"""Admin panel menu controller — thin router over feature controllers."""
from __future__ import annotations

from app.Http.Controllers.AccountsController import AccountsController
from app.Http.Controllers.AssignmentController import AssignmentController
from app.Http.Controllers.CommandController import CommandController
from app.Http.Controllers.ForwardController import ForwardController
from app.Http.Controllers.HelpController import HelpController
from app.Http.Controllers.OpsController import OpsController
from app.Http.Controllers.PanelController import PanelController
from app.Models.User import User
from app.Models.UserState import UserState
from app.Services.GitHubService import GitHubError
from app.Services.RunOrchestratorService import RunOrchestratorService
from app.Services.TelegramService import TelegramService
from app.Support.GithubFactory import make_github
from app.Support.ErrorFormat import friendly_error
from app.Support.Lang import __
from config.bot import BotConfig
from config.menus import main_keyboard, settings_keyboard

ST_SETTINGS_DEMOTE = "settings_demote"
ST_SETTINGS_STATS = "settings_stats"
ST_SETTINGS_MODULES = "settings_modules"


class AdminController:
    def __init__(self, tg: TelegramService, config: BotConfig, ctx=None) -> None:
        self.tg = tg
        self.config = config
        self.db = config.db
        self.accounts = AccountsController(tg, config, ctx=ctx)
        self.ops = OpsController(tg, config)
        self.panel = PanelController(tg, config)
        self.forward = ForwardController(tg, config)
        self.help = HelpController(tg, config)
        self.commands = CommandController(tg, config)
        self.assignment = AssignmentController(tg, config)

    def _runner(self) -> RunOrchestratorService | None:
        gh = make_github(self.config)
        if not gh:
            return None
        return RunOrchestratorService(self.db, gh)

    async def welcome(self, chat_id: int, user: User) -> None:
        await UserState.clear(self.db, int(user.get("telegram_id")))
        await self.tg.send_message(
            chat_id,
            __("auth.welcome_admin", name=user.display_name),
            reply_markup=main_keyboard(),
        )

    async def whoami(self, chat_id: int, user: User) -> None:
        await self.tg.send_message(
            chat_id,
            __(
                "auth.whoami",
                user_id=user.get("telegram_id"),
                chat_id=chat_id,
                role=user.get("role"),
            ),
            reply_markup=main_keyboard(),
        )

    async def settings(self, chat_id: int, user: User) -> None:
        counts = await User.role_counts(self.db)
        admins = await User.admins(self.db, limit=20)
        lines = [
            __(
                "menu.settings_header",
                total=counts.get("total", 0),
                admin=counts.get("admin", 0),
                user=counts.get("user", 0),
            )
        ]
        if not admins:
            lines.append(__("menu.settings_no_admins"))
        for row in admins:
            uname = row.get("username")
            label = f"@{uname}" if uname else (row.get("first_name") or "user")
            me = int(row.get("telegram_id") or 0) == int(user.get("telegram_id") or -1)
            me_flag = " ← شما" if me else ""
            lines.append(
                __(
                    "menu.settings_admin_line",
                    label=label,
                    telegram_id=row.get("telegram_id"),
                )
                + me_flag
            )
        await self.tg.send_message(
            chat_id,
            "\n".join(lines),
            reply_markup=settings_keyboard(),
        )

    async def dispatch_text(self, chat_id: int, user: User, text: str) -> None:
        t = (text or "").strip()
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        current = str(state.get("state") or "")

        # Help owns input while its wizard is active (before feature menu labels).
        if current.startswith("help_"):
            if await self.help.handle(chat_id, user, t):
                return

        # Settings wizard states.
        if current == ST_SETTINGS_DEMOTE:
            await self._finish_demote(chat_id, user, t)
            return
        if current == ST_SETTINGS_STATS:
            await self._finish_stats(chat_id, user, t)
            return
        if current == ST_SETTINGS_MODULES:
            await self._finish_modules(chat_id, user, t)
            return

        # Feature wizards first (consume when active / entry buttons).
        if await self.accounts.handle(chat_id, user, t):
            return
        if await self.ops.handle(chat_id, user, t):
            return
        if await self.panel.handle(chat_id, user, t):
            return
        if await self.forward.handle(chat_id, user, t):
            return
        if await self.commands.handle(chat_id, user, t):
            return
        if await self.assignment.handle(chat_id, user, t):
            return
        if await self.help.handle(chat_id, user, t):
            return

        if t in {"/start", "start", "منو", "/menu"}:
            await self.welcome(chat_id, user)
            return
        if t == "/whoami":
            await self.whoami(chat_id, user)
            return
        if t in {__("menu.btn_settings"), "تنظیمات", "/admins", "⚙️ تنظیمات"}:
            await self.settings(chat_id, user)
            return
        if t in {__("accounts.btn_back"), "منوی اصلی"}:
            await self.welcome(chat_id, user)
            return

        # Settings sub-actions.
        if t == __("settings.btn_demote"):
            await self._start_demote(chat_id, user)
            return
        if t == __("settings.btn_stats"):
            await self._start_stats(chat_id, user)
            return
        if t == __("settings.btn_modules"):
            await self._start_modules(chat_id, user)
            return

        await self.tg.send_message(
            chat_id, __("menu.unknown"), reply_markup=main_keyboard()
        )

    # ------------------------------------------------------------------
    # Settings: demote admin
    # ------------------------------------------------------------------

    async def _start_demote(self, chat_id: int, user: User) -> None:
        tid = int(user.get("telegram_id"))
        admins = await User.admins(self.db, limit=20)
        others = [
            r for r in admins
            if int(r.get("telegram_id") or 0) != tid
        ]
        if not others:
            await self.tg.send_message(
                chat_id, __("settings.demote_no_others"), reply_markup=settings_keyboard()
            )
            return
        lines = [__("settings.demote_pick")]
        for r in others:
            uname = r.get("username")
            label = f"@{uname}" if uname else (r.get("first_name") or "user")
            lines.append(f"• <code>{r.get('telegram_id')}</code> — {label}")
        await UserState.set_state(self.db, tid, ST_SETTINGS_DEMOTE, {})
        await self.tg.send_message(
            chat_id, "\n".join(lines), reply_markup=settings_keyboard()
        )

    async def _finish_demote(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        if t in {__("accounts.btn_cancel"), __("accounts.btn_back"), "/cancel"}:
            await UserState.clear(self.db, tid)
            await self.settings(chat_id, user)
            return
        try:
            target_id = int(t.strip().lstrip("@").split()[0])
        except (ValueError, IndexError):
            await self.tg.send_message(
                chat_id, __("settings.demote_bad_id"), reply_markup=settings_keyboard()
            )
            return
        if target_id == tid:
            await self.tg.send_message(
                chat_id, __("settings.demote_self"), reply_markup=settings_keyboard()
            )
            return
        target = await User.find(self.db, target_id)
        if not target or not target.is_admin:
            await self.tg.send_message(
                chat_id, __("settings.demote_not_admin"), reply_markup=settings_keyboard()
            )
            return
        await target.demote_to_user(self.db)
        await UserState.clear(self.db, tid)
        uname = target.get("username")
        label = f"@{uname}" if uname else (target.get("first_name") or str(target_id))
        await self.tg.send_message(
            chat_id,
            __("settings.demote_done", label=label, telegram_id=target_id),
            reply_markup=settings_keyboard(),
        )

    # ------------------------------------------------------------------
    # Settings: stats_dump
    # ------------------------------------------------------------------

    async def _start_stats(self, chat_id: int, user: User) -> None:
        tid = int(user.get("telegram_id"))
        from app.Services.AccountService import AccountService

        rows = await AccountService(self.db).list_for_user(tid)
        if not rows:
            await self.tg.send_message(
                chat_id, __("settings.stats_no_accounts"), reply_markup=settings_keyboard()
            )
            return
        ids = [str(r.get("id")) for r in rows[:24] if r.get("id")]
        await UserState.set_state(self.db, tid, ST_SETTINGS_STATS, {})
        from config.menus import accounts_pick_keyboard
        await self.tg.send_message(
            chat_id, __("settings.stats_pick"), reply_markup=accounts_pick_keyboard(ids)
        )

    async def _finish_stats(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        if t in {__("accounts.btn_cancel"), __("accounts.btn_back"), "/cancel"}:
            await UserState.clear(self.db, tid)
            await self.settings(chat_id, user)
            return
        from app.Services.AccountScaffoldService import validate_account_id
        aid = validate_account_id(t)
        if not aid:
            await self.tg.send_message(chat_id, __("accounts.invalid_id"))
            return
        runner = self._runner()
        if not runner:
            await self.tg.send_message(
                chat_id, __("accounts.missing_github"), reply_markup=settings_keyboard()
            )
            return
        await UserState.clear(self.db, tid)
        await self.tg.send_message(chat_id, __("cache.working", action="stats_dump"))
        try:
            info = await runner.account_cache_admin(
                tid, aid, action="stats_dump", notify_chat_id=chat_id
            )
        except Exception as exc:
            await self.tg.send_message(
                chat_id,
                __("accounts.error", error=friendly_error(exc)),
                reply_markup=settings_keyboard(),
            )
            return
        await self.tg.send_message(
            chat_id,
            __(
                "cache.dispatched",
                action="stats_dump",
                account_id=aid,
                run_id=info.get("run_id") or "-",
                url=info.get("html_url") or "",
            ),
            reply_markup=settings_keyboard(),
        )

    # ------------------------------------------------------------------
    # Settings: modules on/off/reload
    # ------------------------------------------------------------------

    async def _start_modules(self, chat_id: int, user: User) -> None:
        tid = int(user.get("telegram_id"))
        from app.Services.AccountService import AccountService
        rows = await AccountService(self.db).list_for_user(tid)
        if not rows:
            await self.tg.send_message(
                chat_id, __("settings.modules_no_accounts"), reply_markup=settings_keyboard()
            )
            return
        ids = [str(r.get("id")) for r in rows[:24] if r.get("id")]
        await UserState.set_state(self.db, tid, ST_SETTINGS_MODULES, {})
        from config.menus import accounts_pick_keyboard
        await self.tg.send_message(
            chat_id, __("settings.modules_pick"), reply_markup=accounts_pick_keyboard(ids)
        )

    async def _finish_modules(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        ctx = state.context

        if t in {__("accounts.btn_cancel"), __("accounts.btn_back"), "/cancel"}:
            await UserState.clear(self.db, tid)
            await self.settings(chat_id, user)
            return

        # Step 1 — pick account
        if not ctx.get("account_id"):
            from app.Services.AccountScaffoldService import validate_account_id
            aid = validate_account_id(t)
            if not aid:
                await self.tg.send_message(chat_id, __("accounts.invalid_id"))
                return
            await UserState.set_state(
                self.db, tid, ST_SETTINGS_MODULES, {"account_id": aid}
            )
            from config.menus import modules_action_keyboard
            await self.tg.send_message(
                chat_id,
                __("settings.modules_ask_action", account_id=aid),
                reply_markup=modules_action_keyboard(),
            )
            return

        # Step 2 — pick action
        aid = str(ctx.get("account_id") or "")
        action_map = {
            __("settings.modules_btn_on"): "on",
            __("settings.modules_btn_off"): "off",
            __("settings.modules_btn_reload"): "reload",
        }
        if t not in action_map:
            await self.tg.send_message(chat_id, __("menu.unknown"))
            return
        action = action_map[t]

        from app.Services.AccountScaffoldService import AccountScaffoldService
        from app.Support.GithubFactory import make_scaffold
        scaffold = make_scaffold(self.config)
        if not scaffold:
            await self.tg.send_message(
                chat_id, __("accounts.missing_github"), reply_markup=settings_keyboard()
            )
            return
        await UserState.clear(self.db, tid)
        try:
            if action == "reload":
                # patch enabled=true to trigger runner to reload config
                result = await scaffold.patch_profile_modules(
                    aid, "auto_reply", {"enabled": True}
                )
                detail = __("settings.modules_reload_note")
            else:
                enabled = (action == "on")
                result = await scaffold.patch_profile_modules(
                    aid, "auto_reply", {"enabled": enabled}
                )
                detail = f"enabled={enabled}"
        except (GitHubError, Exception) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc)),
                reply_markup=settings_keyboard(),
            )
            return
        await self.tg.send_message(
            chat_id,
            __(
                "settings.modules_done",
                account_id=aid,
                action=action,
                detail=detail,
            ),
            reply_markup=settings_keyboard(),
        )

