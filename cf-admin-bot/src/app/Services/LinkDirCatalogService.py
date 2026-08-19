"""Link-directory catalog persistence on D1 (control-plane source of truth)."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.Models.LinkDir import (
    LinkDirCollector,
    LinkDirEvent,
    LinkDirItem,
    LinkDirJob,
    LinkDirRun,
    dumps_json,
    loads_json,
)
from app.Models.Model import row_to_dict
from app.Support.Time import utc_now_iso

VERDICTS = ("keep", "review", "junk")
STATUSES = ("active", "review", "junk", "stale")


def catalog_key(ref: str) -> str:
    text = (ref or "").strip().lower()
    if text.startswith("@"):
        text = text[1:]
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def normalize_ref(username: str | None, chat_id: Any = None, ref: Any = None) -> str | None:
    if username:
        u = str(username).strip().lstrip("@")
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,}", u):
            return f"@{u}"
    if ref:
        text = str(ref).strip()
        if text:
            return text
    if chat_id is not None:
        return f"id:{chat_id}"
    return None


def _tri_bool(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if bool(value) else 0


class LinkDirCatalogService:
    def __init__(self, db, *, r2_bucket: Any | None = None) -> None:
        self.db = db
        # Optional: publish a daily promo export into an R2 object so promo sync
        # doesn't hit D1 repeatedly.
        self.r2_bucket = r2_bucket

    _PROMO_EXPORT_KEY = "linkdir/promo_ready.json"

    async def publish_promo_ready_to_r2(
        self,
        *,
        limit: int = 500,
        key: str | None = None,
    ) -> dict[str, Any]:
        """Best-effort: export promo-ready catalog and store it in R2."""
        if self.r2_bucket is None:
            return {"ok": False, "error": "r2_unconfigured"}
        storage_key = str(key or self._PROMO_EXPORT_KEY)
        payload = await self.export_promo_ready(limit=limit)
        # Mark the payload origin (optional but helpful for debugging).
        payload["source"] = f"r2:{storage_key}"
        raw = dumps_json(payload) or "{}"

        await self.r2_bucket.put(
            storage_key,
            raw,
            httpMetadata={"contentType": "application/json; charset=utf-8"},
        )
        return {"ok": True, "key": storage_key, "count": payload.get("count")}

    async def load_promo_ready_from_r2_or_d1(
        self,
        *,
        limit: int = 200,
        key: str | None = None,
    ) -> dict[str, Any]:
        """Read promo_ready.json from R2, fallback to D1 export when missing."""
        if self.r2_bucket is None:
            return await self.export_promo_ready(limit=limit)

        storage_key = str(key or self._PROMO_EXPORT_KEY)
        try:
            obj = await self.r2_bucket.get(storage_key)
        except Exception:
            obj = None

        if obj is not None:
            raw = getattr(obj, "body", None)
            if raw is not None:
                try:
                    if isinstance(raw, (bytes, bytearray)):
                        text = raw.decode("utf-8", errors="replace")
                    else:
                        text = str(raw)
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        # Ensure a consistent shape even if old payloads exist.
                        if parsed.get("items") is None:
                            parsed["items"] = []
                        return parsed
                except Exception:
                    pass

        return await self.export_promo_ready(limit=limit)

    async def upsert_items(
        self,
        items: list[dict[str, Any]],
        *,
        collector_id: str | None = None,
        method: str = "bridge",
    ) -> dict[str, Any]:
        upserted = 0
        errors = 0
        for raw in items:
            if not isinstance(raw, dict):
                errors += 1
                continue
            try:
                await self._upsert_one(
                    raw,
                    collector_id=collector_id,
                    method=str(raw.get("last_method") or method),
                )
                upserted += 1
            except ValueError:
                errors += 1
        return {"upserted": upserted, "errors": errors}

    async def _upsert_one(
        self,
        row: dict[str, Any],
        *,
        collector_id: str | None,
        method: str,
    ) -> dict[str, Any]:
        ref = normalize_ref(
            row.get("username"), row.get("chat_id") or row.get("id"), row.get("ref")
        )
        if not ref:
            raise ValueError("row has no ref")
        key = str(row.get("key") or catalog_key(ref))
        now = utc_now_iso()
        verdict = str(row.get("verdict") or "junk")
        if verdict not in VERDICTS:
            verdict = "junk"

        existing = await LinkDirItem.find(self.db, key)
        prev = existing.to_dict() if existing else {}
        is_new = not bool(prev)

        methods = loads_json(prev.get("methods_json"), [])
        if not isinstance(methods, list):
            methods = []
        if method and method not in methods:
            methods.append(method)
        methods = methods[-10:]

        queries = loads_json(prev.get("queries_json"), [])
        if not isinstance(queries, list):
            queries = []
        q = row.get("query")
        if q and q not in queries:
            queries.append(q)
        for extra_q in row.get("queries") or []:
            if extra_q and extra_q not in queries:
                queries.append(extra_q)
        queries = queries[-20:]

        reasons = row.get("reasons")
        if reasons is None:
            reasons = loads_json(prev.get("reasons_json"), [])
        gates = row.get("gates")
        if gates is None:
            gates = loads_json(prev.get("gates_json"), [])
        activity = row.get("activity")
        if activity is None and prev.get("activity_json"):
            activity = loads_json(prev.get("activity_json"), None)

        postable = row.get("members_can_send")
        if postable is None:
            postable = row.get("postable")
        if row.get("promo_eligible") is not None:
            promo_ok = bool(row.get("promo_eligible"))
        else:
            promo_ok = postable is True

        seed_only = False
        if verdict == "keep" and promo_ok:
            status = "active"
            promo_ready = True
        elif verdict == "keep" and not promo_ok:
            status = "review"
            verdict = "review"
            promo_ready = False
            seed_only = True
        elif verdict == "review":
            status = "review"
            promo_ready = False
            seed_only = postable is False
        else:
            status = "junk"
            promo_ready = False
            seed_only = False

        if row.get("status") in STATUSES and row.get("status") == "stale":
            status = "stale"
            promo_ready = False

        if row.get("seed_only") is True:
            seed_only = True

        seen_count = int(prev.get("seen_count") or 0) + 1
        if row.get("seen_count") is not None and int(row.get("seen_count") or 0) > seen_count:
            seen_count = int(row["seen_count"])

        members_can_send_col = prev.get("members_can_send")
        if "members_can_send" in row or "postable" in row:
            members_can_send_col = _tri_bool(postable)

        postable_col = prev.get("postable")
        if "postable" in row:
            postable_col = _tri_bool(row.get("postable"))
        elif postable is not None:
            postable_col = _tri_bool(postable)

        payload = {
            "key": key,
            "ref": ref,
            "username": row.get("username")
            if row.get("username") is not None
            else prev.get("username"),
            "chat_id": row.get("chat_id")
            if row.get("chat_id") is not None
            else row.get("id", prev.get("chat_id")),
            "invite_hash": row.get("invite_hash")
            if row.get("invite_hash") is not None
            else prev.get("invite_hash"),
            "title": row.get("title") if row.get("title") is not None else prev.get("title"),
            "about": row.get("about")
            if row.get("about") and not str(row.get("about")).startswith("<")
            else prev.get("about"),
            "kind": row.get("kind") if row.get("kind") is not None else prev.get("kind"),
            "is_channel": 1 if bool(row.get("is_channel", prev.get("is_channel"))) else 0,
            "is_group": 1 if bool(row.get("is_group", prev.get("is_group"))) else 0,
            "broadcast": 1 if bool(row.get("broadcast", prev.get("broadcast"))) else 0,
            "megagroup": 1 if bool(row.get("megagroup", prev.get("megagroup"))) else 0,
            "gigagroup": 1 if bool(row.get("gigagroup", prev.get("gigagroup"))) else 0,
            "members_can_send": members_can_send_col,
            "postable": postable_col,
            "participants": row.get("participants")
            if row.get("participants") is not None
            else prev.get("participants"),
            "identity_score": row.get("identity_score")
            if row.get("identity_score") is not None
            else prev.get("identity_score"),
            "quality_score": row.get("quality_score")
            if row.get("quality_score") is not None
            else prev.get("quality_score"),
            "rank_score": row.get("rank_score")
            if row.get("rank_score") is not None
            else row.get("score", prev.get("rank_score")),
            "verdict": verdict,
            "status": status,
            "promo_ready": 1 if promo_ready else 0,
            "seed_only": 1 if seed_only else 0,
            "reasons_json": dumps_json(reasons),
            "gates_json": dumps_json(gates),
            "activity_json": dumps_json(activity),
            "methods_json": dumps_json(methods),
            "queries_json": dumps_json(queries),
            "parent_seed": row.get("parent_seed")
            if row.get("parent_seed") is not None
            else prev.get("parent_seed"),
            "last_method": method,
            "seen_count": seen_count,
            "first_seen_at": prev.get("first_seen_at") or row.get("first_seen_at") or now,
            "last_seen_at": now,
            "last_ranked_at": now,
            "stale_at": (prev.get("stale_at") or now) if status == "stale" else prev.get("stale_at"),
            "created_at": prev.get("created_at") or now,
            "updated_at": now,
        }

        if existing:
            await LinkDirItem.query(self.db).where("key", key).update(payload)
        else:
            await LinkDirItem.query(self.db).insert(payload)

        await LinkDirEvent.query(self.db).insert(
            {
                "item_key": key,
                "event_type": "upsert_new" if is_new else "upsert",
                "collector_id": collector_id,
                "method": method,
                "payload_json": dumps_json(
                    {
                        "ref": ref,
                        "verdict": verdict,
                        "rank_score": payload.get("rank_score"),
                        "promo_ready": promo_ready,
                    }
                ),
                "created_at": now,
            }
        )
        return payload

    async def list_items(
        self,
        *,
        verdict: str | None = None,
        status: str | None = None,
        promo_ready: bool | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(500, int(limit)))
        clauses: list[str] = []
        params: list[Any] = []
        if verdict:
            clauses.append("verdict = ?")
            params.append(verdict)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if promo_ready is not None:
            clauses.append("promo_ready = ?")
            params.append(1 if promo_ready else 0)
        sql = "SELECT * FROM linkdir_items"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY promo_ready DESC, rank_score DESC LIMIT ?"
        params.append(limit)
        result = await self.db.prepare(sql).bind(*params).all()
        rows = getattr(result, "results", None)
        if hasattr(rows, "to_py"):
            rows = rows.to_py()
        if not isinstance(rows, list):
            return []
        out: list[dict[str, Any]] = []
        for row in rows:
            data = row_to_dict(row)
            if data:
                out.append(LinkDirItem.from_row(data).to_api())
        return out

    async def counts(self) -> dict[str, int]:
        sql = """
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN promo_ready = 1 THEN 1 ELSE 0 END) AS promo_ready,
          SUM(CASE WHEN verdict = 'keep' THEN 1 ELSE 0 END) AS verdict_keep,
          SUM(CASE WHEN verdict = 'review' THEN 1 ELSE 0 END) AS verdict_review,
          SUM(CASE WHEN verdict = 'junk' THEN 1 ELSE 0 END) AS verdict_junk,
          SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS status_active,
          SUM(CASE WHEN status = 'review' THEN 1 ELSE 0 END) AS status_review,
          SUM(CASE WHEN status = 'junk' THEN 1 ELSE 0 END) AS status_junk,
          SUM(CASE WHEN status = 'stale' THEN 1 ELSE 0 END) AS status_stale
        FROM linkdir_items
        """
        row = await self.db.prepare(sql).first()
        data = row_to_dict(row) or {}
        out = {
            "total": int(data.get("total") or 0),
            "promo_ready": int(data.get("promo_ready") or 0),
            "verdict_keep": int(data.get("verdict_keep") or 0),
            "verdict_review": int(data.get("verdict_review") or 0),
            "verdict_junk": int(data.get("verdict_junk") or 0),
            "status_active": int(data.get("status_active") or 0),
            "status_review": int(data.get("status_review") or 0),
            "status_junk": int(data.get("status_junk") or 0),
            "status_stale": int(data.get("status_stale") or 0),
        }
        out["keep"] = out["verdict_keep"]
        out["review"] = out["verdict_review"]
        out["junk"] = out["verdict_junk"]
        out["active"] = out["status_active"]
        out["stale"] = out["status_stale"]
        return out

    async def mark_stale(self, *, older_than_hours: float = 72.0) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(hours=float(older_than_hours))).replace(microsecond=0).isoformat()
        stamp = utc_now_iso()
        sql = """
        UPDATE linkdir_items
        SET status = 'stale',
            promo_ready = 0,
            stale_at = ?,
            updated_at = ?
        WHERE status IN ('active', 'review')
          AND COALESCE(last_ranked_at, last_seen_at) < ?
        """
        result = await self.db.prepare(sql).bind(stamp, stamp, cutoff).run()
        changes = 0
        try:
            meta = getattr(result, "meta", None)
            if meta is not None:
                if hasattr(meta, "to_py"):
                    meta = meta.to_py()
                if isinstance(meta, dict) and "changes" in meta:
                    changes = int(meta["changes"])
                elif hasattr(meta, "changes"):
                    changes = int(meta.changes)
        except Exception:
            changes = 0
        return {"stale_marked": changes, "cutoff": cutoff}

    async def export_promo_ready(self, *, limit: int = 200) -> dict[str, Any]:
        rows = await self.list_items(promo_ready=True, limit=limit)
        slim = []
        for r in rows:
            act = r.get("activity") or {}
            slim.append(
                {
                    "ref": r.get("ref"),
                    "parent_seed": r.get("parent_seed"),
                    "username": r.get("username"),
                    "title": r.get("title"),
                    "participants": r.get("participants"),
                    "rank_score": r.get("rank_score"),
                    "identity_score": r.get("identity_score"),
                    "quality_score": r.get("quality_score"),
                    "last_ranked_at": r.get("last_ranked_at"),
                    "kind": r.get("kind"),
                    "members_can_send": r.get("members_can_send"),
                    "activity": {
                        "last_message_age_hours": act.get("last_message_age_hours"),
                        "link_count": act.get("link_count"),
                        "msgs_per_day_est": act.get("msgs_per_day_est"),
                    },
                }
            )
        return {
            "version": 1,
            "generated_at": utc_now_iso(),
            "source": "d1:linkdir_items",
            "count": len(slim),
            "items": slim,
        }

    async def collector_heartbeat(self, data: dict[str, Any]) -> dict[str, Any]:
        collector_id = str(data.get("id") or "").strip()
        if not collector_id:
            raise ValueError("missing_collector_id")
        now = utc_now_iso()
        existing = await LinkDirCollector.find(self.db, collector_id)
        status = str(data.get("status") or "idle")
        if status not in {"idle", "running", "circuit", "disabled"}:
            status = "idle"
        payload = {
            "id": collector_id,
            "session_name": data.get("session_name"),
            "label": data.get("label") or collector_id,
            "enabled": 1 if data.get("enabled", True) else 0,
            "status": status,
            "circuit_until": data.get("circuit_until"),
            "circuit_reason": data.get("circuit_reason"),
            "budgets_json": dumps_json(data.get("budgets") or data.get("budgets_json")),
            "last_run_at": data.get("last_run_at") or now,
            "meta_json": dumps_json(data.get("meta") or {}),
            "updated_at": now,
        }
        if existing:
            await LinkDirCollector.query(self.db).where("id", collector_id).update(payload)
        else:
            payload["created_at"] = now
            await LinkDirCollector.query(self.db).insert(payload)
        row = await LinkDirCollector.find(self.db, collector_id)
        return row.to_api() if row else payload

    async def claim_jobs(
        self,
        *,
        owner: str,
        limit: int = 5,
        lease_seconds: int = 900,
        job_type: str | None = None,
    ) -> list[dict[str, Any]]:
        owner = str(owner or "").strip()
        if not owner:
            raise ValueError("missing_lease_owner")
        limit = max(1, min(20, int(limit)))
        now = datetime.now(timezone.utc)
        lease_until = (now + timedelta(seconds=max(60, lease_seconds))).replace(
            microsecond=0
        ).isoformat()
        stamp = utc_now_iso()

        await self.db.prepare(
            """
            UPDATE linkdir_jobs
            SET status = 'pending', lease_owner = NULL, lease_until = NULL, updated_at = ?
            WHERE status = 'leased' AND lease_until IS NOT NULL AND lease_until < ?
            """
        ).bind(stamp, stamp).run()

        clauses = ["status = 'pending'"]
        params: list[Any] = []
        if job_type:
            clauses.append("job_type = ?")
            params.append(job_type)
        sql = (
            "SELECT * FROM linkdir_jobs WHERE "
            + " AND ".join(clauses)
            + " ORDER BY priority ASC, id ASC LIMIT ?"
        )
        params.append(limit)
        result = await self.db.prepare(sql).bind(*params).all()
        rows = getattr(result, "results", None)
        if hasattr(rows, "to_py"):
            rows = rows.to_py()
        claimed: list[dict[str, Any]] = []
        for row in rows or []:
            data = row_to_dict(row)
            if not data:
                continue
            job_id = data.get("id")
            await self.db.prepare(
                """
                UPDATE linkdir_jobs
                SET status = 'leased',
                    lease_owner = ?,
                    lease_until = ?,
                    attempts = attempts + 1,
                    updated_at = ?
                WHERE id = ? AND status = 'pending'
                """
            ).bind(owner, lease_until, stamp, job_id).run()
            fresh = await LinkDirJob.find(self.db, job_id)
            if fresh and fresh.get("lease_owner") == owner:
                claimed.append(fresh.to_api())
        return claimed

    async def complete_job(self, data: dict[str, Any]) -> dict[str, Any]:
        job_id = data.get("id")
        if job_id is None:
            raise ValueError("missing_job_id")
        status = str(data.get("status") or "done")
        if status not in {"done", "failed", "cancelled"}:
            status = "done"
        now = utc_now_iso()
        await self.db.prepare(
            """
            UPDATE linkdir_jobs
            SET status = ?,
                last_error = ?,
                updated_at = ?,
                done_at = ?,
                lease_owner = NULL,
                lease_until = NULL
            WHERE id = ?
            """
        ).bind(
            status,
            data.get("error") or data.get("last_error"),
            now,
            now if status == "done" else None,
            int(job_id),
        ).run()
        row = await LinkDirJob.find(self.db, int(job_id))
        return row.to_api() if row else {"id": job_id, "status": status}

    async def enqueue_job(self, data: dict[str, Any]) -> dict[str, Any]:
        job_type = str(data.get("job_type") or "").strip()
        if not job_type:
            raise ValueError("missing_job_type")
        now = utc_now_iso()
        await LinkDirJob.query(self.db).insert(
            {
                "job_type": job_type,
                "payload_json": dumps_json(data.get("payload") or {}),
                "priority": int(data.get("priority") or 100),
                "status": "pending",
                "attempts": 0,
                "created_at": now,
                "updated_at": now,
            }
        )
        return {"ok": True, "job_type": job_type}

    async def record_run(self, data: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        await LinkDirRun.query(self.db).insert(
            {
                "collector_id": data.get("collector_id"),
                "steps_json": dumps_json(data.get("steps") or []),
                "ok": 1 if data.get("ok", True) else 0,
                "summary_json": dumps_json(data.get("summary") or data),
                "started_at": data.get("started_at") or now,
                "finished_at": data.get("finished_at") or now,
            }
        )
        # Best-effort: keep a fresh R2 snapshot of promo-ready items.
        # This reduces D1 reads from promo sync jobs.
        if self.r2_bucket is not None:
            try:
                await self.publish_promo_ready_to_r2(limit=500)
            except Exception:
                # Don't fail the run record if R2 publish fails.
                pass

        return {"ok": True}
