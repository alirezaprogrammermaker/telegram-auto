"""Account management — ownership, phone uniqueness, view mapping."""
from __future__ import annotations

from typing import Any

from app.Models.Account import Account
from app.Models.LoginSession import mask_phone
from app.Services.AccountScaffoldService import (
    ROLES,
    suggest_label,
    validate_label,
    validate_role,
)
from app.Support.Time import utc_now_iso


class AccountConflictError(Exception):
    def __init__(self, code: str, *, account_id: str | None = None):
        super().__init__(code)
        self.code = code
        self.account_id = account_id


class AccountService:
    def __init__(self, db) -> None:
        self.db = db

    @staticmethod
    def _payload_from_row(row: Account, **overrides: Any) -> dict[str, Any]:
        account_id = str(overrides.get("id") or row.get("id"))
        payload: dict[str, Any] = {
            "id": account_id,
            "label": row.get("label") or account_id,
            "role": row.get("role"),
            "phone_e164": row.get("phone_e164"),
            "phone_mask": row.get("phone_mask"),
            "enabled": int(row.get("enabled") or 0),
            "session_name": row.get("session_name") or account_id,
            "session_secret": row.get("session_secret"),
            "workflow": row.get("workflow"),
            "profile_path": row.get("profile_path"),
            "github_commit_sha": row.get("github_commit_sha"),
            "telegram_user_id": row.get("telegram_user_id"),
            "telegram_username": row.get("telegram_username"),
            "status": row.get("status") or "scaffolded",
            "last_error": row.get("last_error"),
            "last_login_at": row.get("last_login_at"),
        }
        payload.update(overrides)
        return payload

    async def list_for_user(self, user_id: int) -> list[dict[str, Any]]:
        rows = await Account.for_user(self.db, user_id)
        return [row.to_view() for row in rows]

    async def vacant_roles(
        self, user_id: int, *, ignore_account_id: str | None = None
    ) -> list[str]:
        """Roles with no owned account (optionally ignoring one account)."""
        used: set[str] = set()
        for row in await self.list_for_user(user_id):
            if ignore_account_id and str(row.get("id")) == ignore_account_id:
                continue
            role = str(row.get("role") or "").strip().lower()
            if role in ROLES:
                used.add(role)
        return [r for r in ROLES if r not in used]

    async def role_index(
        self, user_id: int, role: str, account_id: str
    ) -> int:
        """1-based stable index of account among owned accounts with this role."""
        peers = [
            str(r.get("id"))
            for r in await self.list_for_user(user_id)
            if str(r.get("role") or "").lower() == role
        ]
        if account_id not in peers:
            peers.append(account_id)
        peers = sorted(set(peers))
        return peers.index(account_id) + 1

    async def get_owned(self, user_id: int, account_id: str) -> Account | None:
        return await Account.find_owned(self.db, user_id, account_id)

    async def require_owned(self, user_id: int, account_id: str) -> Account:
        row = await self.get_owned(user_id, account_id)
        if not row:
            raise AccountConflictError("account_not_owned", account_id=account_id)
        return row

    async def assert_phone_available(
        self, phone_e164: str, *, except_account_id: str | None = None
    ) -> None:
        existing = await Account.find_by_phone(self.db, phone_e164)
        if not existing:
            return
        if except_account_id and existing.account_key == except_account_id:
            return
        raise AccountConflictError(
            "phone_taken", account_id=existing.account_key
        )

    async def assert_key_available_for_user(
        self, user_id: int, account_id: str
    ) -> Account | None:
        """Return existing owned row if present; raise if owned by someone else."""
        existing = await Account.find(self.db, account_id)
        if not existing:
            return None
        if existing.owner_id in {0, int(user_id)}:
            return existing if existing.owner_id == int(user_id) else None
        raise AccountConflictError("account_owned_by_other", account_id=account_id)

    async def sync_from_login(
        self,
        *,
        user_id: int,
        account_id: str,
        label: str,
        role: str | None,
        phone_e164: str | None,
        enabled: int = 0,
        session_name: str | None = None,
        session_secret: str | None = None,
        workflow: str | None = None,
        profile_path: str | None = None,
        github_commit_sha: str | None = None,
        status: str = "logging_in",
        last_error: str | None = None,
        mark_login: bool = False,
    ) -> Account:
        payload: dict[str, Any] = {
            "id": account_id,
            "label": label,
            "role": role,
            "enabled": int(enabled),
            "session_name": session_name or account_id,
            "session_secret": session_secret,
            "workflow": workflow,
            "profile_path": profile_path,
            "github_commit_sha": github_commit_sha,
            "status": status,
            "last_error": last_error,
        }
        if phone_e164:
            payload["phone_e164"] = phone_e164
            payload["phone_mask"] = mask_phone(phone_e164)
        else:
            # Preserve existing phone fields on status-only updates.
            existing = await Account.find(self.db, account_id)
            if existing:
                if existing.get("phone_e164"):
                    payload["phone_e164"] = existing.get("phone_e164")
                if existing.get("phone_mask"):
                    payload["phone_mask"] = existing.get("phone_mask")
        if mark_login:
            payload["last_login_at"] = utc_now_iso()
            payload["status"] = "ready"
            payload["last_error"] = None
        return await Account.upsert_owned(self.db, user_id, payload)

    async def set_enabled(
        self,
        user_id: int,
        account_id: str,
        *,
        enabled: bool,
        scaffold: "AccountScaffoldService | None" = None,
    ) -> dict[str, Any]:
        """Flip enabled in GitHub registry + D1 (owned accounts only)."""
        row = await self.require_owned(user_id, account_id)
        result: dict[str, Any] = {
            "account_id": account_id,
            "enabled": bool(enabled),
            "registry_changed": False,
        }

        if scaffold is not None:
            reg = await scaffold.set_registry_enabled(account_id, enabled=enabled)
            if reg and reg.get("changed"):
                result["registry_changed"] = True
                result["commit"] = reg.get("commit")
            elif reg is None:
                result["registry_missing"] = True

        status = str(row.get("status") or "scaffolded")
        if enabled and status in {"scaffolded", "disabled"}:
            status = "ready" if row.get("last_login_at") else "scaffolded"
        if not enabled and status == "ready":
            status = "disabled"

        account = await Account.upsert_owned(
            self.db,
            user_id,
            self._payload_from_row(
                row,
                enabled=1 if enabled else 0,
                status=status,
                github_commit_sha=(
                    (result.get("commit") or {}).get("sha")
                    if isinstance(result.get("commit"), dict)
                    else row.get("github_commit_sha")
                ),
            ),
        )
        result["account"] = account
        return result

    async def set_label(
        self,
        user_id: int,
        account_id: str,
        label: str,
        *,
        scaffold: "AccountScaffoldService | None" = None,
    ) -> dict[str, Any]:
        label_ok = validate_label(label)
        if not label_ok:
            raise AccountConflictError("invalid_label", account_id=account_id)
        row = await self.require_owned(user_id, account_id)
        result: dict[str, Any] = {
            "account_id": account_id,
            "label": label_ok,
        }
        if scaffold is not None:
            gh = await scaffold.update_label(account_id, label_ok)
            result["commit"] = gh.get("commit")
        account = await Account.upsert_owned(
            self.db,
            user_id,
            self._payload_from_row(
                row,
                label=label_ok,
                github_commit_sha=(
                    (result.get("commit") or {}).get("sha")
                    if isinstance(result.get("commit"), dict)
                    else row.get("github_commit_sha")
                ),
            ),
        )
        result["account"] = account
        return result

    async def auto_label(
        self,
        user_id: int,
        account_id: str,
        *,
        scaffold: "AccountScaffoldService | None" = None,
        role: str | None = None,
    ) -> dict[str, Any]:
        row = await self.require_owned(user_id, account_id)
        role_ok = validate_role(role or str(row.get("role") or "")) or "full"
        index = await self.role_index(user_id, role_ok, account_id)
        label = suggest_label(account_id, role_ok, index=index)
        return await self.set_label(
            user_id, account_id, label, scaffold=scaffold
        )

    async def set_role(
        self,
        user_id: int,
        account_id: str,
        role: str,
        *,
        scaffold: "AccountScaffoldService | None" = None,
        auto_rename: bool = False,
    ) -> dict[str, Any]:
        role_ok = validate_role(role)
        if not role_ok:
            raise AccountConflictError("invalid_role", account_id=account_id)
        row = await self.require_owned(user_id, account_id)
        label_override = None
        if auto_rename:
            peers = [
                str(r.get("id"))
                for r in await self.list_for_user(user_id)
                if str(r.get("role") or "").lower() == role_ok
                or str(r.get("id")) == account_id
            ]
            peers = sorted(set(peers))
            index = peers.index(account_id) + 1
            label_override = suggest_label(account_id, role_ok, index=index)

        result: dict[str, Any] = {
            "account_id": account_id,
            "role": role_ok,
            "previous_role": row.get("role"),
        }
        if scaffold is not None:
            gh = await scaffold.update_role(
                account_id, role_ok, label=label_override
            )
            result["commit"] = gh.get("commit")
            if not label_override:
                label_override = str(gh.get("label") or row.get("label") or account_id)

        account = await Account.upsert_owned(
            self.db,
            user_id,
            self._payload_from_row(
                row,
                role=role_ok,
                label=label_override or row.get("label") or account_id,
                github_commit_sha=(
                    (result.get("commit") or {}).get("sha")
                    if isinstance(result.get("commit"), dict)
                    else row.get("github_commit_sha")
                ),
            ),
        )
        result["account"] = account
        result["label"] = account.get("label")
        return result

    async def logout(
        self,
        user_id: int,
        account_id: str,
        *,
        github: "GitHubService | None" = None,
        scaffold: "AccountScaffoldService | None" = None,
    ) -> dict[str, Any]:
        """Invalidate session secret, disable registry, mark logged out in D1."""
        from app.Services.AccountScaffoldService import secret_name_for

        row = await self.require_owned(user_id, account_id)
        secret_name = str(row.get("session_secret") or secret_name_for(account_id))
        result: dict[str, Any] = {
            "account_id": account_id,
            "secret_deleted": False,
            "registry_disabled": False,
        }

        if github and secret_name:
            await github.delete_secret(secret_name)
            result["secret_deleted"] = True

        if scaffold is not None:
            try:
                reg = await scaffold.set_registry_enabled(account_id, enabled=False)
                if reg and reg.get("changed"):
                    result["registry_disabled"] = True
                    result["commit"] = reg.get("commit")
            except Exception as exc:
                result["registry_error"] = str(exc)[:240]

        account = await Account.upsert_owned(
            self.db,
            user_id,
            {
                "id": account_id,
                "label": row.get("label") or account_id,
                "role": row.get("role"),
                "phone_e164": row.get("phone_e164"),
                "phone_mask": row.get("phone_mask"),
                "enabled": 0,
                "session_name": row.get("session_name") or account_id,
                "session_secret": secret_name,
                "workflow": row.get("workflow"),
                "profile_path": row.get("profile_path"),
                "github_commit_sha": row.get("github_commit_sha"),
                "telegram_user_id": None,
                "telegram_username": None,
                "status": "scaffolded",
                "last_error": None,
                "last_login_at": None,
            },
        )
        result["account"] = account
        result["logged_out"] = True
        return result

    async def delete(
        self,
        user_id: int,
        account_id: str,
        *,
        github: "GitHubService | None" = None,
        scaffold: "AccountScaffoldService | None" = None,
    ) -> dict[str, Any]:
        """Delete owned account from D1 (+ optional GitHub registry/secret cleanup)."""
        from app.Services.AccountScaffoldService import secret_name_for

        row = await self.require_owned(user_id, account_id)
        secret_name = str(row.get("session_secret") or secret_name_for(account_id))
        result: dict[str, Any] = {
            "account_id": account_id,
            "github_removed": False,
            "secret_deleted": False,
        }

        if scaffold is not None:
            try:
                gh_result = await scaffold.remove(account_id)
                result["github_removed"] = True
                result["commit"] = gh_result.get("commit")
                secret_name = str(
                    gh_result.get("session_secret") or secret_name
                )
            except Exception as exc:
                # Still delete local row; surface GitHub issue to caller.
                result["github_error"] = str(exc)[:240]

        if github is not None and secret_name:
            try:
                await github.delete_secret(secret_name)
                result["secret_deleted"] = True
            except Exception as exc:
                result["secret_error"] = str(exc)[:240]

        await Account.query(self.db).where("id", account_id).delete()
        # Cancel active login sessions for this account (owned by this user).
        from app.Models.LoginSession import LoginSession

        sessions = (
            await LoginSession.query(self.db)
            .where("account_id", account_id)
            .limit(20)
            .get()
        )
        for session in sessions:
            if int(session.get("created_by") or 0) == int(user_id):
                await session.touch(
                    self.db,
                    status="cancelled",
                    clear_secrets=True,
                    error="account_deleted",
                )
        result["deleted"] = True
        return result
