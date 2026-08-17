from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from app.Models.Model import Model

SESSION_TTL_MINUTES = 30


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def mask_phone(phone: str | None) -> str:
    if not phone:
        return ""
    digits = phone.strip()
    if len(digits) <= 4:
        return "***"
    return digits[:3] + "***" + digits[-2:]


class LoginSession(Model):
    table = "login_sessions"
    primary_key = "id"
    fillable = (
        "id",
        "account_id",
        "role",
        "phone",
        "otp",
        "twofa",
        "status",
        "created_by",
        "github_run_id",
        "error",
        "created_at",
        "updated_at",
        "expires_at",
    )

    @property
    def phone_mask(self) -> str:
        return mask_phone(str(self.get("phone") or ""))

    @property
    def is_expired(self) -> bool:
        raw = str(self.get("expires_at") or "")
        if not raw:
            return True
        try:
            expires = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return True
        return utc_now() >= expires.astimezone(timezone.utc).replace(tzinfo=timezone.utc)

    @classmethod
    async def create_new(
        cls,
        db,
        *,
        account_id: str,
        role: str | None,
        created_by: int,
        phone: str | None = None,
        status: str = "drafting",
    ) -> "LoginSession":
        now = utc_now()
        sid = secrets.token_hex(12)
        row = {
            "id": sid,
            "account_id": account_id,
            "role": role,
            "phone": phone,
            "status": status,
            "created_by": created_by,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=SESSION_TTL_MINUTES)).isoformat(),
        }
        # Omit nullables so D1 insert stays clean.
        await cls.query(db).insert({k: v for k, v in row.items() if v is not None})
        return (await cls.find(db, sid)) or cls(**row)

    async def touch(
        self,
        db,
        *,
        status: str | None = None,
        phone: str | None = None,
        otp: str | None = None,
        twofa: str | None = None,
        github_run_id: str | None = None,
        error: str | None = None,
        clear_secrets: bool = False,
        extend_ttl: bool = False,
    ) -> "LoginSession":
        sid = str(self.get("id"))
        patch: dict[str, Any] = {"updated_at": utc_now_iso()}
        if status is not None:
            patch["status"] = status
        if phone is not None:
            patch["phone"] = phone
        if otp is not None:
            patch["otp"] = otp
        if twofa is not None:
            patch["twofa"] = twofa
        if github_run_id is not None:
            patch["github_run_id"] = github_run_id
        if error is not None:
            patch["error"] = error
        if clear_secrets:
            patch["phone"] = None
            patch["otp"] = None
            patch["twofa"] = None
        if extend_ttl:
            patch["expires_at"] = (
                utc_now() + timedelta(minutes=SESSION_TTL_MINUTES)
            ).isoformat()
        await self.query(db).where("id", sid).update(patch)
        return (await self.find(db, sid)) or self

    @classmethod
    async def latest_active_for_account(
        cls, db, account_id: str
    ) -> "LoginSession | None":
        rows = (
            await cls.query(db)
            .where("account_id", account_id)
            .order_by("updated_at", "DESC")
            .limit(5)
            .get()
        )
        active = {
            "drafting",
            "scaffolding",
            "sending",
            "awaiting_otp",
            "awaiting_2fa",
            "completing",
        }
        for row in rows:
            if str(row.get("status") or "") in active and not row.is_expired:
                return row
        return None

    @classmethod
    async def for_bridge(
        cls, db, account_id: str, *, action: str
    ) -> "LoginSession | None":
        """Newest non-expired session that can serve bridge credentials."""
        rows = (
            await cls.query(db)
            .where("account_id", account_id)
            .order_by("updated_at", "DESC")
            .limit(10)
            .get()
        )
        wanted = {
            "send": {"sending", "awaiting_otp", "scaffolding"},
            "complete": {"awaiting_otp", "awaiting_2fa", "completing"},
        }.get(action, set())
        for row in rows:
            if row.is_expired:
                continue
            if str(row.get("status") or "") in wanted:
                return row
            # Also allow any recent session that still has the needed fields.
            if action == "send" and row.get("phone"):
                return row
            if action == "complete" and row.get("otp"):
                return row
        return None
