from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.Models.Model import Model

STATE_IDLE = "idle"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class UserState(Model):
    table = "user_states"
    primary_key = "telegram_id"
    fillable = ("telegram_id", "state", "context_json", "updated_at")

    @property
    def is_active(self) -> bool:
        return str(self.get("state") or STATE_IDLE) != STATE_IDLE

    @property
    def context(self) -> dict[str, Any]:
        raw = self.get("context_json")
        if not raw:
            return {}
        if isinstance(raw, dict):
            return dict(raw)
        try:
            data = json.loads(str(raw))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    @classmethod
    async def get_or_idle(cls, db, telegram_id: int) -> "UserState":
        row = await cls.find(db, telegram_id)
        if row:
            return row
        return cls(
            telegram_id=telegram_id,
            state=STATE_IDLE,
            context_json="{}",
            updated_at=utc_now(),
        )

    @classmethod
    async def set_state(
        cls,
        db,
        telegram_id: int,
        state: str,
        context: dict[str, Any] | None = None,
    ) -> "UserState":
        payload = {
            "state": state,
            "context_json": json.dumps(context or {}, ensure_ascii=False),
            "updated_at": utc_now(),
        }
        existing = await cls.find(db, telegram_id)
        if existing:
            await cls.query(db).where("telegram_id", telegram_id).update(payload)
        else:
            await cls.query(db).insert(
                {
                    "telegram_id": telegram_id,
                    **payload,
                }
            )
        return (await cls.find(db, telegram_id)) or cls(
            telegram_id=telegram_id, **payload
        )

    @classmethod
    async def clear(cls, db, telegram_id: int) -> "UserState":
        return await cls.set_state(db, telegram_id, STATE_IDLE, {})

    @classmethod
    async def merge_context(
        cls, db, telegram_id: int, patch: dict[str, Any], *, state: str | None = None
    ) -> "UserState":
        current = await cls.get_or_idle(db, telegram_id)
        ctx = current.context
        ctx.update(patch)
        return await cls.set_state(
            db,
            telegram_id,
            state if state is not None else str(current.get("state") or STATE_IDLE),
            ctx,
        )
