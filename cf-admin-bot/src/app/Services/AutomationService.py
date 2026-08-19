from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.Models.Account import Account
from app.Models.Automation import AutomationPolicy, AutomationRun
from app.Models.Command import AccountHeartbeat, Command
from app.Models.Model import row_to_dict
from app.Models.User import User
from app.Services.AccountScaffoldService import AccountScaffoldService
from app.Services.AssignmentRebalanceService import AssignmentRebalanceService
from app.Services.AssignmentService import AssignmentService
from app.Services.DriftService import DriftService
from app.Services.ProfileConfigService import ProfileConfigService
from app.Services.RunOrchestratorService import RunOrchestratorService
from app.Services.TelegramService import TelegramService
from app.Support.Lang import __
from app.Support.Time import utc_now_iso


@dataclass
class AccountHealthSnapshot:
    account: dict[str, Any]
    policy: dict[str, Any]
    heartbeat: dict[str, Any] | None
    age_minutes: int | None
    classification: str


class AutomationService:
    def __init__(
        self,
        db,
        *,
        runner: RunOrchestratorService | None = None,
        tg: TelegramService | None = None,
    ) -> None:
        self.db = db
        self.runner = runner
        self.tg = tg

    async def ensure_defaults(self) -> AutomationPolicy:
        row = await AutomationPolicy.resolve_for_account(
            self.db, user_id=0, account_id="__missing__"
        )
        if row:
            return row
        return await AutomationPolicy.upsert_scope(
            self.db,
            scope_type="global",
            scope_id="default",
            values={},
        )

    async def set_user_policy(self, user_id: int, values: dict[str, Any]) -> dict[str, Any]:
        await self.ensure_defaults()
        row = await AutomationPolicy.upsert_scope(
            self.db,
            scope_type="user",
            scope_id=str(user_id),
            values=self._sanitize_policy(values),
        )
        return row.to_view()

    async def toggle_user_policy(self, user_id: int, *, enabled: bool) -> dict[str, Any]:
        policy = await self.policy_for_user(user_id)
        return await self.set_user_policy(user_id, {**policy, "enabled": enabled})

    async def policy_for_user(self, user_id: int) -> dict[str, Any]:
        await self.ensure_defaults()
        user_row = (
            await AutomationPolicy.query(self.db)
            .where("scope_type", "user")
            .where("scope_id", str(user_id))
            .first()
        )
        if user_row:
            return user_row.to_view()
        global_row = (
            await AutomationPolicy.query(self.db)
            .where("scope_type", "global")
            .where("scope_id", "default")
            .first()
        )
        return global_row.to_view() if global_row else {}

    async def status_for_user(self, user_id: int) -> dict[str, Any]:
        policy = await self.policy_for_user(user_id)
        accounts = await Account.for_user(self.db, user_id)
        heartbeats = {
            str(hb.get("account_id")): hb.to_view()
            for hb in await AccountHeartbeat.query(self.db).get()
        }
        rows: list[dict[str, Any]] = []
        for acct in accounts:
            view = acct.to_view()
            hb = heartbeats.get(str(view.get("id")))
            age_minutes = self._age_minutes((hb or {}).get("updated_at"))
            rows.append(
                {
                    "account_id": view.get("id"),
                    "label": view.get("label"),
                    "role": view.get("role"),
                    "enabled": view.get("enabled"),
                    "status": view.get("status"),
                    "heartbeat_status": (hb or {}).get("status") or "-",
                    "heartbeat_age_minutes": age_minutes,
                    "classification": self._classify(age_minutes, policy),
                }
            )
        recent = await AutomationRun.list_recent_for_user(self.db, user_id=user_id, limit=10)
        drift = await self._drift_for_user(user_id)
        return {
            "policy": policy,
            "accounts": rows,
            "recent_runs": [r.to_view() for r in recent],
            "drift": drift,
        }

    async def run_watchdog(
        self,
        *,
        user_id: int | None = None,
        source: str = "manual",
    ) -> dict[str, Any]:
        await self.ensure_defaults()
        accounts = await self._accounts_for_watchdog(user_id=user_id)
        heartbeats = {
            str(hb.get("account_id")): hb.to_view()
            for hb in await AccountHeartbeat.query(self.db).get()
        }
        summary = {
            "source": source,
            "checked": 0,
            "warned": 0,
            "pinged": 0,
            "restarted": 0,
            "skipped": 0,
            "accounts": [],
        }
        for acct in accounts:
            row = await self._evaluate_account(acct, heartbeats.get(acct.account_key))
            summary["checked"] += 1
            summary["accounts"].append(row)
            action = str(row.get("action") or "skipped")
            if action == "warn_stale":
                summary["warned"] += 1
            elif action == "ping_probe":
                summary["pinged"] += 1
            elif action == "restart_account":
                summary["restarted"] += 1
            else:
                summary["skipped"] += 1
        return summary

    async def _accounts_for_watchdog(self, *, user_id: int | None) -> list[Account]:
        if user_id is not None:
            return await Account.for_user(self.db, user_id)
        result = await self.db.prepare(
            "SELECT * FROM accounts ORDER BY user_id ASC, id ASC"
        ).all()
        rows = getattr(result, "results", None)
        if hasattr(rows, "to_py"):
            rows = rows.to_py()
        out: list[Account] = []
        if isinstance(rows, list):
            for row in rows:
                data = row_to_dict(row)
                if data:
                    out.append(Account.from_row(data))
        return out

    async def _evaluate_account(
        self,
        acct: Account,
        hb: dict[str, Any] | None,
    ) -> dict[str, Any]:
        view = acct.to_view()
        user_id = int(view.get("user_id") or acct.get("user_id") or 0)
        policy_row = await AutomationPolicy.resolve_for_account(
            self.db, user_id=user_id, account_id=acct.account_key
        )
        policy = (
            policy_row.to_view()
            if policy_row
            else await self.policy_for_user(user_id)
        )
        age_minutes = self._age_minutes((hb or {}).get("updated_at"))
        classification = self._classify(age_minutes, policy)

        snapshot = AccountHealthSnapshot(
            account=view,
            policy=policy,
            heartbeat=hb,
            age_minutes=age_minutes,
            classification=classification,
        )

        # conservative filtering to respect Telegram safety
        if not policy.get("enabled", True):
            return self._action_view(snapshot, "skipped", "policy_disabled")
        if not view.get("enabled"):
            return self._action_view(snapshot, "skipped", "account_disabled")
        if str(view.get("status") or "").lower() != "ready":
            return self._action_view(snapshot, "skipped", "account_not_ready")
        if not self._role_allowed(str(view.get("role") or ""), policy):
            return self._action_view(snapshot, "skipped", "role_not_allowed")

        if classification == "healthy":
            return self._action_view(snapshot, "skipped", "healthy")

        if classification == "stale_restart":
            if await self._can_restart(acct.account_key, policy):
                info = await self._restart_account(user_id, acct.account_key, snapshot)
                return self._action_view(snapshot, "restart_account", "stale_restart", info)

        if classification in {"stale_restart", "stale_ping"}:
            if await self._can_ping(acct.account_key, policy):
                info = await self._ping_account(acct.account_key, snapshot)
                return self._action_view(snapshot, "ping_probe", "stale_ping", info)

        if classification == "stale_warn":
            if await self._can_warn(acct.account_key):
                await self._notify_owner(
                    acct,
                    __("auto.warn_msg",
                       account_id=acct.account_key,
                       age_minutes=snapshot.age_minutes or -1,
                       status=(hb or {}).get("status") or "-"),
                )
                await self._record_run(
                    user_id=user_id,
                    account_id=acct.account_key,
                    action="warn_stale",
                    reason="stale_warn",
                    cooldown_minutes=60,
                    details={"age_minutes": snapshot.age_minutes},
                    policy_id=policy.get("id"),
                )
                return self._action_view(snapshot, "warn_stale", "stale_warn")

        return self._action_view(snapshot, "skipped", classification)

    async def _ping_account(
        self, account_id: str, snapshot: AccountHealthSnapshot
    ) -> dict[str, Any]:
        cmd = await Command.enqueue(
            self.db,
            account_id=account_id,
            command_type="ping",
            payload={"source": "automation_watchdog"},
            issued_by="automation",
            ttl_seconds=300,
        )
        await self._record_run(
            user_id=int(snapshot.account.get("user_id") or 0),
            account_id=account_id,
            action="ping_probe",
            reason="stale_ping",
            cooldown_minutes=int(snapshot.policy.get("ping_after_minutes") or 15),
            details={"command_id": cmd.get("id"), "age_minutes": snapshot.age_minutes},
            policy_id=snapshot.policy.get("id"),
        )
        if snapshot.policy.get("notify_on_action"):
            await self._notify_owner(
                Account(**snapshot.account),
                __("auto.ping_msg",
                   account_id=account_id,
                   age_minutes=snapshot.age_minutes or -1),
            )
        return {"command_id": cmd.get("id")}

    async def _restart_account(
        self, user_id: int, account_id: str, snapshot: AccountHealthSnapshot
    ) -> dict[str, Any]:
        info: dict[str, Any] = {"run_id": None, "status": "runner_unavailable"}
        if self.runner is not None:
            try:
                info = await self.runner.restart(user_id, account_id)
                run_status = "done"
            except Exception as exc:
                info = {"error": str(exc)[:300]}
                run_status = "failed"
                rebalance = await self._rebalance_after_failure(
                    user_id=user_id, account_id=account_id
                )
                if rebalance:
                    info["rebalance"] = rebalance
        else:
            run_status = "skipped"
        await self._record_run(
            user_id=user_id,
            account_id=account_id,
            action="restart_account",
            reason="stale_restart",
            cooldown_minutes=int(snapshot.policy.get("restart_cooldown_minutes") or 180),
            details={"age_minutes": snapshot.age_minutes, **info},
            status=run_status,
            policy_id=snapshot.policy.get("id"),
        )
        if snapshot.policy.get("notify_on_action"):
            await self._notify_owner(
                Account(**snapshot.account),
                __("auto.restart_msg",
                   account_id=account_id,
                   age_minutes=snapshot.age_minutes or -1,
                   run_id=info.get("run_id") or "-"),
            )
        return info

    async def _record_run(
        self,
        *,
        user_id: int,
        account_id: str,
        action: str,
        reason: str,
        cooldown_minutes: int,
        details: dict[str, Any] | None = None,
        status: str = "done",
        policy_id: str | None = None,
    ) -> None:
        action_key = f"{account_id}:{action}:{self._bucket(cooldown_minutes)}"
        existing = await self.db.prepare(
            "SELECT id FROM automation_runs WHERE action_key = ?"
        ).bind(action_key).first()
        if row_to_dict(existing):
            return
        await AutomationRun.create(
            self.db,
            user_id=user_id,
            account_id=account_id,
            action=action,
            reason=reason,
            action_key=action_key,
            details=details,
            status=status,
            policy_id=policy_id,
        )

    async def _can_warn(self, account_id: str) -> bool:
        return not await self._recent_action(account_id, "warn_stale", 60)

    async def _can_ping(self, account_id: str, policy: dict[str, Any]) -> bool:
        return not await self._recent_action(
            account_id,
            "ping_probe",
            int(policy.get("ping_after_minutes") or 15),
        )

    async def _can_restart(self, account_id: str, policy: dict[str, Any]) -> bool:
        cooldown = int(policy.get("restart_cooldown_minutes") or 180)
        if await self._recent_action(account_id, "restart_account", cooldown):
            return False
        since_iso = (datetime.now(timezone.utc) - timedelta(days=1)).replace(
            microsecond=0
        ).isoformat()
        restarts_today = await AutomationRun.count_since(
            self.db,
            account_id=account_id,
            action="restart_account",
            since_iso=since_iso,
        )
        return restarts_today < int(policy.get("max_restarts_per_day") or 2)

    async def _recent_action(self, account_id: str, action: str, minutes: int) -> bool:
        rows = await AutomationRun.recent_for_account_action(
            self.db, account_id=account_id, action=action, limit=5
        )
        now = datetime.now(timezone.utc)
        for row in rows:
            dt = self._parse_iso(row.get("created_at"))
            if not dt:
                continue
            if (now - dt).total_seconds() < minutes * 60:
                return True
        return False

    async def _notify_owner(self, acct: Account, text: str) -> None:
        if self.tg is None:
            return
        owner = await User.find(self.db, int(acct.get("user_id") or 0))
        if not owner:
            return
        chat_id = int(owner.get("chat_id") or owner.get("telegram_id") or 0)
        if chat_id:
            await self.tg.send_message(chat_id, text)

    def _sanitize_policy(self, values: dict[str, Any]) -> dict[str, Any]:
        warn_after = max(5, int(values.get("warn_after_minutes", 10)))
        ping_after = max(warn_after, int(values.get("ping_after_minutes", 15)))
        restart_after = max(ping_after, int(values.get("restart_after_minutes", 30)))
        restart_cooldown = max(30, int(values.get("restart_cooldown_minutes", 180)))
        max_restarts = max(0, min(6, int(values.get("max_restarts_per_day", 2))))
        return {
            "enabled": bool(values.get("enabled", True)),
            "warn_after_minutes": warn_after,
            "ping_after_minutes": ping_after,
            "restart_after_minutes": restart_after,
            "restart_cooldown_minutes": restart_cooldown,
            "max_restarts_per_day": max_restarts,
            "notify_on_warn": bool(values.get("notify_on_warn", True)),
            "notify_on_action": bool(values.get("notify_on_action", True)),
            "allowed_roles_csv": values.get("allowed_roles_csv") or "",
        }

    def _role_allowed(self, role: str, policy: dict[str, Any]) -> bool:
        raw = str(policy.get("allowed_roles_csv") or "").strip()
        if not raw:
            return True
        allowed = {p.strip().lower() for p in raw.split(",") if p.strip()}
        return role.lower() in allowed

    def _classify(self, age_minutes: int | None, policy: dict[str, Any]) -> str:
        if age_minutes is None:
            return "stale_ping"
        if age_minutes >= int(policy.get("restart_after_minutes") or 30):
            return "stale_restart"
        if age_minutes >= int(policy.get("ping_after_minutes") or 15):
            return "stale_ping"
        if age_minutes >= int(policy.get("warn_after_minutes") or 10):
            return "stale_warn"
        return "healthy"

    def _action_view(
        self,
        snapshot: AccountHealthSnapshot,
        action: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "account_id": snapshot.account.get("id"),
            "role": snapshot.account.get("role"),
            "enabled": snapshot.account.get("enabled"),
            "status": snapshot.account.get("status"),
            "heartbeat_status": (snapshot.heartbeat or {}).get("status") or "-",
            "heartbeat_age_minutes": snapshot.age_minutes,
            "classification": snapshot.classification,
            "action": action,
            "reason": reason,
            "details": details or {},
        }

    def _age_minutes(self, updated_at: str | None) -> int | None:
        dt = self._parse_iso(updated_at)
        if not dt:
            return None
        age_seconds = (datetime.now(timezone.utc) - dt).total_seconds()
        return max(0, int(age_seconds // 60))

    def _parse_iso(self, raw: Any) -> datetime | None:
        text = str(raw or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return None

    def _bucket(self, minutes: int) -> str:
        minutes = max(1, int(minutes))
        epoch_minutes = math.floor(datetime.now(timezone.utc).timestamp() / 60)
        return str(epoch_minutes // minutes)

    async def _drift_for_user(self, user_id: int) -> dict[str, Any]:
        if self.runner is None:
            return {"accounts": [], "assignment_only": 0, "profile_only": 0}
        scaffold = AccountScaffoldService(self.runner.github)
        profile = ProfileConfigService(self.db, scaffold)
        return await DriftService(self.db, profile).scan_user(user_id)

    async def _rebalance_after_failure(
        self, *, user_id: int, account_id: str
    ) -> dict[str, Any] | None:
        if self.runner is None:
            return None
        scaffold = AccountScaffoldService(self.runner.github)
        assignments = AssignmentService(self.db, scaffold, self.runner)
        try:
            result = await AssignmentRebalanceService(assignments).rebalance_failed_account(
                user_id=user_id, failed_account_id=account_id
            )
        except Exception:
            return None
        if not result.get("count"):
            return None
        return result
