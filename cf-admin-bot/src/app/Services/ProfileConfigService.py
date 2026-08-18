"""Safe profile module toggles for owned accounts (GitHub profile JSON)."""
from __future__ import annotations

from typing import Any

from app.Services.AccountScaffoldService import AccountScaffoldService, validate_account_id
from app.Services.AccountService import AccountConflictError, AccountService
from app.Services.GitHubService import GitHubError

# module -> allowed patch keys and value kinds
ALLOWED: dict[str, dict[str, str]] = {
    "group_inspect": {
        "dry_run": "bool",
        "paused": "bool",
        "daily_join_budget": "budget",
    },
    "link_harvest": {
        "paused": "bool",
        "catch_up_limit": "catchup",
        "directories": "dirs",
    },
    "promo_spread": {
        "dry_run": "bool",
        "paused": "bool",
        "mode": "mode",
    },
}

ROLE_MODULE = {
    "inspector": "group_inspect",
    "collector": "link_harvest",
    "promo": "promo_spread",
}


class ProfileConfigService:
    def __init__(self, db, scaffold: AccountScaffoldService) -> None:
        self.db = db
        self.scaffold = scaffold
        self.accounts = AccountService(db)

    async def _owned_module(
        self, user_id: int, account_id: str, module: str
    ) -> None:
        row = await self.accounts.require_owned(user_id, account_id)
        expected = ROLE_MODULE.get(str(row.get("role") or "").lower())
        # Allow full role to patch any allowed module; otherwise enforce match.
        role = str(row.get("role") or "").lower()
        if role != "full" and expected and expected != module:
            raise AccountConflictError("wrong_role_for_module", account_id=account_id)

    def _validate_patch(self, module: str, patch: dict[str, Any]) -> dict[str, Any]:
        allowed = ALLOWED.get(module)
        if not allowed:
            raise GitHubError(f"module not allowed: {module}")
        out: dict[str, Any] = {}
        for key, value in patch.items():
            kind = allowed.get(key)
            if not kind:
                raise GitHubError(f"key not allowed: {module}.{key}")
            if kind == "bool":
                out[key] = bool(value)
            elif kind == "budget":
                out[key] = max(1, min(12, int(value)))
            elif kind == "catchup":
                out[key] = max(0, min(200, int(value)))
            elif kind == "mode":
                mode = str(value).strip().lower()
                if mode not in {"forward", "copy"}:
                    raise GitHubError("mode must be forward|copy")
                out[key] = mode
            elif kind == "dirs":
                if not isinstance(value, list):
                    raise GitHubError("directories must be a list")
                dirs = [str(x).strip() for x in value if str(x).strip()]
                if len(dirs) > 5:
                    raise GitHubError("max 5 directories")
                out[key] = dirs
            else:
                raise GitHubError(f"unknown kind {kind}")
        if not out:
            raise GitHubError("empty patch")
        return out

    async def patch(
        self,
        user_id: int,
        account_id: str,
        module: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        aid = validate_account_id(account_id)
        if not aid:
            raise AccountConflictError("invalid_id", account_id=account_id)
        await self._owned_module(user_id, aid, module)
        clean = self._validate_patch(module, patch)
        return await self.scaffold.patch_profile_modules(aid, module, clean)

    async def toggle_bool(
        self,
        user_id: int,
        account_id: str,
        module: str,
        key: str,
        *,
        value: bool | None = None,
    ) -> dict[str, Any]:
        info = await self.scaffold.get_profile(account_id)
        modules = (info.get("profile") or {}).get("modules") or {}
        current = modules.get(module) if isinstance(modules, dict) else {}
        cur_val = bool((current or {}).get(key)) if isinstance(current, dict) else False
        new_val = (not cur_val) if value is None else bool(value)
        return await self.patch(user_id, account_id, module, {key: new_val})

    async def set_budget(
        self, user_id: int, account_id: str, budget: int
    ) -> dict[str, Any]:
        return await self.patch(
            user_id, account_id, "group_inspect", {"daily_join_budget": budget}
        )

    async def add_directory(
        self, user_id: int, account_id: str, ref: str
    ) -> dict[str, Any]:
        shown = (ref or "").strip()
        if not shown:
            raise GitHubError("empty directory")
        info = await self.scaffold.get_profile(account_id)
        modules = (info.get("profile") or {}).get("modules") or {}
        current = modules.get("link_harvest") if isinstance(modules, dict) else {}
        dirs = list((current or {}).get("directories") or []) if isinstance(current, dict) else []
        dirs = [str(x) for x in dirs if str(x).strip()]
        if shown in dirs:
            raise GitHubError("directory_exists")
        if len(dirs) >= 5:
            raise GitHubError("directories_full")
        dirs.append(shown)
        return await self.patch(
            user_id, account_id, "link_harvest", {"directories": dirs}
        )
