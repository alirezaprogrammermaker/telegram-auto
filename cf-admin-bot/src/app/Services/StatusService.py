"""Read-only control-plane snapshots (D1 + latest GHA runs + heartbeat metrics)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.Models.Command import AccountHeartbeat
from app.Services.AccountService import AccountService
from app.Services.GitHubService import GitHubService

DISCOVERY_ROLES = frozenset({"collector", "inspector", "linkdir", "full"})
PROMO_ROLES = frozenset({"promo", "full"})
FORWARD_ROLES = frozenset({"forward", "full"})
LINKDIR_ROLES = frozenset({"linkdir"})


class StatusService:
    def __init__(self, db, github: GitHubService | None = None) -> None:
        self.db = db
        self.github = github
        self.accounts = AccountService(db)

    @staticmethod
    def _heartbeat_is_stale(updated_at: Any, *, max_age_minutes: int = 5) -> bool:
        text = str(updated_at or "").strip()
        if not text:
            return True
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return True
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_minutes = (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
        return age_minutes > float(max_age_minutes)

    async def _latest_run(self, workflow: str | None) -> dict[str, Any] | None:
        if not self.github or not workflow or workflow == "-":
            return None
        try:
            # Include schedule + dispatch so status matches reality.
            return await self.github.latest_workflow_run(str(workflow), event=None)
        except Exception:
            return None

    async def _heartbeats_by_account(self) -> dict[str, dict[str, Any]]:
        rows = await AccountHeartbeat.query(self.db).get()
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            view = row.to_view()
            aid = str(view.get("account_id") or "")
            if aid:
                out[aid] = view
        return out

    @staticmethod
    def _live_from_heartbeat(hb: dict[str, Any] | None) -> dict[str, Any]:
        if not hb:
            return {
                "heartbeat_status": None,
                "heartbeat_at": None,
                "heartbeat_stale": True,
                "modules": {},
                "stats_today": None,
                "forward_queue_pending": None,
                "promo_queue_pending": None,
                "promo_circuit": None,
            }
        meta = hb.get("meta") if isinstance(hb.get("meta"), dict) else {}
        metrics = meta.get("metrics") if isinstance(meta.get("metrics"), dict) else {}
        stats = metrics.get("stats_today")
        if not isinstance(stats, dict):
            stats = None
        updated_at = hb.get("updated_at")
        return {
            "heartbeat_status": hb.get("status"),
            "heartbeat_at": updated_at,
            "heartbeat_stale": StatusService._heartbeat_is_stale(updated_at),
            "modules": hb.get("modules") if isinstance(hb.get("modules"), dict) else {},
            "stats_today": stats,
            "forward_queue_pending": metrics.get("forward_queue_pending"),
            "promo_queue_pending": metrics.get("promo_queue_pending"),
            "promo_circuit": (
                metrics.get("promo_circuit")
                if isinstance(metrics.get("promo_circuit"), dict)
                else None
            ),
        }

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

        heartbeats = await self._heartbeats_by_account()
        lines: list[dict[str, Any]] = []
        for row in rows[:20]:
            aid = str(row.get("id") or "")
            run = await self._latest_run(row.get("workflow"))
            live = self._live_from_heartbeat(heartbeats.get(aid))
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
                    **live,
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

    async def forward_snapshot(self, user_id: int) -> dict[str, Any]:
        return await self.snapshot(user_id, roles=FORWARD_ROLES)

    async def linkdir_snapshot(self, user_id: int) -> dict[str, Any]:
        return await self.snapshot(user_id, roles=LINKDIR_ROLES)
