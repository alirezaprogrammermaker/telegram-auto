"""Command queue model — issued by admin/agent, polled and acked by userbot."""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.Models.Model import Model
from app.Support.Time import utc_now_iso

VALID_TYPES = frozenset(
    {
        "ping",
        "config_patch",
        "module_on",
        "module_off",
        "module_reload",
        "pause_route",
        "resume_route",
        "flush_queue",
        "heartbeat_request",
    }
)

VALID_STATUSES = frozenset({"pending", "acked", "done", "failed", "expired"})


class Command(Model):
    table = "commands"
    primary_key = "id"

    # ---------- helpers ----------

    def payload_dict(self) -> dict[str, Any]:
        raw = self.get("payload")
        if not raw:
            return {}
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {}
        except (ValueError, TypeError):
            return {}

    def result_dict(self) -> dict[str, Any]:
        raw = self.get("result")
        if not raw:
            return {}
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {}
        except (ValueError, TypeError):
            return {}

    def to_view(self) -> dict[str, Any]:
        return {
            "id": self.get("id"),
            "account_id": self.get("account_id"),
            "type": self.get("type"),
            "payload": self.payload_dict(),
            "status": self.get("status"),
            "result": self.result_dict(),
            "issued_by": self.get("issued_by"),
            "created_at": self.get("created_at"),
            "acked_at": self.get("acked_at"),
            "done_at": self.get("done_at"),
            "ttl_seconds": self.get("ttl_seconds") or 300,
        }

    # ---------- class methods ----------

    @classmethod
    async def enqueue(
        cls,
        db,
        *,
        account_id: str,
        command_type: str,
        payload: dict[str, Any] | None = None,
        issued_by: str = "admin",
        ttl_seconds: int = 300,
    ) -> "Command":
        cmd_id = str(uuid.uuid4())
        now = utc_now_iso()
        row = {
            "id": cmd_id,
            "account_id": account_id,
            "type": command_type,
            "payload": json.dumps(payload or {}),
            "status": "pending",
            "result": None,
            "issued_by": issued_by,
            "created_at": now,
            "acked_at": None,
            "done_at": None,
            "ttl_seconds": ttl_seconds,
        }
        await cls.query(db).insert(row)
        return cls.from_row(row)

    @classmethod
    async def poll_pending(
        cls, db, account_id: str, *, limit: int = 10
    ) -> list["Command"]:
        """Return pending commands for an account (oldest first), expiring stale ones."""
        now = utc_now_iso()
        # Expire commands whose TTL has passed (created_at + ttl_seconds < now).
        # Simple approach: fetch all pending and filter in Python (D1 has no date arithmetic).
        all_pending = (
            await cls.query(db)
            .where("account_id", account_id)
            .where("status", "pending")
            .order_by("created_at", "ASC")
            .limit(50)
            .get()
        )
        active: list[Command] = []
        expired_ids: list[str] = []
        for cmd in all_pending:
            created = cmd.get("created_at") or ""
            ttl = int(cmd.get("ttl_seconds") or 300)
            if _is_expired(created, ttl, now):
                expired_ids.append(str(cmd.get("id")))
            else:
                active.append(cmd)
        for eid in expired_ids:
            await cls.query(db).where("id", eid).update(
                {"status": "expired", "done_at": now}
            )
        return active[:limit]

    @classmethod
    async def ack(
        cls,
        db,
        command_id: str,
        *,
        account_id: str,
        result: dict[str, Any] | None = None,
        status: str = "done",
    ) -> bool:
        """Mark a command as acked/done/failed. Returns False if not found."""
        now = utc_now_iso()
        cmd = (
            await cls.query(db)
            .where("id", command_id)
            .where("account_id", account_id)
            .first()
        )
        if cmd is None:
            return False
        update: dict[str, Any] = {"status": status, "done_at": now}
        if result is not None:
            update["result"] = json.dumps(result)
        if status == "acked" and not cmd.get("acked_at"):
            update["acked_at"] = now
            update.pop("done_at", None)
        await cls.query(db).where("id", command_id).update(update)
        return True

    @classmethod
    async def list_recent(
        cls, db, account_id: str, *, limit: int = 20
    ) -> list["Command"]:
        return (
            await cls.query(db)
            .where("account_id", account_id)
            .order_by("created_at", "DESC")
            .limit(limit)
            .get()
        )


class AccountHeartbeat(Model):
    table = "account_heartbeats"
    primary_key = "account_id"

    @classmethod
    async def upsert(
        cls,
        db,
        account_id: str,
        *,
        status: str = "running",
        modules: dict[str, str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now_iso()
        existing = await cls.find(db, account_id)
        row: dict[str, Any] = {
            "account_id": account_id,
            "status": status,
            "modules_json": json.dumps(modules or {}),
            "meta_json": json.dumps(meta or {}),
            "updated_at": now,
        }
        if existing:
            await cls.query(db).where("account_id", account_id).update(
                {k: v for k, v in row.items() if k != "account_id"}
            )
        else:
            await cls.query(db).insert(row)

    def to_view(self) -> dict[str, Any]:
        modules_raw = self.get("modules_json") or "{}"
        meta_raw = self.get("meta_json") or "{}"
        try:
            modules = json.loads(modules_raw)
        except (ValueError, TypeError):
            modules = {}
        try:
            meta = json.loads(meta_raw)
        except (ValueError, TypeError):
            meta = {}
        return {
            "account_id": self.get("account_id"),
            "status": self.get("status"),
            "modules": modules,
            "meta": meta,
            "updated_at": self.get("updated_at"),
        }


def _is_expired(created_at_iso: str, ttl_seconds: int, now_iso: str) -> bool:
    """Best-effort ISO-8601 expiry check (no external deps)."""
    try:
        from datetime import datetime, timezone

        fmt = "%Y-%m-%dT%H:%M:%S"
        created = datetime.strptime(created_at_iso[:19], fmt).replace(
            tzinfo=timezone.utc
        )
        now = datetime.strptime(now_iso[:19], fmt).replace(tzinfo=timezone.utc)
        return (now - created).total_seconds() > ttl_seconds
    except Exception:
        return False
