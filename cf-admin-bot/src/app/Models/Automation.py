from __future__ import annotations

import json
import uuid
from typing import Any

from app.Models.Model import Model, row_to_dict
from app.Support.Time import utc_now_iso


class AutomationPolicy(Model):
    table = "automation_policies"
    primary_key = "id"

    @classmethod
    async def upsert_scope(
        cls,
        db,
        *,
        scope_type: str,
        scope_id: str,
        values: dict[str, Any],
    ) -> "AutomationPolicy":
        now = utc_now_iso()
        existing = (
            await cls.query(db)
            .where("scope_type", scope_type)
            .where("scope_id", scope_id)
            .first()
        )
        payload = {
            "enabled": int(bool(values.get("enabled", 1))),
            "warn_after_minutes": int(values.get("warn_after_minutes", 10)),
            "ping_after_minutes": int(values.get("ping_after_minutes", 15)),
            "restart_after_minutes": int(values.get("restart_after_minutes", 30)),
            "restart_cooldown_minutes": int(values.get("restart_cooldown_minutes", 180)),
            "max_restarts_per_day": int(values.get("max_restarts_per_day", 2)),
            "notify_on_warn": int(bool(values.get("notify_on_warn", 1))),
            "notify_on_action": int(bool(values.get("notify_on_action", 1))),
            "allowed_roles_csv": values.get("allowed_roles_csv"),
            "updated_at": now,
        }
        if existing:
            await cls.query(db).where("id", str(existing.get("id"))).update(payload)
            return await cls.find(db, str(existing.get("id"))) or existing
        row_id = str(uuid.uuid4())
        row = {
            "id": row_id,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "created_at": now,
            **payload,
        }
        await cls.query(db).insert(row)
        return cls(**row)

    @classmethod
    async def resolve_for_account(
        cls, db, *, user_id: int, account_id: str
    ) -> "AutomationPolicy | None":
        for scope_type, scope_id in (
            ("account", account_id),
            ("user", str(user_id)),
            ("global", "default"),
        ):
            row = (
                await cls.query(db)
                .where("scope_type", scope_type)
                .where("scope_id", scope_id)
                .first()
            )
            if row:
                return row
        return None

    def to_view(self) -> dict[str, Any]:
        return {
            "id": self.get("id"),
            "scope_type": self.get("scope_type"),
            "scope_id": self.get("scope_id"),
            "enabled": bool(int(self.get("enabled") or 0)),
            "warn_after_minutes": int(self.get("warn_after_minutes") or 10),
            "ping_after_minutes": int(self.get("ping_after_minutes") or 15),
            "restart_after_minutes": int(self.get("restart_after_minutes") or 30),
            "restart_cooldown_minutes": int(self.get("restart_cooldown_minutes") or 180),
            "max_restarts_per_day": int(self.get("max_restarts_per_day") or 2),
            "notify_on_warn": bool(int(self.get("notify_on_warn") or 0)),
            "notify_on_action": bool(int(self.get("notify_on_action") or 0)),
            "allowed_roles_csv": self.get("allowed_roles_csv") or "",
            "updated_at": self.get("updated_at"),
        }


class AutomationRun(Model):
    table = "automation_runs"
    primary_key = "id"

    @classmethod
    async def create(
        cls,
        db,
        *,
        user_id: int,
        account_id: str,
        action: str,
        action_key: str,
        policy_id: str | None = None,
        status: str = "done",
        reason: str = "",
        details: dict[str, Any] | None = None,
    ) -> "AutomationRun":
        now = utc_now_iso()
        row = {
            "id": str(uuid.uuid4()),
            "policy_id": policy_id,
            "user_id": str(user_id),
            "account_id": account_id,
            "action": action,
            "status": status,
            "reason": reason,
            "action_key": action_key,
            "details_json": json.dumps(details or {}),
            "created_at": now,
            "updated_at": now,
        }
        await cls.query(db).insert(row)
        return cls(**row)

    @classmethod
    async def recent_for_account_action(
        cls, db, *, account_id: str, action: str, limit: int = 20
    ) -> list["AutomationRun"]:
        return (
            await cls.query(db)
            .where("account_id", account_id)
            .where("action", action)
            .order_by("created_at", "DESC")
            .limit(limit)
            .get()
        )

    @classmethod
    async def list_recent_for_user(
        cls, db, *, user_id: int, limit: int = 20
    ) -> list["AutomationRun"]:
        return (
            await cls.query(db)
            .where("user_id", str(user_id))
            .order_by("created_at", "DESC")
            .limit(limit)
            .get()
        )

    @classmethod
    async def count_since(
        cls,
        db,
        *,
        account_id: str,
        action: str,
        since_iso: str,
    ) -> int:
        result = await db.prepare(
            """
            SELECT COUNT(*) AS c
            FROM automation_runs
            WHERE account_id = ? AND action = ? AND created_at >= ?
            """
        ).bind(account_id, action, since_iso).first()
        row = row_to_dict(result)
        return int((row or {}).get("c") or 0)

    def details(self) -> dict[str, Any]:
        raw = self.get("details_json") or "{}"
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def to_view(self) -> dict[str, Any]:
        return {
            "id": self.get("id"),
            "policy_id": self.get("policy_id"),
            "user_id": self.get("user_id"),
            "account_id": self.get("account_id"),
            "action": self.get("action"),
            "status": self.get("status"),
            "reason": self.get("reason"),
            "action_key": self.get("action_key"),
            "details": self.details(),
            "created_at": self.get("created_at"),
            "updated_at": self.get("updated_at"),
        }
