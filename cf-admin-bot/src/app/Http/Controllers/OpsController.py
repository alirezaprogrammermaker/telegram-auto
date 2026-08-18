"""Ops menu — dispatch / cancel / restart / merge pool (GHA only)."""
from __future__ import annotations

from app.Models.User import User
from app.Models.UserState import UserState
from app.Services.AccountScaffoldService import validate_account_id
from app.Services.AccountService import AccountConflictError, AccountService
from app.Services.GitHubService import GitHubError
from app.Services.RunOrchestratorService import RunOrchestratorService
from app.Services.TelegramService import TelegramService
from app.Support.GithubFactory import make_github
from app.Support.Lang import __
from config.bot import BotConfig
from config.menus import (
    accounts_pick_keyboard,
    confirm_ops_keyboard,
    main_keyboard,
    ops_menu_keyboard,
)

ST_OPS_MENU = "ops_menu"
ST_OPS_PICK = "ops_pick"
ST_OPS_CONFIRM = "ops_confirm"

ACTIONS = frozenset({"dispatch", "cancel", "restart", "merge"})


class OpsController:
    def __init__(self, tg: TelegramService, config: BotConfig) -> None:
        self.tg = tg
        self.config = config
        self.db = config.db

    def _runner(self) -> RunOrchestratorService | None:
        gh = make_github(self.config)
        if not gh:
            return None
        return RunOrchestratorService(self.db, gh)

    async def open_menu(self, chat_id: int, user: User) -> None:
        tid = int(user.get("telegram_id"))
        await UserState.set_state(self.db, tid, ST_OPS_MENU, {})
        await self.tg.send_message(
            chat_id, __("ops.menu"), reply_markup=ops_menu_keyboard()
        )

    async def cancel(self, chat_id: int, user: User) -> None:
        await UserState.clear(self.db, int(user.get("telegram_id")))
        await self.tg.send_message(
            chat_id, __("ops.cancelled"), reply_markup=main_keyboard()
        )

    async def handle(self, chat_id: int, user: User, text: str) -> bool:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        t = (text or "").strip()

        if t in {__("menu.btn_ops"), "عملیات", "🛠 عملیات"}:
            await self.open_menu(chat_id, user)
            return True

        current = str(state.get("state") or "")
        if current not in {ST_OPS_MENU, ST_OPS_PICK, ST_OPS_CONFIRM}:
            return False

        if t in {
            __("menu.btn_status"),
            __("menu.btn_accounts"),
            __("menu.btn_discovery"),
            __("menu.btn_promo"),
            __("menu.btn_settings"),
            "وضعیت",
            "اکانت‌ها",
            "کشف",
            "تبلیغ",
            "تنظیمات",
        }:
            await UserState.clear(self.db, tid)
            return False

        if t in {"/cancel", __("accounts.btn_cancel"), "انصراف"}:
            await self.cancel(chat_id, user)
            return True

        if t in {__("accounts.btn_back"), "منوی اصلی"}:
            await UserState.clear(self.db, tid)
            await self.tg.send_message(
                chat_id,
                __("auth.welcome_admin", name=user.display_name),
                reply_markup=main_keyboard(),
            )
            return True

        if current == ST_OPS_MENU:
            await self._menu_choice(chat_id, user, t)
            return True
        if current == ST_OPS_PICK:
            await self._pick_account(chat_id, user, t)
            return True
        if current == ST_OPS_CONFIRM:
            await self._confirm(chat_id, user, t)
            return True
        return False

    async def _menu_choice(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        if not self.config.github_ready():
            await self.tg.send_message(
                chat_id, __("accounts.missing_github"), reply_markup=main_keyboard()
            )
            await UserState.clear(self.db, tid)
            return

        action = None
        if t == __("ops.btn_dispatch"):
            action = "dispatch"
        elif t == __("ops.btn_cancel_run"):
            action = "cancel"
        elif t == __("ops.btn_restart"):
            action = "restart"
        elif t == __("ops.btn_merge"):
            await UserState.set_state(
                self.db, tid, ST_OPS_CONFIRM, {"action": "merge"}
            )
            await self.tg.send_message(
                chat_id,
                __("ops.confirm_merge"),
                reply_markup=confirm_ops_keyboard("merge"),
            )
            return

        if not action:
            await self.tg.send_message(
                chat_id, __("ops.menu"), reply_markup=ops_menu_keyboard()
            )
            return

        rows = await AccountService(self.db).list_for_user(tid)
        ids = [str(r.get("id")) for r in rows if r.get("id")]
        if not ids:
            await self.tg.send_message(
                chat_id, __("accounts.list_empty"), reply_markup=ops_menu_keyboard()
            )
            return
        await UserState.set_state(
            self.db, tid, ST_OPS_PICK, {"action": action}
        )
        await self.tg.send_message(
            chat_id,
            __("ops.pick", action=__("ops.action_" + action)),
            reply_markup=accounts_pick_keyboard(ids),
        )

    async def _pick_account(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        action = str(state.context.get("action") or "")
        if action not in ACTIONS:
            await self.open_menu(chat_id, user)
            return
        aid = validate_account_id(t)
        if not aid:
            await self.tg.send_message(chat_id, __("accounts.invalid_id"))
            return
        try:
            await AccountService(self.db).require_owned(tid, aid)
        except AccountConflictError:
            await self.tg.send_message(
                chat_id, __("accounts.not_owned", account_id=t)
            )
            return
        await UserState.set_state(
            self.db, tid, ST_OPS_CONFIRM, {"action": action, "account_id": aid}
        )
        await self.tg.send_message(
            chat_id,
            __(
                "ops.confirm_account",
                action=__("ops.action_" + action),
                account_id=aid,
            ),
            reply_markup=confirm_ops_keyboard(action),
        )

    async def _confirm(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        action = str(state.context.get("action") or "")
        aid = str(state.context.get("account_id") or "")
        expected = __("ops.btn_confirm_" + action) if action in ACTIONS else ""
        if t != expected:
            await self.open_menu(chat_id, user)
            return

        runner = self._runner()
        if not runner:
            await self.tg.send_message(
                chat_id, __("accounts.missing_github"), reply_markup=main_keyboard()
            )
            await UserState.clear(self.db, tid)
            return

        await self.tg.send_message(chat_id, __("ops.working", action=__("ops.action_" + action)))
        try:
            if action == "merge":
                info = await runner.merge_pool()
            elif action == "dispatch":
                info = await runner.dispatch(tid, aid)
            elif action == "cancel":
                info = await runner.cancel(tid, aid)
            elif action == "restart":
                info = await runner.restart(tid, aid)
            else:
                await self.open_menu(chat_id, user)
                return
        except AccountConflictError as exc:
            key = {
                "account_disabled": "ops.account_disabled",
                "account_not_owned": "accounts.not_owned",
            }.get(exc.code, "accounts.error")
            await UserState.set_state(self.db, tid, ST_OPS_MENU, {})
            await self.tg.send_message(
                chat_id,
                __(key, account_id=exc.account_id or aid, error=exc.code),
                reply_markup=ops_menu_keyboard(),
            )
            return
        except GitHubError as exc:
            await UserState.set_state(self.db, tid, ST_OPS_MENU, {})
            await self.tg.send_message(
                chat_id,
                __("accounts.error", error=str(exc)[:240]),
                reply_markup=ops_menu_keyboard(),
            )
            return

        await UserState.set_state(self.db, tid, ST_OPS_MENU, {})
        if action == "cancel" and not info.get("cancelled"):
            body = __("ops.cancel_none", account_id=aid)
        else:
            body = __(
                "ops.done",
                action=__("ops.action_" + action),
                account_id=aid or "pool",
                run_id=info.get("run_id") or "-",
                status=info.get("status") or "-",
                conclusion=info.get("conclusion") or "-",
                url=info.get("html_url") or "",
            )
        await self.tg.send_message(chat_id, body, reply_markup=ops_menu_keyboard())
