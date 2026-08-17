from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.Models.Model import Model


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Account(Model):
    table = "accounts"
    primary_key = "id"
    fillable = (
        "id",
        "label",
        "role",
        "enabled",
        "session_name",
        "session_secret",
        "phone_mask",
        "status",
        "last_error",
        "created_at",
        "updated_at",
    )

    @classmethod
    async def upsert_row(cls, db, values: dict[str, Any]) -> "Account":
        account_id = str(values["id"])
        now = utc_now()
        existing = await cls.find(db, account_id)
        payload = dict(values)
        payload["updated_at"] = now
        if existing:
            await cls.query(db).where("id", account_id).update(payload)
        else:
            payload.setdefault("created_at", now)
            await cls.query(db).insert(payload)
        return (await cls.find(db, account_id)) or cls(**payload)

    @classmethod
    async def all_ordered(cls, db, *, limit: int = 50) -> list["Account"]:
        return await cls.query(db).order_by("id", "ASC").limit(limit).get()
