"""Post-login provisioning: enable registry/account and start runner."""
from __future__ import annotations

from typing import Any

from app.Services.AccountScaffoldService import AccountScaffoldService
from app.Services.AccountService import AccountService
from app.Services.RunOrchestratorService import RunOrchestratorService


class ProvisioningService:
    def __init__(
        self,
        db,
        *,
        accounts: AccountService,
        scaffold: AccountScaffoldService,
        runner: RunOrchestratorService | None = None,
    ) -> None:
        self.db = db
        self.accounts = accounts
        self.scaffold = scaffold
        self.runner = runner

    async def provision_after_login(
        self, *, user_id: int, account_id: str
    ) -> dict[str, Any]:
        row = await self.accounts.require_owned(user_id, account_id)
        role = str(row.get("role") or "").lower()
        enabled = await self.accounts.set_enabled(
            user_id, account_id, enabled=True, scaffold=self.scaffold
        )
        dispatch_info = None
        if self.runner is not None and str(row.get("workflow") or "").strip():
            dispatch_info = await self.runner.dispatch(user_id, account_id)
        return {
            "account_id": account_id,
            "role": role,
            "enabled": True,
            "registry_changed": enabled.get("registry_changed", False),
            "dispatch_info": dispatch_info,
        }
