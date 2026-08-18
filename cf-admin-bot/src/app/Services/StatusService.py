"""Read-only control-plane snapshots (D1 + latest GHA runs)."""
from __future__ import annotations

from typing import Any

from app.Services.AccountService import AccountService
from app.Services.GitHubService import GitHubService

DISCOVERY_ROLES = frozenset({"collector", "inspector"})
PROMO_ROLES = frozenset({"promo"})


class StatusService:
    def __init__(self, db, github: GitHubService | None = None) -> None:
        self.db = db
        self.github = github
        self.accounts = AccountService(db)

    async def _latest_run(self, workflow: str | None) -> dict[str, Any] | None:
        if not self.github or not workflow or workflow == "-":
            return None
        try:
            # Include schedule + dispatch so status matches reality.
            return await self.github.latest_workflow_run(str(workflow), event=None)
        except Exception:
            return None

    async def snapshot(
        self, user_id: int, *, roles: frozenset[str] | None = None
    ) -> dict[str, Any]:
        rows = await self.accounts.list_for_user(user_id)
        if roles is not None:
            rows = [
                r
                for r in rows
                if str(r.get("role") or "").lower() in roles
            ]

        lines: list[dict[str, Any]] = []
        for row in rows[:20]:
            run = await self._latest_run(row.get("workflow"))
            lines.append(
                {
                    "id": row.get("id"),
                    "label": row.get("label") or row.get("id"),
                    "role": row.get("role") or "-",
                    "enabled": bool(row.get("enabled")),
                    "status": row.get("status") or "-",
                    "phone_mask": row.get("phone_mask") or "-",
                    "workflow": row.get("workflow") or "-",
                    "run_id": (run or {}).get("id"),
                    "run_status": (run or {}).get("status") or "-",
                    "run_conclusion": (run or {}).get("conclusion") or "-",
                    "run_url": (run or {}).get("html_url") or "",
                }
            )
        return {
            "count": len(lines),
            "github_ready": self.github is not None,
            "accounts": lines,
        }

    async def discovery_snapshot(self, user_id: int) -> dict[str, Any]:
        return await self.snapshot(user_id, roles=DISCOVERY_ROLES)

    async def promo_snapshot(self, user_id: int) -> dict[str, Any]:
        return await self.snapshot(user_id, roles=PROMO_ROLES)
