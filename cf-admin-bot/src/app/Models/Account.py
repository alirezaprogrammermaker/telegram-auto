from __future__ import annotations

from typing import Any

from app.Models.Model import Model
from app.Support.Time import utc_now_iso


class Account(Model):
    """Owned Telegram automation identity (D1 source of truth for the admin bot)."""

    table = "accounts"
    primary_key = "id"
    fillable = (
        "id",
        "user_id",
        "label",
        "role",
        "phone_e164",
        "phone_mask",
        "enabled",
        "session_name",
        "session_secret",
        "workflow",
        "profile_path",
        "github_commit_sha",
        "telegram_user_id",
        "telegram_username",
        "status",
        "last_error",
        "last_login_at",
        "created_at",
        "updated_at",
    )

    @property
    def account_key(self) -> str:
        return str(self.get("id") or "")

    @property
    def owner_id(self) -> int:
        return int(self.get("user_id") or 0)

    def belongs_to(self, user_id: int) -> bool:
        return self.owner_id == int(user_id)

    def to_view(self) -> dict[str, Any]:
        return {
            "id": self.account_key,
            "user_id": self.owner_id,
            "label": self.get("label") or self.account_key,
            "role": self.get("role") or "-",
            "enabled": bool(int(self.get("enabled") or 0)),
            "session_secret": self.get("session_secret") or "-",
            "status": self.get("status") or "scaffolded",
            "phone_mask": self.get("phone_mask") or "-",
            "workflow": self.get("workflow") or "-",
            "last_login_at": self.get("last_login_at") or "-",
        }

    @classmethod
    async def for_user(
        cls, db, user_id: int, *, limit: int = 50
    ) -> list["Account"]:
        return (
            await cls.query(db)
            .where("user_id", int(user_id))
            .order_by("id", "ASC")
            .limit(limit)
            .get()
        )

    @classmethod
    async def find_owned(
        cls, db, user_id: int, account_id: str
    ) -> "Account | None":
        row = await cls.find(db, account_id)
        if not row or not row.belongs_to(user_id):
            return None
        return row

    @classmethod
    async def find_by_phone(cls, db, phone_e164: str) -> "Account | None":
        return await cls.query(db).where("phone_e164", phone_e164).first()

    @classmethod
    async def upsert_owned(cls, db, user_id: int, values: dict[str, Any]) -> "Account":
        account_id = str(values["id"])
        now = utc_now_iso()
        payload = {k: v for k, v in values.items() if k in cls.fillable or k == "id"}
        payload["id"] = account_id
        payload["user_id"] = int(user_id)
        payload["updated_at"] = now

        existing = await cls.find(db, account_id)
        if existing:
            if not existing.belongs_to(user_id) and existing.owner_id != 0:
                raise PermissionError("account_owned_by_other")
            # Claim orphan (user_id=0) or update own row.
            await cls.query(db).where("id", account_id).update(payload)
        else:
            payload.setdefault("created_at", now)
            await cls.query(db).insert(payload)
        return (await cls.find(db, account_id)) or cls(**payload)
