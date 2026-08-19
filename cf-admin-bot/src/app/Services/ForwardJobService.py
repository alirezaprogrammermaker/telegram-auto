"""Forward job management — D1 persistence + GitHub profile sync + GHA dispatch."""
from __future__ import annotations

import json
from typing import Any

from app.Support.Time import utc_now_iso


class ForwardJobService:
    """CRUD for forward_jobs in D1, with GitHub profile sync helpers."""

    def __init__(self, db) -> None:
        self.db = db

    # ──────────────────────────────────────────────────────────────────
    # Schema
    # ──────────────────────────────────────────────────────────────────

    @classmethod
    async def ensure_schema(cls, db) -> None:
        await db.prepare(
            """
            CREATE TABLE IF NOT EXISTS forward_jobs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              account_id TEXT NOT NULL,
              owner_id INTEGER NOT NULL,
              source TEXT NOT NULL,
              destination TEXT NOT NULL,
              options_json TEXT NOT NULL DEFAULT '{}',
              enabled INTEGER NOT NULL DEFAULT 1,
              auto_join INTEGER NOT NULL DEFAULT 1,
              filter_remove_links INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              last_dispatched_at TEXT,
              last_run_id INTEGER,
              last_run_status TEXT
            )
            """
        ).run()
        await db.prepare(
            "CREATE INDEX IF NOT EXISTS idx_forward_jobs_owner ON forward_jobs(owner_id, enabled)"
        ).run()
        await db.prepare(
            "CREATE INDEX IF NOT EXISTS idx_forward_jobs_account ON forward_jobs(account_id)"
        ).run()

    # ──────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _row(raw) -> dict[str, Any] | None:
        if raw is None:
            return None
        if hasattr(raw, "to_py"):
            raw = raw.to_py()
        if isinstance(raw, dict):
            return raw
        return None

    @staticmethod
    def _rows(result) -> list[dict[str, Any]]:
        rows = getattr(result, "results", None)
        if hasattr(rows, "to_py"):
            rows = rows.to_py()
        if not isinstance(rows, list):
            return []
        out = []
        for r in rows:
            if hasattr(r, "to_py"):
                r = r.to_py()
            if isinstance(r, dict):
                out.append(r)
        return out

    # ──────────────────────────────────────────────────────────────────
    # CRUD
    # ──────────────────────────────────────────────────────────────────

    async def create_job(
        self,
        *,
        account_id: str,
        owner_id: int,
        source: str,
        destination: str,
        auto_join: bool = True,
        filter_remove_links: bool = False,
        options: dict | None = None,
    ) -> int:
        """Insert a new forward job and return its id."""
        now = utc_now_iso()
        stmt = await self.db.prepare(
            """
            INSERT INTO forward_jobs
              (account_id, owner_id, source, destination, options_json,
               enabled, auto_join, filter_remove_links, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """
        ).bind(
            account_id,
            owner_id,
            source,
            destination,
            json.dumps(options or {}, ensure_ascii=False),
            int(auto_join),
            int(filter_remove_links),
            now,
            now,
        ).run()
        meta = getattr(stmt, "meta", None) or {}
        row_id = getattr(stmt, "last_row_id", None) or (
            meta.get("last_row_id") if isinstance(meta, dict) else None
        )
        if row_id:
            return int(row_id)
        # fallback: fetch latest
        res = await self.db.prepare(
            "SELECT id FROM forward_jobs WHERE account_id=? AND owner_id=? AND source=? ORDER BY id DESC LIMIT 1"
        ).bind(account_id, owner_id, source).first()
        return int((self._row(res) or {}).get("id") or 0)

    async def list_for_owner(
        self, owner_id: int, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        res = await self.db.prepare(
            "SELECT * FROM forward_jobs WHERE owner_id=? ORDER BY id DESC LIMIT ?"
        ).bind(owner_id, limit).all()
        return self._rows(res)

    async def list_for_account(
        self, account_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        res = await self.db.prepare(
            "SELECT * FROM forward_jobs WHERE account_id=? ORDER BY id DESC LIMIT ?"
        ).bind(account_id, limit).all()
        return self._rows(res)

    async def get(self, job_id: int) -> dict[str, Any] | None:
        res = await self.db.prepare(
            "SELECT * FROM forward_jobs WHERE id=? LIMIT 1"
        ).bind(job_id).first()
        return self._row(res)

    async def set_enabled(self, job_id: int, enabled: bool) -> None:
        await self.db.prepare(
            "UPDATE forward_jobs SET enabled=?, updated_at=? WHERE id=?"
        ).bind(int(enabled), utc_now_iso(), job_id).run()

    async def delete(self, job_id: int) -> None:
        await self.db.prepare(
            "DELETE FROM forward_jobs WHERE id=?"
        ).bind(job_id).run()

    async def mark_dispatched(
        self, job_id: int, *, run_id: int | None = None, run_status: str = "queued"
    ) -> None:
        await self.db.prepare(
            """
            UPDATE forward_jobs
               SET last_dispatched_at=?, last_run_id=?, last_run_status=?, updated_at=?
             WHERE id=?
            """
        ).bind(utc_now_iso(), run_id, run_status, utc_now_iso(), job_id).run()

    # ──────────────────────────────────────────────────────────────────
    # Route dict builder (for GitHub profile)
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def job_to_route(job: dict[str, Any]) -> dict[str, Any]:
        """Convert a D1 forward_job row into a channel_forward route dict."""
        options: dict = {}
        raw_opts = job.get("options_json") or "{}"
        if isinstance(raw_opts, str):
            try:
                options = json.loads(raw_opts)
            except Exception:
                options = {}
        elif isinstance(raw_opts, dict):
            options = raw_opts

        route: dict[str, Any] = {
            "source": str(job.get("source") or ""),
            "destination": str(job.get("destination") or ""),
            "destinations": [str(job.get("destination") or "")],
            "enabled": bool(job.get("enabled", 1)),
            "paused": False,
            "visibility": options.get("visibility", "private"),
            "filter": {
                "enabled": bool(job.get("filter_remove_links")),
                "remove_links": bool(job.get("filter_remove_links")),
                "remove_mentions": bool(options.get("filter_remove_mentions", False)),
                "remove_hashtags": bool(options.get("filter_remove_hashtags", False)),
                "remove_ids": False,
                "prefix": options.get("prefix", ""),
                "suffix": options.get("suffix", ""),
                "collapse_whitespace": True,
                "block_enabled": False,
                "block_words": [],
                "allow_enabled": False,
                "allow_words": [],
                "regex_enabled": False,
                "regex_pattern": "",
                "regex_must_match": True,
                "link_replacements": {},
            },
            "media_filter": {"enabled": False, "allow": [], "deny": []},
            "schedule": {
                "enabled": False,
                "timezone": "Asia/Tehran",
                "days": [],
                "windows": [{"start": "09:00", "end": "23:00"}],
            },
            "dedup": {"enabled": False, "window_hours": 24},
            "delivery": {
                "pin_latest": False,
                "button_text": "",
                "button_url": "",
                "sync_edits": True,
                "sync_deletes": True,
                "preserve_reply": False,
                "media_prefix": "",
                "media_suffix": "",
            },
        }
        return route

    @staticmethod
    def build_module_patch(
        jobs: list[dict[str, Any]],
        *,
        auto_join: bool = True,
    ) -> dict[str, Any]:
        """Build a channel_forward module patch from a list of D1 jobs."""
        routes = [ForwardJobService.job_to_route(j) for j in jobs if j.get("enabled")]
        return {
            "enabled": True,
            "auto_join": auto_join,
            "dry_run": False,
            "paused": False,
            "delay_seconds": 1.5,
            "forward_mode": "copy",
            "catch_up_enabled": True,
            "catch_up_limit": 50,
            "routes": routes,
        }
