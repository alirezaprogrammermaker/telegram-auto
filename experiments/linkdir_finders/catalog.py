"""Persistent shared catalog of ranked لینکدونی candidates.

Local JSON under data/pool/ is an offline cache. When
ADMIN_BOT_BRIDGE_URL + ADMIN_BOT_BRIDGE_TOKEN are set, D1 (via the admin-bot
bridge) is the shared source of truth for list/counts and receives best-effort
upsert sync after local writes.

Not yet wired into promo_spread runtime; this is the data foundation.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.paths import ensure_pool_dir, pool_path
from app.storage import load_json, save_json

CATALOG_NAME = "linkdir_catalog.json"
PROMO_EXPORT_NAME = "linkdir_promo_ready.json"
_SYNC_CHUNK = 40

VERDICTS = ("keep", "review", "junk")
logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def catalog_key(ref: str) -> str:
    text = (ref or "").strip().lower()
    if text.startswith("@"):
        text = text[1:]
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def normalize_ref(username: str | None, chat_id: Any = None) -> str | None:
    if username:
        u = str(username).strip().lstrip("@")
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,}", u):
            return f"@{u}"
    if chat_id is not None:
        return f"id:{chat_id}"
    return None


class LinkDirCatalog:
    """Thread-safe ranked directory catalog (local JSON cache + optional D1)."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        collector_id: str | None = None,
    ) -> None:
        ensure_pool_dir()
        self.path = path or pool_path(CATALOG_NAME)
        self.collector_id = (collector_id or "").strip() or None
        self._lock = threading.Lock()
        self._pending_sync: dict[str, dict[str, Any]] = {}
        self._data = load_json(
            self.path,
            {"version": 1, "items": {}, "meta": {}},
        )
        if not isinstance(self._data.get("items"), dict):
            self._data["items"] = {}
        if not isinstance(self._data.get("meta"), dict):
            self._data["meta"] = {}

    def _save_locked(self) -> None:
        """Persist local JSON. Caller must hold self._lock."""
        self._data["meta"]["updated_at"] = utc_now()
        self._data["version"] = 1
        save_json(self.path, self._data)

    def _queue_sync_locked(self, item: dict[str, Any]) -> None:
        key = str(item.get("key") or "")
        if key:
            self._pending_sync[key] = dict(item)

    def _take_pending_sync(self) -> list[dict[str, Any]]:
        with self._lock:
            batch = list(self._pending_sync.values())
            self._pending_sync.clear()
            return batch

    def _requeue_sync(self, items: list[dict[str, Any]]) -> None:
        with self._lock:
            for item in items:
                key = str(item.get("key") or "")
                if key:
                    self._pending_sync[key] = item

    def _flush_bridge_sync(self) -> None:
        """Best-effort push of pending items to D1; never raises."""
        batch = self._take_pending_sync()
        if not batch:
            return
        try:
            from app.linkdir_bridge import is_available, upsert_items
        except Exception:
            self._requeue_sync(batch)
            return
        if not is_available():
            # Offline / no bridge: local JSON is enough; drop sync queue.
            return
        method = str(
            (batch[-1].get("last_method") if batch else None) or "local_catalog"
        )
        try:
            failed: list[dict[str, Any]] = []
            for i in range(0, len(batch), _SYNC_CHUNK):
                chunk = batch[i : i + _SYNC_CHUNK]
                resp = upsert_items(
                    chunk, collector_id=self.collector_id, method=method
                )
                if not resp or not resp.get("ok"):
                    logger.warning(
                        "linkdir bridge upsert failed for %s items", len(chunk)
                    )
                    failed.extend(chunk)
                    failed.extend(batch[i + _SYNC_CHUNK :])
                    break
            if failed:
                self._requeue_sync(failed)
        except Exception as exc:
            logger.warning("linkdir bridge sync error: %s", exc)
            self._requeue_sync(batch)

    def upsert_from_search(
        self, row: dict[str, Any], *, method: str, save: bool = True
    ) -> dict[str, Any]:
        """Merge one search/rank row into the catalog."""
        ref = normalize_ref(row.get("username"), row.get("id")) or row.get("ref")
        if not ref:
            raise ValueError("row has no ref")
        key = catalog_key(ref)
        now = utc_now()
        verdict = str(row.get("verdict") or "junk")
        if verdict not in VERDICTS:
            verdict = "junk"

        with self._lock:
            items = self._data.setdefault("items", {})
            prev = items.get(key)
            is_new = not isinstance(prev, dict)
            if is_new:
                item: dict[str, Any] = {
                    "key": key,
                    "ref": ref,
                    "created_at": now,
                    "seen_count": 0,
                    "methods": [],
                    "queries": [],
                }
            else:
                item = dict(prev)

            item["ref"] = ref
            item["username"] = row.get("username")
            item["title"] = row.get("title")
            item["chat_id"] = row.get("id")
            item["is_channel"] = bool(row.get("is_channel"))
            item["is_group"] = bool(row.get("is_group"))
            if row.get("kind"):
                item["kind"] = row.get("kind")
            if "members_can_send" in row:
                item["members_can_send"] = row.get("members_can_send")
            if "postable" in row:
                item["postable"] = row.get("postable")
            if "broadcast" in row:
                item["broadcast"] = row.get("broadcast")
            if "megagroup" in row:
                item["megagroup"] = row.get("megagroup")
            if "gigagroup" in row:
                item["gigagroup"] = row.get("gigagroup")
            if row.get("participants") is not None:
                item["participants"] = row.get("participants")
            if row.get("about") and not str(row.get("about")).startswith("<"):
                item["about"] = row.get("about")

            item["identity_score"] = row.get("identity_score")
            item["quality_score"] = row.get("quality_score")
            item["rank_score"] = row.get("rank_score") or row.get("score")
            item["verdict"] = verdict
            item["reasons"] = row.get("reasons") or []
            item["gates"] = row.get("gates") or []
            if row.get("activity") is not None:
                item["activity"] = row.get("activity")
            if row.get("parent_seed"):
                item["parent_seed"] = row.get("parent_seed")

            item["seen_count"] = int(item.get("seen_count") or 0) + 1
            item["last_seen_at"] = now
            item["last_ranked_at"] = now
            item["last_method"] = method

            methods = item.setdefault("methods", [])
            if method not in methods:
                methods.append(method)
            item["methods"] = methods[-10:]

            q = row.get("query")
            queries = item.setdefault("queries", [])
            if q and q not in queries:
                queries.append(q)
            item["queries"] = queries[-20:]

            # Promo destinations MUST allow member posting.
            postable = row.get("members_can_send")
            if postable is None:
                postable = row.get("postable")
            if row.get("promo_eligible") is not None:
                promo_ok = bool(row.get("promo_eligible"))
            else:
                promo_ok = postable is True

            if verdict == "keep" and promo_ok:
                item["status"] = "active"
                item["promo_ready"] = True
            elif verdict == "keep" and not promo_ok:
                # Useful as seed/source, not as promo target
                item["status"] = "review"
                item["verdict"] = "review"
                item["promo_ready"] = False
                item["seed_only"] = True
            elif verdict == "review":
                item["status"] = "review"
                item["promo_ready"] = False
                item["seed_only"] = postable is False
            else:
                item["status"] = "junk"
                item["promo_ready"] = False
                item["seed_only"] = False

            items[key] = item
            self._queue_sync_locked(item)
            self._data["meta"]["last_refresh_method"] = method
            self._data["meta"]["last_refresh_at"] = now
            if save:
                self._save_locked()
            out = dict(item)

        if save:
            self._flush_bridge_sync()
        return out

    def save(self) -> None:
        with self._lock:
            self._save_locked()
        self._flush_bridge_sync()

    def known_refs(self) -> set[str]:
        with self._lock:
            rows = (self._data.get("items") or {}).values()
            out: set[str] = set()
            for item in rows:
                if not isinstance(item, dict):
                    continue
                ref = str(item.get("ref") or "")
                if ref:
                    out.add(ref.lower())
                uname = item.get("username")
                if uname:
                    out.add(f"@{str(uname).lower()}")
            return out

    def seeds_for_snowball(
        self,
        *,
        limit: int = 12,
        min_rank: float = 70.0,
        prefer_seed_only: bool = True,
    ) -> list[dict[str, Any]]:
        # Prefer postable keeps, but locked linkdirs are excellent harvest seeds too.
        ready = self.list_items(promo_ready=True, limit=max(limit * 2, limit))
        review = self.list_items(status="review", limit=max(limit * 4, limit))
        rows = ready + review
        filtered: list[dict[str, Any]] = []
        seen: set[str] = set()
        for r in rows:
            uname = r.get("username")
            if not uname:
                continue
            key = str(uname).lower()
            if key in seen:
                continue
            if float(r.get("rank_score") or 0) < min_rank and not r.get("seed_only"):
                if float(r.get("identity_score") or 0) < 55:
                    continue
            seen.add(key)
            filtered.append(r)

        if prefer_seed_only:
            def _seed_key(r: dict[str, Any]) -> tuple:
                title = str(r.get("title") or "")
                uname = str(r.get("username") or "").lower()
                persianish = any(
                    tok in title or tok in uname
                    for tok in ("لینک", "doni", "گپ", "تبلیغ", "تبادل")
                )
                age = (r.get("activity") or {}).get("last_message_age_hours")
                fresh = isinstance(age, (int, float)) and age < 72
                return (
                    1 if r.get("seed_only") and persianish else 0,
                    1 if persianish else 0,
                    1 if fresh else 0,
                    1 if r.get("seed_only") else 0,
                    float(r.get("identity_score") or 0),
                    float(r.get("rank_score") or 0),
                )

            filtered.sort(key=_seed_key, reverse=True)
        else:
            filtered.sort(
                key=lambda r: (
                    1 if r.get("promo_ready") else 0,
                    float(r.get("rank_score") or 0),
                ),
                reverse=True,
            )
        return filtered[: max(1, limit)]

    def items_for_rerank(
        self,
        *,
        limit: int = 40,
        include_review: bool = True,
        include_stale: bool = True,
        stale_limit: int = 15,
    ) -> list[dict[str, Any]]:
        active = self.list_items(status="active", limit=limit)
        out = list(active)
        if include_review and len(out) < limit:
            need = limit - len(out)
            out.extend(self.list_items(status="review", limit=need))
        if include_stale:
            stale = self.list_items(status="stale", limit=stale_limit)
            # Prefer recently large / high identity stale for revival attempts
            stale.sort(key=lambda r: float(r.get("identity_score") or 0), reverse=True)
            out.extend(stale[:stale_limit])
        # de-dupe by key
        seen: set[str] = set()
        uniq: list[dict[str, Any]] = []
        for row in out:
            key = str(row.get("key") or row.get("ref"))
            if key in seen:
                continue
            seen.add(key)
            uniq.append(row)
        return uniq[: max(1, limit + (stale_limit if include_stale else 0))]

    def record_pipeline_run(self, summary: dict[str, Any]) -> None:
        with self._lock:
            meta = self._data.setdefault("meta", {})
            history = meta.setdefault("pipeline_runs", [])
            if not isinstance(history, list):
                history = []
            history.append(summary)
            meta["pipeline_runs"] = history[-30:]
            meta["last_pipeline_at"] = utc_now()
            meta["last_pipeline"] = summary
            self._save_locked()
        self._flush_bridge_sync()
        try:
            from app.linkdir_bridge import is_available, record_run

            if is_available():
                record_run(
                    {
                        "collector_id": summary.get("collector_id")
                        or summary.get("account_id"),
                        "method": summary.get("method") or summary.get("phase"),
                        "summary": summary,
                        "started_at": summary.get("started_at"),
                        "finished_at": summary.get("finished_at") or utc_now(),
                    }
                )
        except Exception as exc:
            logger.warning("linkdir bridge record_run failed: %s", exc)

    def mark_stale(self, *, older_than_hours: float = 72.0) -> int:
        """Mark active/review items not seen recently as stale (not deleted)."""
        now = datetime.now(timezone.utc)
        n = 0
        with self._lock:
            for item in (self._data.get("items") or {}).values():
                if not isinstance(item, dict):
                    continue
                if item.get("status") not in {"active", "review"}:
                    continue
                last = item.get("last_ranked_at") or item.get("last_seen_at")
                if not last:
                    continue
                try:
                    dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                except ValueError:
                    continue
                age_h = (now - dt).total_seconds() / 3600.0
                if age_h > older_than_hours:
                    item["status"] = "stale"
                    item["promo_ready"] = False
                    item["stale_at"] = utc_now()
                    n += 1
            if n:
                self._save_locked()
        if n:
            self._flush_bridge_sync()
        try:
            from app.linkdir_bridge import is_available, mark_stale as bridge_mark_stale

            if is_available():
                bridge_mark_stale(older_than_hours=older_than_hours)
        except Exception as exc:
            logger.warning("linkdir bridge mark_stale failed: %s", exc)
        return n

    def _local_list_items(
        self,
        *,
        verdict: str | None = None,
        promo_ready: bool | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = [
                dict(x)
                for x in (self._data.get("items") or {}).values()
                if isinstance(x, dict)
            ]
        if verdict:
            rows = [r for r in rows if r.get("verdict") == verdict]
        if status:
            rows = [r for r in rows if r.get("status") == status]
        if promo_ready is not None:
            rows = [r for r in rows if bool(r.get("promo_ready")) is promo_ready]
        rows.sort(
            key=lambda r: (
                1 if r.get("promo_ready") else 0,
                float(r.get("rank_score") or 0),
            ),
            reverse=True,
        )
        return rows[: max(1, limit)]

    def list_items(
        self,
        *,
        verdict: str | None = None,
        promo_ready: bool | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        try:
            from app.linkdir_bridge import is_available, list_items as bridge_list

            if is_available():
                remote = bridge_list(
                    promo_ready=promo_ready,
                    verdict=verdict,
                    status=status,
                    limit=limit,
                )
                if remote is not None:
                    return remote
        except Exception as exc:
            logger.warning("linkdir bridge list_items failed: %s", exc)
        return self._local_list_items(
            verdict=verdict,
            promo_ready=promo_ready,
            status=status,
            limit=limit,
        )

    def _local_counts(self) -> dict[str, int]:
        with self._lock:
            rows = [
                x for x in (self._data.get("items") or {}).values() if isinstance(x, dict)
            ]
        out = {
            "total": len(rows),
            "promo_ready": 0,
            "verdict_keep": 0,
            "verdict_review": 0,
            "verdict_junk": 0,
            "status_active": 0,
            "status_review": 0,
            "status_junk": 0,
            "status_stale": 0,
            # aliases used by CLI prints
            "keep": 0,
            "review": 0,
            "junk": 0,
            "active": 0,
            "stale": 0,
        }
        for r in rows:
            v = str(r.get("verdict") or "")
            if v == "keep":
                out["verdict_keep"] += 1
                out["keep"] += 1
            elif v == "review":
                out["verdict_review"] += 1
                out["review"] += 1
            elif v == "junk":
                out["verdict_junk"] += 1
                out["junk"] += 1

            s = str(r.get("status") or "")
            if s == "active":
                out["status_active"] += 1
                out["active"] += 1
            elif s == "review":
                out["status_review"] += 1
            elif s == "junk":
                out["status_junk"] += 1
            elif s == "stale":
                out["status_stale"] += 1
                out["stale"] += 1

            if r.get("promo_ready"):
                out["promo_ready"] += 1
        return out

    def counts(self) -> dict[str, int]:
        try:
            from app.linkdir_bridge import counts as bridge_counts, is_available

            if is_available():
                remote = bridge_counts()
                if isinstance(remote, dict) and "total" in remote:
                    # Preserve CLI aliases expected by local callers
                    out = dict(remote)
                    out.setdefault("keep", int(out.get("verdict_keep") or 0))
                    out.setdefault("review", int(out.get("verdict_review") or 0))
                    out.setdefault("junk", int(out.get("verdict_junk") or 0))
                    out.setdefault("active", int(out.get("status_active") or 0))
                    out.setdefault("stale", int(out.get("status_stale") or 0))
                    return out
        except Exception as exc:
            logger.warning("linkdir bridge counts failed: %s", exc)
        return self._local_counts()

    def export_promo_ready(self, *, path: Path | None = None, limit: int = 200) -> Path:
        """Write a slim JSON list promo accounts can consume later."""
        # Prefer local cache for export file contents so offline runners stay consistent;
        # D1 may already hold the same rows via sync.
        rows = self._local_list_items(promo_ready=True, limit=limit)
        if not rows:
            rows = self.list_items(promo_ready=True, limit=limit)
        slim = []
        for r in rows:
            slim.append(
                {
                    "ref": r.get("ref"),
                    "username": r.get("username"),
                    "title": r.get("title"),
                    "participants": r.get("participants"),
                    "rank_score": r.get("rank_score"),
                    "identity_score": r.get("identity_score"),
                    "quality_score": r.get("quality_score"),
                    "last_ranked_at": r.get("last_ranked_at"),
                    "activity": {
                        "last_message_age_hours": (r.get("activity") or {}).get(
                            "last_message_age_hours"
                        ),
                        "link_count": (r.get("activity") or {}).get("link_count"),
                        "msgs_per_day_est": (r.get("activity") or {}).get(
                            "msgs_per_day_est"
                        ),
                    },
                }
            )
        ensure_pool_dir()
        out = path or pool_path(PROMO_EXPORT_NAME)
        payload = {
            "version": 1,
            "generated_at": utc_now(),
            "source": str(self.path.name),
            "count": len(slim),
            "items": slim,
        }
        save_json(out, payload)
        with self._lock:
            self._data.setdefault("meta", {})["last_promo_export_at"] = utc_now()
            self._data["meta"]["last_promo_export_count"] = len(slim)
            self._save_locked()
        self._flush_bridge_sync()
        return out
