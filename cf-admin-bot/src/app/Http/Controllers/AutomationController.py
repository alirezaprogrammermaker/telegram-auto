from __future__ import annotations

from app.Models.User import User
from app.Models.UserState import UserState
from app.Services.AutomationService import AutomationService
from app.Services.RunOrchestratorService import RunOrchestratorService
from app.Services.TelegramService import TelegramService
from app.Support.ErrorFormat import friendly_error
from app.Support.GithubFactory import make_github
from app.Support.Lang import __
from config.bot import BotConfig
from config.menus import main_keyboard

ST_AUTO_MENU = "auto_menu"
ST_AUTO_THRESHOLDS = "auto_thresholds"


def _auto_menu_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("auto.btn_status")},
                {"text": __("auto.btn_run_now")},
            ],
            [
                {"text": __("auto.btn_enable")},
                {"text": __("auto.btn_disable")},
            ],
            [
                {"text": __("auto.btn_thresholds")},
                {"text": __("accounts.btn_back")},
            ],
        ],
        "resize_keyboard": True,
    }


class AutomationController:
    def __init__(self, tg: TelegramService, config: BotConfig) -> None:
        self.tg = tg
        self.config = config
        self.db = config.db

    def _service(self) -> AutomationService:
        gh = make_github(self.config)
        runner = RunOrchestratorService(self.db, gh) if gh else None
        return AutomationService(self.db, runner=runner, tg=self.tg)

    async def open_menu(self, chat_id: int, user: User) -> None:
        tid = int(user.get("telegram_id"))
        await UserState.set_state(self.db, tid, ST_AUTO_MENU, {})
        await self.tg.send_message(
            chat_id,
            __("auto.menu"),
            reply_markup=_auto_menu_keyboard(),
        )

    async def handle(self, chat_id: int, user: User, text: str) -> bool:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        current = str(state.get("state") or "")
        t = (text or "").strip()

        if t in {__("menu.btn_automation"), "🤖 خودکارسازی", "خودکارسازی"}:
            await self.open_menu(chat_id, user)
            return True

        if current not in {ST_AUTO_MENU, ST_AUTO_THRESHOLDS}:
            return False

        if t in {"/cancel", __("accounts.btn_cancel"), "انصراف"}:
            await UserState.clear(self.db, tid)
            await self.tg.send_message(
                chat_id, __("auto.cancelled"), reply_markup=main_keyboard()
            )
            return True

        if t in {__("accounts.btn_back"), "منوی اصلی"}:
            await UserState.clear(self.db, tid)
            await self.tg.send_message(
                chat_id,
                __("auth.welcome_admin", name=user.display_name),
                reply_markup=main_keyboard(),
            )
            return True

        if current == ST_AUTO_MENU:
            await self._handle_menu_choice(chat_id, user, t)
            return True

        if current == ST_AUTO_THRESHOLDS:
            await self._save_thresholds(chat_id, user, t)
            return True

        return False

    async def _handle_menu_choice(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        svc = self._service()
        if t == __("auto.btn_status"):
            status = await svc.status_for_user(tid)
            await self.tg.send_message(
                chat_id, _format_status(status), reply_markup=_auto_menu_keyboard()
            )
            return
        if t == __("auto.btn_run_now"):
            await self.tg.send_message(chat_id, __("auto.running"))
            try:
                result = await svc.run_watchdog(user_id=tid, source="manual_ui")
            except Exception as exc:
                await self.tg.send_message(
                    chat_id,
                    __("accounts.error", error=friendly_error(exc)),
                    reply_markup=_auto_menu_keyboard(),
                )
                return
            await self.tg.send_message(
                chat_id, _format_run_summary(result), reply_markup=_auto_menu_keyboard()
            )
            return
        if t == __("auto.btn_enable"):
            policy = await svc.toggle_user_policy(tid, enabled=True)
            await self.tg.send_message(
                chat_id,
                __("auto.toggled", state="ON", updated_at=policy.get("updated_at")),
                reply_markup=_auto_menu_keyboard(),
            )
            return
        if t == __("auto.btn_disable"):
            policy = await svc.toggle_user_policy(tid, enabled=False)
            await self.tg.send_message(
                chat_id,
                __("auto.toggled", state="OFF", updated_at=policy.get("updated_at")),
                reply_markup=_auto_menu_keyboard(),
            )
            return
        if t == __("auto.btn_thresholds"):
            policy = await svc.policy_for_user(tid)
            await UserState.set_state(self.db, tid, ST_AUTO_THRESHOLDS, {})
            await self.tg.send_message(
                chat_id,
                __(
                    "auto.ask_thresholds",
                    warn=policy.get("warn_after_minutes"),
                    ping=policy.get("ping_after_minutes"),
                    restart=policy.get("restart_after_minutes"),
                    cooldown=policy.get("restart_cooldown_minutes"),
                    max_restarts=policy.get("max_restarts_per_day"),
                ),
                reply_markup=_auto_menu_keyboard(),
            )

    async def _save_thresholds(self, chat_id: int, user: User, text: str) -> None:
        tid = int(user.get("telegram_id"))
        parts = [p for p in text.replace("،", ",").replace(",", " ").split() if p]
        if len(parts) != 5:
            await self.tg.send_message(chat_id, __("auto.bad_thresholds"))
            return
        try:
            warn, ping, restart, cooldown, max_restarts = [int(x) for x in parts]
        except ValueError:
            await self.tg.send_message(chat_id, __("auto.bad_thresholds"))
            return
        svc = self._service()
        try:
            policy = await svc.set_user_policy(
                tid,
                {
                    "warn_after_minutes": warn,
                    "ping_after_minutes": ping,
                    "restart_after_minutes": restart,
                    "restart_cooldown_minutes": cooldown,
                    "max_restarts_per_day": max_restarts,
                    "enabled": True,
                },
            )
        except Exception as exc:
            await self.tg.send_message(
                chat_id,
                __("accounts.error", error=friendly_error(exc)),
                reply_markup=_auto_menu_keyboard(),
            )
            return
        await UserState.set_state(self.db, tid, ST_AUTO_MENU, {})
        await self.tg.send_message(
            chat_id,
            __("auto.thresholds_saved",
               warn=policy.get("warn_after_minutes"),
               ping=policy.get("ping_after_minutes"),
               restart=policy.get("restart_after_minutes"),
               cooldown=policy.get("restart_cooldown_minutes"),
               max_restarts=policy.get("max_restarts_per_day")),
            reply_markup=_auto_menu_keyboard(),
        )


def _format_status(status: dict) -> str:
    policy = status.get("policy") or {}
    lines = [
        __("auto.status_header"),
        "",
        __("auto.status_policy",
           enabled="ON" if policy.get("enabled") else "OFF",
           warn=policy.get("warn_after_minutes"),
           ping=policy.get("ping_after_minutes"),
           restart=policy.get("restart_after_minutes"),
           cooldown=policy.get("restart_cooldown_minutes"),
           max_restarts=policy.get("max_restarts_per_day")),
        "",
    ]
    for row in status.get("accounts") or []:
        lines.append(
            __(
                "auto.status_account",
                account_id=row.get("account_id"),
                role=row.get("role"),
                hb_status=row.get("heartbeat_status"),
                age=row.get("heartbeat_age_minutes")
                if row.get("heartbeat_age_minutes") is not None else "-",
                classification=row.get("classification"),
            )
        )
    recent = status.get("recent_runs") or []
    if recent:
        lines.append("")
        lines.append(__("auto.status_recent"))
        for item in recent[:5]:
            lines.append(
                __("auto.status_recent_line",
                   action=item.get("action"),
                   account_id=item.get("account_id"),
                   status=item.get("status"),
                   reason=item.get("reason"))
            )
    return "\n".join(lines)


def _format_run_summary(summary: dict) -> str:
    lines = [
        __("auto.run_summary_header"),
        __("auto.run_summary_counts",
           checked=summary.get("checked", 0),
           warned=summary.get("warned", 0),
           pinged=summary.get("pinged", 0),
           restarted=summary.get("restarted", 0),
           skipped=summary.get("skipped", 0)),
    ]
    interesting = [
        row for row in (summary.get("accounts") or [])
        if row.get("action") != "skipped"
    ]
    for row in interesting[:8]:
        lines.append(
            __("auto.run_summary_line",
               account_id=row.get("account_id"),
               action=row.get("action"),
               reason=row.get("reason"))
        )
    return "\n".join(lines)
