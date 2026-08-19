"""Conservative assignment failover for unhealthy accounts."""
from __future__ import annotations

from typing import Any

from app.Services.AssignmentService import AssignmentService


class AssignmentRebalanceService:
    def __init__(self, assignments: AssignmentService) -> None:
        self.assignments = assignments

    async def rebalance_failed_account(
        self, *, user_id: int, failed_account_id: str
    ) -> dict[str, Any]:
        result = await self.assignments.reassign_account(
            user_id, failed_account_id, auto_dispatch=True
        )
        return {
            "failed_account_id": failed_account_id,
            "moved": result.get("moved", []),
            "count": int(result.get("count", 0)),
        }
