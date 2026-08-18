"""Dispatch / cancel / restart owned account runners on GitHub Actions."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from app.Services.AccountService import AccountConflictError, AccountService
from app.Services.GitHubService import GitHubError, GitHubService

MERGE_POOL_WORKFLOW = "merge-group-pool.yml"
POOL_ADMIN_WORKFLOW = "pool-admin.yml"
ACCOUNT_CACHE_ADMIN_WORKFLOW = "account-cache-admin.yml"


class RunOrchestratorService:
    def __init__(self, db, github: GitHubService) -> None:
        self.db = db
        self.github = github
        self.accounts = AccountService(db)

    def _workflow_for(self, row) -> str:
        wf = str(row.get("workflow") or "").strip()
        if not wf:
            raise GitHubError("account has no workflow")
        return wf

    @staticmethod
    def _run_view(run: dict[str, Any] | None) -> dict[str, Any]:
        if not run:
            return {
                "run_id": None,
                "status": None,
                "conclusion": None,
                "html_url": None,
            }
        return {
            "run_id": run.get("id"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "html_url": run.get("html_url"),
        }

    async def dispatch(
        self,
        user_id: int,
        account_id: str,
        *,
        max_runtime_seconds: str | None = None,
    ) -> dict[str, Any]:
        row = await self.accounts.require_owned(user_id, account_id)
        workflow = self._workflow_for(row)
        if not int(row.get("enabled") or 0):
            raise AccountConflictError("account_disabled", account_id=account_id)

        inputs: dict[str, str] = {}
        if max_runtime_seconds:
            inputs["max_runtime_seconds"] = str(max_runtime_seconds)

        started = time.time()
        await self.github.dispatch_workflow(workflow, inputs)
        run = await self.github.wait_for_workflow_run(
            workflow, not_before_epoch=started
        )
        return {
            "account_id": account_id,
            "workflow": workflow,
            "action": "dispatch",
            **self._run_view(run),
        }

    async def cancel(self, user_id: int, account_id: str) -> dict[str, Any]:
        row = await self.accounts.require_owned(user_id, account_id)
        workflow = self._workflow_for(row)
        active = await self.github.find_active_run(workflow)
        if not active:
            return {
                "account_id": account_id,
                "workflow": workflow,
                "action": "cancel",
                "cancelled": False,
                **self._run_view(None),
            }
        run_id = active.get("id")
        await self.github.cancel_run(run_id)
        return {
            "account_id": account_id,
            "workflow": workflow,
            "action": "cancel",
            "cancelled": True,
            **self._run_view(active),
        }

    async def restart(
        self,
        user_id: int,
        account_id: str,
        *,
        max_runtime_seconds: str | None = None,
    ) -> dict[str, Any]:
        cancel_info = await self.cancel(user_id, account_id)
        if cancel_info.get("cancelled"):
            await asyncio.sleep(3)
        dispatch_info = await self.dispatch(
            user_id, account_id, max_runtime_seconds=max_runtime_seconds
        )
        return {
            "account_id": account_id,
            "workflow": dispatch_info.get("workflow"),
            "action": "restart",
            "previous_cancelled": bool(cancel_info.get("cancelled")),
            "previous_run_id": cancel_info.get("run_id"),
            **{
                k: dispatch_info.get(k)
                for k in ("run_id", "status", "conclusion", "html_url")
            },
        }

    async def merge_pool(self) -> dict[str, Any]:
        started = time.time()
        await self.github.dispatch_workflow(MERGE_POOL_WORKFLOW, {})
        run = await self.github.wait_for_workflow_run(
            MERGE_POOL_WORKFLOW, not_before_epoch=started
        )
        return {
            "action": "merge_pool",
            "workflow": MERGE_POOL_WORKFLOW,
            **self._run_view(run),
        }

    async def pool_admin(
        self,
        *,
        action: str,
        notify_user_id: int,
        notify_chat_id: int | None = None,
        status_filter: str = "",
        ref: str = "",
        limit: int = 20,
        intent: str = "",
        promo_account_id: str = "",
        source_channel: str = "",
    ) -> dict[str, Any]:
        action = (action or "").strip().lower()
        if action not in {"status", "list", "approve", "reject", "get"}:
            raise GitHubError(f"bad pool action: {action}")
        inputs: dict[str, str] = {
            "action": action,
            "notify_user_id": str(int(notify_user_id)),
            "notify_chat_id": str(int(notify_chat_id or notify_user_id)),
            "limit": str(max(1, min(int(limit), 50))),
        }
        if status_filter:
            inputs["status_filter"] = status_filter
        if ref:
            inputs["ref"] = ref
        if intent:
            inputs["intent"] = intent
        if promo_account_id:
            inputs["promo_account_id"] = promo_account_id
        if source_channel:
            inputs["source_channel"] = source_channel
        started = time.time()
        await self.github.dispatch_workflow(POOL_ADMIN_WORKFLOW, inputs)
        run = await self.github.wait_for_workflow_run(
            POOL_ADMIN_WORKFLOW, not_before_epoch=started
        )
        return {
            "action": action,
            "workflow": POOL_ADMIN_WORKFLOW,
            **self._run_view(run),
        }

    async def account_cache_admin(
        self,
        user_id: int,
        account_id: str,
        *,
        action: str,
        notify_chat_id: int | None = None,
    ) -> dict[str, Any]:
        await self.accounts.require_owned(user_id, account_id)
        action = (action or "").strip()
        allowed = {
            "promo_queue_status",
            "promo_queue_clear",
            "forward_queue_status",
            "forward_queue_clear",
            "promo_safety_dump",
            "inspect_state_dump",
            "stats_dump",
        }
        if action not in allowed:
            raise GitHubError(f"bad cache action: {action}")
        inputs = {
            "account_id": account_id,
            "action": action,
            "notify_user_id": str(int(user_id)),
            "notify_chat_id": str(int(notify_chat_id or user_id)),
        }
        started = time.time()
        await self.github.dispatch_workflow(ACCOUNT_CACHE_ADMIN_WORKFLOW, inputs)
        run = await self.github.wait_for_workflow_run(
            ACCOUNT_CACHE_ADMIN_WORKFLOW, not_before_epoch=started
        )
        return {
            "action": action,
            "account_id": account_id,
            "workflow": ACCOUNT_CACHE_ADMIN_WORKFLOW,
            **self._run_view(run),
        }
