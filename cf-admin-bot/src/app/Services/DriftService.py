"""Detect drift between D1 assignments and Git profile routes."""
from __future__ import annotations

import json
from typing import Any

from app.Models.Assignment import Assignment
from app.Services.ProfileConfigService import ProfileConfigService
from app.Support.PromoRoutes import migrate_routes as migrate_promo_routes


class DriftService:
    def __init__(self, db, profile: ProfileConfigService) -> None:
        self.db = db
        self.profile = profile

    async def scan_user(self, user_id: int) -> dict[str, Any]:
        rows = await Assignment.list_for_user(
            self.db, user_id, status="active", limit=1000
        )
        by_account: dict[str, list[Assignment]] = {}
        for row in rows:
            aid = str(row.get("account_id") or "")
            by_account.setdefault(aid, []).append(row)

        accounts: list[dict[str, Any]] = []
        totals = {"assignment_only": 0, "profile_only": 0}
        for account_id, assignments in by_account.items():
            item = await self.scan_account(user_id, account_id, assignments=assignments)
            totals["assignment_only"] += len(item["assignment_only"])
            totals["profile_only"] += len(item["profile_only"])
            accounts.append(item)
        return {
            "accounts": accounts,
            "assignment_only": totals["assignment_only"],
            "profile_only": totals["profile_only"],
        }

    async def scan_account(
        self,
        user_id: int,
        account_id: str,
        *,
        assignments: list[Assignment] | None = None,
    ) -> dict[str, Any]:
        if assignments is None:
            assignments = await Assignment.list_for_account(
                self.db, account_id, status="active", limit=1000
            )
        profile = await self.profile.module_config(user_id, account_id, "channel_forward")
        routes = await self.profile._forward_routes(user_id, account_id)
        promo = await self.profile.module_config(user_id, account_id, "promo_spread")

        assignment_keys: set[str] = set()
        profile_keys: set[str] = set()
        for row in assignments:
            task_type = str(row.get("task_type") or "")
            source = str(row.get("source") or "")
            target = str(row.get("target") or "")
            if task_type == "forward":
                assignment_keys.add(f"forward:{source}:{target}")
            elif task_type == "promo":
                try:
                    groups = json.loads(target)
                except Exception:
                    groups = []
                if isinstance(groups, list):
                    for group in groups:
                        profile_key = f"promo:{source}:{str(group)}"
                        assignment_keys.add(profile_key)

        for route in routes:
            profile_keys.add(
                f"forward:{route.get('source')}:{route.get('destination')}"
            )

        promo_routes_raw = migrate_promo_routes(promo)
        for route in promo_routes_raw:
            source = str(route.get("source") or "")
            for group in route.get("groups") or []:
                profile_keys.add(f"promo:{source}:{str(group)}")

        return {
            "account_id": account_id,
            "forward_route_count": len(routes),
            "promo_route_count": len(promo_routes_raw),
            "assignment_only": sorted(assignment_keys - profile_keys),
            "profile_only": sorted(profile_keys - assignment_keys),
            "profile_enabled": bool(profile.get("enabled", True)),
        }
