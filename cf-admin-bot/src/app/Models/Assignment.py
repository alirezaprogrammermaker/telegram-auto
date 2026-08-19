"""Assignment model — one row per forward/promo route assignment.

Each row tracks which account is responsible for a given source channel or
promo route.  The table is the single source of truth for load balancing and
sticky-source lookups in the Smart Assignment Engine.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.Models.Model import Model
from app.Support.Time import utc_now_iso


class Assignment(Model):
    table = "assignments"
    primary_key = "id"
    fillable = (
        "id",
        "user_id",
        "account_id",
        "task_type",
        "source",
        "target",
        "status",
        "score_json",
        "assigned_at",
        "removed_at",
    )

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return str(self.get("status") or "") == "active"

    def to_dict(self) -> dict[str, Any]:
        d = dict(self._attrs)
        # parse score_json back to dict for callers
        raw = d.get("score_json")
        if raw:
            try:
                d["score"] = json.loads(raw)
            except Exception:
                d["score"] = {}
        return d

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    @classmethod
    async def create(
        cls,
        db,
        *,
        user_id: int,
        account_id: str,
        task_type: str,
        source: str,
        target: str | None = None,
        score: dict[str, Any] | None = None,
    ) -> "Assignment":
        now = utc_now_iso()
        row_id = str(uuid.uuid4())
        payload: dict[str, Any] = {
            "id": row_id,
            "user_id": str(user_id),
            "account_id": account_id,
            "task_type": task_type,
            "source": source,
            "target": target,
            "status": "active",
            "score_json": json.dumps(score) if score else None,
            "assigned_at": now,
            "removed_at": None,
        }
        await cls.query(db).insert(payload)
        return cls(**payload)

    @classmethod
    async def remove(cls, db, assignment_id: str) -> None:
        """Soft-delete: mark status='removed' and set removed_at."""
        await cls.query(db).where("id", assignment_id).update(
            {"status": "removed", "removed_at": utc_now_iso()}
        )

    @classmethod
    async def remove_by_source(
        cls, db, *, user_id: int, account_id: str, task_type: str, source: str
    ) -> None:
        """Remove all active assignments for a specific source on an account."""
        rows = (
            await cls.query(db)
            .where("user_id", str(user_id))
            .where("account_id", account_id)
            .where("task_type", task_type)
            .where("source", source)
            .where("status", "active")
            .get()
        )
        for row in rows:
            await cls.remove(db, str(row.get("id")))

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    @classmethod
    async def list_for_user(
        cls,
        db,
        user_id: int,
        *,
        task_type: str | None = None,
        status: str = "active",
        limit: int = 100,
    ) -> list["Assignment"]:
        q = (
            cls.query(db)
            .where("user_id", str(user_id))
            .where("status", status)
            .order_by("assigned_at", "DESC")
            .limit(limit)
        )
        if task_type:
            q = q.where("task_type", task_type)
        return await q.get()

    @classmethod
    async def list_for_account(
        cls,
        db,
        account_id: str,
        *,
        task_type: str | None = None,
        status: str = "active",
        limit: int = 200,
    ) -> list["Assignment"]:
        q = (
            cls.query(db)
            .where("account_id", account_id)
            .where("status", status)
            .order_by("assigned_at", "DESC")
            .limit(limit)
        )
        if task_type:
            q = q.where("task_type", task_type)
        return await q.get()

    @classmethod
    async def count_for_account(
        cls,
        db,
        account_id: str,
        *,
        task_type: str | None = None,
        status: str = "active",
    ) -> int:
        rows = await cls.list_for_account(
            db, account_id, task_type=task_type, status=status, limit=500
        )
        return len(rows)

    @classmethod
    async def find_by_source(
        cls,
        db,
        *,
        user_id: int,
        task_type: str,
        source: str,
        status: str = "active",
    ) -> "Assignment | None":
        """Return the active assignment for a source (sticky lookup)."""
        return (
            await cls.query(db)
            .where("user_id", str(user_id))
            .where("task_type", task_type)
            .where("source", source)
            .where("status", status)
            .order_by("assigned_at", "DESC")
            .first()
        )

    @classmethod
    async def load_summary(cls, db, *, user_id: int) -> dict[str, dict[str, int]]:
        """Return per-account forward/promo counts for all active assignments.

        Returns: {account_id: {"forward": N, "promo": N, "total": N}}
        """
        all_rows = await cls.list_for_user(db, user_id, status="active", limit=1000)
        summary: dict[str, dict[str, int]] = {}
        for row in all_rows:
            aid = str(row.get("account_id") or "")
            tt = str(row.get("task_type") or "")
            if aid not in summary:
                summary[aid] = {"forward": 0, "promo": 0, "total": 0}
            if tt in summary[aid]:
                summary[aid][tt] += 1
            summary[aid]["total"] += 1
        return summary
