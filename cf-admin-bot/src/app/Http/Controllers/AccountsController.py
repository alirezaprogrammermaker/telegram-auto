"""Accounts menu + login wizard (conversation state machine)."""
from __future__ import annotations

from app.Models.LoginSession import LoginSession
from app.Models.User import User
from app.Models.UserState import UserState
from app.Services.AccountScaffoldService import (
    ROLES,
    validate_account_id,
    validate_label,
    validate_phone,
    validate_role,
)
from app.Services.AccountService import AccountConflictError, AccountService
from app.Services.GitHubService import GitHubError, GitHubService
from app.Services.LoginOrchestratorService import LoginOrchestratorService
from app.Services.TelegramService import TelegramService
from app.Support.GithubFactory import make_github, make_scaffold
from app.Support.Lang import __
from config.bot import BotConfig
from config.menus import (
    accounts_menu_keyboard,
    accounts_pick_keyboard,
    confirm_delete_keyboard,
    confirm_enable_keyboard,
    confirm_keyboard,
    confirm_logout_keyboard,
    main_keyboard,
    manage_actions_keyboard,
    otp_keyboard,
    rename_keyboard,
    role_pick_keyboard,
    roles_keyboard,
)

# conversation states
ST_ACCOUNTS_MENU = "accounts_menu"
ST_ADD_ID = "accounts_add_id"
ST_ADD_ROLE = "accounts_add_role"
ST_ADD_PHONE = "accounts_add_phone"
ST_ADD_CONFIRM = "accounts_add_confirm"
ST_LOGIN_ID = "accounts_login_id"
ST_LOGIN_PHONE = "accounts_login_phone"
ST_LOGIN_CONFIRM = "accounts_login_confirm"
ST_AWAIT_OTP = "accounts_await_otp"
ST_AWAIT_2FA = "accounts_await_2fa"
ST_MANAGE_PICK = "accounts_manage_pick"
ST_MANAGE_ACTION = "accounts_manage_action"
ST_MANAGE_CONFIRM_LOGOUT = "accounts_manage_confirm_logout"
ST_MANAGE_CONFIRM_DELETE = "accounts_manage_confirm_delete"
ST_MANAGE_CONFIRM_ENABLE = "accounts_manage_confirm_enable"
ST_MANAGE_RENAME = "accounts_manage_rename"
ST_MANAGE_ROLE = "accounts_manage_role"


def _noise_buttons() -> set[str]:
    return {
        __("menu.btn_status"),
        __("menu.btn_accounts"),
        __("menu.btn_discovery"),
        __("menu.btn_promo"),
        __("menu.btn_ops"),
        __("menu.btn_settings"),
        __("accounts.btn_list"),
        __("accounts.btn_add"),
        __("accounts.btn_login"),
        __("accounts.btn_manage"),
        __("accounts.btn_enable"),
        __("accounts.btn_disable"),
        __("accounts.btn_rename"),
        __("accounts.btn_auto_label"),
        __("accounts.btn_change_role"),
        __("accounts.btn_vacant_roles"),
        __("accounts.btn_all_roles"),
        __("accounts.btn_logout"),
        __("accounts.btn_delete"),
        __("accounts.btn_manage_back"),
        __("accounts.btn_back"),
        "اکانت‌ها",
        "👥 اکانت‌ها",
        "وضعیت",
        "تنظیمات",
    }


def _other_main_menu(t: str) -> bool:
    """Main-menu buttons that should leave the accounts wizard."""
    return t in {
        __("menu.btn_status"),
        __("menu.btn_discovery"),
        __("menu.btn_promo"),
        __("menu.btn_ops"),
        __("menu.btn_settings"),
        "وضعیت",
        "کشف",
        "تبلیغ",
        "عملیات",
        "تنظیمات",
        "📊 وضعیت",
        "🧺 کشف",
        "📣 تبلیغ",
        "🛠 عملیات",
        "⚙️ تنظیمات",
    }


class AccountsController:
    def __init__(self, tg: TelegramService, config: BotConfig, ctx=None) -> None:
        self.tg = tg
        self.config = config
        self.db = config.db
        self.ctx = ctx

    def _schedule(self, coro) -> bool:
        """Run work after webhook responds (preferred), else caller should await."""
        if self.ctx is None:
            return False
        try:
            self.ctx.waitUntil(coro)
            return True
        except Exception:
            return False

    async def _watch_complete_and_notify(
        self, chat_id: int, telegram_id: int, session: LoginSession
    ) -> None:
        orch = self._orchestrator()
        if not orch:
            return
        try:
            info = await orch.poll_until_settled(session, expect="completing")
        except Exception as exc:
            await self.tg.send_message(
                chat_id,
                __("accounts.error", error=str(exc)[:240]),
                reply_markup=otp_keyboard(),
            )
            return
        await self._notify_complete_result(chat_id, telegram_id, session, info)

    async def _notify_complete_result(
        self,
        chat_id: int,
        telegram_id: int,
        session: LoginSession,
        info: dict,
    ) -> None:
        login = info.get("login")
        account_id = session.get("account_id")
        if login == "done":
            await UserState.clear(self.db, telegram_id)
            await self.tg.send_message(
                chat_id,
                __("accounts.done", account_id=account_id),
                reply_markup=main_keyboard(),
            )
            return
        if login == "failed":
            await self.tg.send_message(
                chat_id,
                __(
                    "accounts.failed",
                    account_id=account_id,
                    error=info.get("conclusion") or info.get("error") or "failed",
                ),
                reply_markup=otp_keyboard(),
            )
            await self.tg.send_message(
                chat_id,
                __("accounts.hint_2fa_or_retry"),
                reply_markup=otp_keyboard(),
            )
            return
        if login == "timeout":
            await self.tg.send_message(
                chat_id,
                __(
                    "accounts.watch_timeout",
                    account_id=account_id,
                    run_id=info.get("run_id") or "-",
                ),
                reply_markup=otp_keyboard(),
            )
            return
        await self.tg.send_message(
            chat_id,
            __(
                "accounts.run_status",
                status=info.get("status") or "-",
                conclusion=info.get("conclusion") or "-",
                url=info.get("html_url") or "",
            ),
            reply_markup=otp_keyboard(),
        )

    def _orchestrator(self) -> LoginOrchestratorService | None:
        gh = self._github()
        if not gh:
            return None
        return LoginOrchestratorService(self.db, gh)

    def _github(self) -> GitHubService | None:
        return make_github(self.config)

    def _scaffold(self):
        return make_scaffold(self.config)

    async def _send_manage_detail(
        self, chat_id: int, user: User, account_id: str
    ) -> bool:
        tid = int(user.get("telegram_id"))
        try:
            row = await AccountService(self.db).require_owned(tid, account_id)
        except AccountConflictError:
            await UserState.set_state(self.db, tid, ST_ACCOUNTS_MENU, {})
            await self.tg.send_message(
                chat_id, __("accounts.menu"), reply_markup=accounts_menu_keyboard()
            )
            return False
        view = row.to_view()
        await UserState.set_state(
            self.db, tid, ST_MANAGE_ACTION, {"account_id": account_id}
        )
        await self.tg.send_message(
            chat_id,
            __(
                "accounts.manage_detail",
                id=view.get("id"),
                label=view.get("label") or account_id,
                role=view.get("role") or "-",
                status=view.get("status") or "-",
                enabled=view.get("enabled"),
                phone=view.get("phone_mask") or "-",
            ),
            reply_markup=manage_actions_keyboard(),
        )
        return True

    async def _reply_github_error(
        self, chat_id: int, exc: GitHubError, *, ctx: dict | None = None
    ) -> None:
        kind = exc.user_message
        if kind == "github_unavailable":
            text = __("accounts.github_unavailable")
        elif kind == "github_unauthorized":
            text = __("accounts.github_unauthorized")
        elif kind == "github_forbidden":
            text = __("accounts.github_forbidden")
        elif kind == "exists":
            text = __("accounts.exists")
        else:
            text = __("accounts.error", error=str(exc)[:240])
        markup = confirm_keyboard() if ctx else accounts_menu_keyboard()
        await self.tg.send_message(chat_id, text, reply_markup=markup)
        if ctx:
            await self.tg.send_message(
                chat_id,
                __(
                    "accounts.retry_confirm",
                    account_id=ctx.get("account_id"),
                    role=ctx.get("role"),
                    phone=ctx.get("phone"),
                ),
                reply_markup=confirm_keyboard(),
            )

    async def open_menu(self, chat_id: int, user: User) -> None:
        await UserState.set_state(
            self.db, int(user.get("telegram_id")), ST_ACCOUNTS_MENU, {}
        )
        await self.tg.send_message(
            chat_id,
            __("accounts.menu"),
            reply_markup=accounts_menu_keyboard(),
        )

    async def cancel(self, chat_id: int, user: User) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        session_id = state.context.get("session_id")
        if session_id:
            session = await LoginSession.find(self.db, session_id)
            if session:
                orch = self._orchestrator()
                if orch:
                    await orch.cancel(session)
        await UserState.clear(self.db, tid)
        await self.tg.send_message(
            chat_id,
            __("accounts.cancelled"),
            reply_markup=main_keyboard(),
        )

    async def handle(self, chat_id: int, user: User, text: str) -> bool:
        """Return True if message was consumed by accounts wizard."""
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        t = (text or "").strip()
        current_preview = str(state.get("state") or "")

        if t in {"/cancel", __("accounts.btn_cancel"), "انصراف"}:
            if current_preview.startswith("accounts_"):
                await self.cancel(chat_id, user)
                return True
            return False

        if t in {__("accounts.btn_back"), "منوی اصلی"} and current_preview in {
            ST_ACCOUNTS_MENU,
            ST_MANAGE_PICK,
            ST_MANAGE_ACTION,
            ST_MANAGE_CONFIRM_LOGOUT,
            ST_MANAGE_CONFIRM_DELETE,
            ST_MANAGE_CONFIRM_ENABLE,
            ST_MANAGE_RENAME,
            ST_MANAGE_ROLE,
            "idle",
        }:
            await UserState.clear(self.db, tid)
            await self.tg.send_message(
                chat_id,
                __("auth.welcome_admin", name=user.display_name),
                reply_markup=main_keyboard(),
            )
            return True

        # Entry from main menu
        if t in {__("menu.btn_accounts"), "اکانت‌ها", "👥 اکانت‌ها"}:
            await self.open_menu(chat_id, user)
            return True

        if not state.is_active:
            return False

        # Allow jumping to other main sections without trapping in accounts menu.
        if _other_main_menu(t):
            await UserState.clear(self.db, tid)
            return False

        current = str(state.get("state") or "")
        if current == ST_ACCOUNTS_MENU:
            await self._menu_choice(chat_id, user, t)
            return True
        if current == ST_ADD_ID:
            await self._add_id(chat_id, user, t)
            return True
        if current == ST_ADD_ROLE:
            await self._add_role(chat_id, user, t)
            return True
        if current == ST_ADD_PHONE:
            await self._add_phone(chat_id, user, t)
            return True
        if current == ST_ADD_CONFIRM:
            await self._add_confirm(chat_id, user, t)
            return True
        if current == ST_LOGIN_ID:
            await self._login_id(chat_id, user, t)
            return True
        if current == ST_LOGIN_PHONE:
            await self._login_phone(chat_id, user, t)
            return True
        if current == ST_LOGIN_CONFIRM:
            await self._login_confirm(chat_id, user, t)
            return True
        if current == ST_AWAIT_OTP:
            await self._await_otp(chat_id, user, t)
            return True
        if current == ST_AWAIT_2FA:
            await self._await_2fa(chat_id, user, t)
            return True
        if current == ST_MANAGE_PICK:
            await self._manage_pick(chat_id, user, t)
            return True
        if current == ST_MANAGE_ACTION:
            await self._manage_action(chat_id, user, t)
            return True
        if current == ST_MANAGE_CONFIRM_LOGOUT:
            await self._manage_confirm_logout(chat_id, user, t)
            return True
        if current == ST_MANAGE_CONFIRM_DELETE:
            await self._manage_confirm_delete(chat_id, user, t)
            return True
        if current == ST_MANAGE_CONFIRM_ENABLE:
            await self._manage_confirm_enable(chat_id, user, t)
            return True
        if current == ST_MANAGE_RENAME:
            await self._manage_rename(chat_id, user, t)
            return True
        if current == ST_MANAGE_ROLE:
            await self._manage_role(chat_id, user, t)
            return True
        return False

    async def _menu_choice(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        if t == __("accounts.btn_list"):
            await self._list(chat_id, user)
            return
        if t == __("accounts.btn_add"):
            if not self.config.github_ready():
                await self.tg.send_message(
                    chat_id,
                    __("accounts.missing_github"),
                    reply_markup=accounts_menu_keyboard(),
                )
                return
            await UserState.set_state(self.db, tid, ST_ADD_ID, {})
            await self.tg.send_message(
                chat_id, __("accounts.ask_id"), reply_markup=accounts_menu_keyboard()
            )
            return
        if t == __("accounts.btn_login"):
            if not self.config.github_ready():
                await self.tg.send_message(
                    chat_id,
                    __("accounts.missing_github"),
                    reply_markup=accounts_menu_keyboard(),
                )
                return
            await UserState.set_state(self.db, tid, ST_LOGIN_ID, {})
            await self.tg.send_message(
                chat_id,
                __("accounts.ask_login_id"),
                reply_markup=accounts_menu_keyboard(),
            )
            return
        if t == __("accounts.btn_manage"):
            await self._start_manage(chat_id, user)
            return
        await self.tg.send_message(
            chat_id, __("accounts.menu"), reply_markup=accounts_menu_keyboard()
        )

    async def _list(self, chat_id: int, user: User) -> None:
        orch = self._orchestrator()
        if not orch:
            await self.tg.send_message(
                chat_id,
                __("accounts.missing_github"),
                reply_markup=accounts_menu_keyboard(),
            )
            return
        try:
            rows = await orch.list_accounts_view(int(user.get("telegram_id")))
        except GitHubError as exc:
            await self.tg.send_message(
                chat_id,
                __("accounts.error", error=str(exc)),
                reply_markup=accounts_menu_keyboard(),
            )
            return
        if not rows:
            await self.tg.send_message(
                chat_id,
                __("accounts.list_empty"),
                reply_markup=accounts_menu_keyboard(),
            )
            return
        lines = [__("accounts.list_header")]
        for row in rows:
            lines.append(
                __(
                    "accounts.list_line",
                    id=row.get("id"),
                    label=row.get("label") or row.get("id"),
                    role=row.get("role") or "-",
                    enabled=row.get("enabled"),
                    status=row.get("status") or "-",
                    phone=row.get("phone_mask") or "-",
                )
            )
        await self.tg.send_message(
            chat_id, "\n".join(lines), reply_markup=accounts_menu_keyboard()
        )

    async def _start_manage(self, chat_id: int, user: User) -> None:
        tid = int(user.get("telegram_id"))
        rows = await AccountService(self.db).list_for_user(tid)
        if not rows:
            await self.tg.send_message(
                chat_id,
                __("accounts.list_empty"),
                reply_markup=accounts_menu_keyboard(),
            )
            return
        ids = [str(r.get("id")) for r in rows if r.get("id")]
        await UserState.set_state(self.db, tid, ST_MANAGE_PICK, {})
        await self.tg.send_message(
            chat_id,
            __("accounts.manage_pick"),
            reply_markup=accounts_pick_keyboard(ids),
        )

    async def _manage_pick(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        if t in _noise_buttons():
            await self.tg.send_message(chat_id, __("accounts.ignore_step"))
            await self._start_manage(chat_id, user)
            return
        aid = validate_account_id(t)
        if not aid:
            await self.tg.send_message(chat_id, __("accounts.invalid_id"))
            await self._start_manage(chat_id, user)
            return
        try:
            await AccountService(self.db).require_owned(tid, aid)
        except AccountConflictError:
            await self.tg.send_message(
                chat_id,
                __("accounts.not_owned", account_id=aid),
                reply_markup=accounts_menu_keyboard(),
            )
            await UserState.set_state(self.db, tid, ST_ACCOUNTS_MENU, {})
            return
        await self._send_manage_detail(chat_id, user, aid)

    async def _manage_action(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        if t == __("accounts.btn_manage_back"):
            await self._start_manage(chat_id, user)
            return
        if t in {__("accounts.btn_enable"), __("accounts.btn_disable")}:
            if not self.config.github_ready():
                await self.tg.send_message(
                    chat_id,
                    __("accounts.missing_github"),
                    reply_markup=manage_actions_keyboard(),
                )
                return
            enabled = t == __("accounts.btn_enable")
            await UserState.set_state(
                self.db,
                tid,
                ST_MANAGE_CONFIRM_ENABLE,
                {"account_id": aid, "enabled": enabled},
            )
            key = "accounts.confirm_enable" if enabled else "accounts.confirm_disable"
            await self.tg.send_message(
                chat_id,
                __(key, account_id=aid),
                reply_markup=confirm_enable_keyboard(enabled=enabled),
            )
            return
        if t == __("accounts.btn_rename"):
            await UserState.set_state(
                self.db, tid, ST_MANAGE_RENAME, {"account_id": aid}
            )
            await self.tg.send_message(
                chat_id,
                __("accounts.ask_rename", account_id=aid),
                reply_markup=rename_keyboard(),
            )
            return
        if t == __("accounts.btn_auto_label"):
            await self._apply_auto_label(chat_id, user, aid)
            return
        if t in {__("accounts.btn_change_role"), __("accounts.btn_vacant_roles")}:
            vacant_only = t == __("accounts.btn_vacant_roles")
            await self._start_role_change(
                chat_id, user, aid, vacant_only=vacant_only
            )
            return
        if t == __("accounts.btn_logout"):
            if not self.config.github_ready():
                await self.tg.send_message(
                    chat_id,
                    __("accounts.missing_github"),
                    reply_markup=manage_actions_keyboard(),
                )
                return
            await UserState.set_state(
                self.db, tid, ST_MANAGE_CONFIRM_LOGOUT, {"account_id": aid}
            )
            await self.tg.send_message(
                chat_id,
                __("accounts.confirm_logout", account_id=aid),
                reply_markup=confirm_logout_keyboard(),
            )
            return
        if t == __("accounts.btn_delete"):
            if not self.config.github_ready():
                await self.tg.send_message(
                    chat_id,
                    __("accounts.missing_github"),
                    reply_markup=manage_actions_keyboard(),
                )
                return
            await UserState.set_state(
                self.db, tid, ST_MANAGE_CONFIRM_DELETE, {"account_id": aid}
            )
            await self.tg.send_message(
                chat_id,
                __("accounts.confirm_delete", account_id=aid),
                reply_markup=confirm_delete_keyboard(),
            )
            return
        await self.tg.send_message(
            chat_id, __("accounts.ignore_step"), reply_markup=manage_actions_keyboard()
        )

    async def _apply_auto_label(self, chat_id: int, user: User, account_id: str) -> None:
        tid = int(user.get("telegram_id"))
        scaffold = self._scaffold()
        if not scaffold:
            await self.tg.send_message(
                chat_id, __("accounts.missing_github"), reply_markup=main_keyboard()
            )
            await UserState.clear(self.db, tid)
            return
        try:
            result = await AccountService(self.db).auto_label(
                tid, account_id, scaffold=scaffold
            )
        except AccountConflictError as exc:
            key = (
                "accounts.invalid_label"
                if exc.code == "invalid_label"
                else "accounts.not_owned"
            )
            await self.tg.send_message(
                chat_id, __(key, account_id=account_id), reply_markup=manage_actions_keyboard()
            )
            return
        except GitHubError as exc:
            await self._reply_github_error(chat_id, exc)
            await self._send_manage_detail(chat_id, user, account_id)
            return
        await self.tg.send_message(
            chat_id,
            __(
                "accounts.rename_done",
                account_id=account_id,
                label=result.get("label"),
            ),
        )
        await self._send_manage_detail(chat_id, user, account_id)

    async def _start_role_change(
        self,
        chat_id: int,
        user: User,
        account_id: str,
        *,
        vacant_only: bool,
    ) -> None:
        tid = int(user.get("telegram_id"))
        if not self.config.github_ready():
            await self.tg.send_message(
                chat_id,
                __("accounts.missing_github"),
                reply_markup=manage_actions_keyboard(),
            )
            return
        try:
            row = await AccountService(self.db).require_owned(tid, account_id)
        except AccountConflictError:
            await self.tg.send_message(
                chat_id,
                __("accounts.not_owned", account_id=account_id),
                reply_markup=accounts_menu_keyboard(),
            )
            return
        vacant = await AccountService(self.db).vacant_roles(
            tid, ignore_account_id=account_id
        )
        vacant_txt = ", ".join(f"<code>{r}</code>" for r in vacant) or "—"
        roles = vacant if vacant_only else list(ROLES)
        if vacant_only and not roles:
            await self.tg.send_message(
                chat_id,
                __("accounts.vacant_none"),
                reply_markup=role_pick_keyboard(list(ROLES), vacant_only=False),
            )
            await UserState.set_state(
                self.db,
                tid,
                ST_MANAGE_ROLE,
                {"account_id": account_id, "vacant_only": False},
            )
            return

        await UserState.set_state(
            self.db,
            tid,
            ST_MANAGE_ROLE,
            {"account_id": account_id, "vacant_only": vacant_only},
        )
        header = (
            __(
                "accounts.vacant_pick",
                account_id=account_id,
            )
            if vacant_only
            else __(
                "accounts.ask_role_change",
                account_id=account_id,
                role=row.get("role") or "-",
                vacant=vacant_txt,
            )
        )
        await self.tg.send_message(
            chat_id,
            header,
            reply_markup=role_pick_keyboard(roles, vacant_only=vacant_only),
        )

    async def _manage_rename(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        if t == __("accounts.btn_manage_back"):
            await self._send_manage_detail(chat_id, user, aid)
            return
        if t == __("accounts.btn_auto_label"):
            await self._apply_auto_label(chat_id, user, aid)
            return
        if t in _noise_buttons() or validate_role(t):
            await self.tg.send_message(
                chat_id,
                __("accounts.ignore_step"),
                reply_markup=rename_keyboard(),
            )
            return
        label = validate_label(t)
        if not label:
            await self.tg.send_message(
                chat_id,
                __("accounts.invalid_label"),
                reply_markup=rename_keyboard(),
            )
            return
        scaffold = self._scaffold()
        if not scaffold:
            await self.tg.send_message(
                chat_id, __("accounts.missing_github"), reply_markup=main_keyboard()
            )
            await UserState.clear(self.db, tid)
            return
        try:
            result = await AccountService(self.db).set_label(
                tid, aid, label, scaffold=scaffold
            )
        except AccountConflictError as exc:
            key = (
                "accounts.invalid_label"
                if exc.code == "invalid_label"
                else "accounts.not_owned"
            )
            await self.tg.send_message(
                chat_id, __(key, account_id=aid), reply_markup=rename_keyboard()
            )
            return
        except GitHubError as exc:
            await self._reply_github_error(chat_id, exc)
            await UserState.set_state(
                self.db, tid, ST_MANAGE_RENAME, {"account_id": aid}
            )
            return
        await self.tg.send_message(
            chat_id,
            __(
                "accounts.rename_done",
                account_id=aid,
                label=result.get("label"),
            ),
        )
        await self._send_manage_detail(chat_id, user, aid)

    async def _manage_role(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        if t == __("accounts.btn_manage_back"):
            await self._send_manage_detail(chat_id, user, aid)
            return
        if t == __("accounts.btn_vacant_roles"):
            await self._start_role_change(chat_id, user, aid, vacant_only=True)
            return
        if t == __("accounts.btn_all_roles"):
            await self._start_role_change(chat_id, user, aid, vacant_only=False)
            return
        role = validate_role(t)
        if not role:
            await self.tg.send_message(
                chat_id,
                __("accounts.invalid_role"),
                reply_markup=role_pick_keyboard(
                    list(ROLES),
                    vacant_only=bool(state.context.get("vacant_only")),
                ),
            )
            return
        scaffold = self._scaffold()
        if not scaffold:
            await self.tg.send_message(
                chat_id, __("accounts.missing_github"), reply_markup=main_keyboard()
            )
            await UserState.clear(self.db, tid)
            return
        try:
            row = await AccountService(self.db).require_owned(tid, aid)
            previous = str(row.get("role") or "-")
            result = await AccountService(self.db).set_role(
                tid, aid, role, scaffold=scaffold, auto_rename=True
            )
        except AccountConflictError as exc:
            key = {
                "invalid_role": "accounts.invalid_role",
                "account_not_owned": "accounts.not_owned",
            }.get(exc.code, "accounts.error")
            await self.tg.send_message(
                chat_id,
                __(key, account_id=aid, error=exc.code),
                reply_markup=manage_actions_keyboard(),
            )
            return
        except GitHubError as exc:
            await self._reply_github_error(chat_id, exc)
            await self._start_role_change(chat_id, user, aid, vacant_only=False)
            return
        await self.tg.send_message(
            chat_id,
            __(
                "accounts.role_done",
                account_id=aid,
                previous=previous,
                role=result.get("role"),
                label=result.get("label"),
            ),
        )
        await self._send_manage_detail(chat_id, user, aid)

    async def _manage_confirm_enable(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        enabled = bool(state.context.get("enabled"))
        expected = (
            __("accounts.btn_confirm_enable")
            if enabled
            else __("accounts.btn_confirm_disable")
        )
        if t != expected:
            await self._send_manage_detail(chat_id, user, aid)
            return

        scaffold = self._scaffold()
        if not scaffold:
            await self.tg.send_message(
                chat_id, __("accounts.missing_github"), reply_markup=main_keyboard()
            )
            await UserState.clear(self.db, tid)
            return
        try:
            await AccountService(self.db).set_enabled(
                tid, aid, enabled=enabled, scaffold=scaffold
            )
        except AccountConflictError:
            await UserState.set_state(self.db, tid, ST_ACCOUNTS_MENU, {})
            await self.tg.send_message(
                chat_id,
                __("accounts.not_owned", account_id=aid),
                reply_markup=accounts_menu_keyboard(),
            )
            return
        except GitHubError as exc:
            await self._reply_github_error(chat_id, exc)
            await self._send_manage_detail(chat_id, user, aid)
            return

        await UserState.set_state(self.db, tid, ST_ACCOUNTS_MENU, {})
        done = "accounts.enable_done" if enabled else "accounts.disable_done"
        await self.tg.send_message(
            chat_id,
            __(done, account_id=aid),
            reply_markup=accounts_menu_keyboard(),
        )

    async def _manage_confirm_logout(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        if t != __("accounts.btn_confirm_logout"):
            await self._send_manage_detail(chat_id, user, aid)
            return

        gh = self._github()
        scaffold = self._scaffold()
        if not gh:
            await self.tg.send_message(
                chat_id, __("accounts.missing_github"), reply_markup=main_keyboard()
            )
            await UserState.clear(self.db, tid)
            return
        try:
            await AccountService(self.db).logout(
                tid, aid, github=gh, scaffold=scaffold
            )
        except AccountConflictError:
            await UserState.set_state(self.db, tid, ST_ACCOUNTS_MENU, {})
            await self.tg.send_message(
                chat_id,
                __("accounts.not_owned", account_id=aid),
                reply_markup=accounts_menu_keyboard(),
            )
            return
        except GitHubError as exc:
            await self._reply_github_error(chat_id, exc)
            await self._send_manage_detail(chat_id, user, aid)
            return

        await UserState.set_state(self.db, tid, ST_ACCOUNTS_MENU, {})
        await self.tg.send_message(
            chat_id,
            __("accounts.logout_done", account_id=aid),
            reply_markup=accounts_menu_keyboard(),
        )

    async def _manage_confirm_delete(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        if t != __("accounts.btn_confirm_delete"):
            await self._send_manage_detail(chat_id, user, aid)
            return

        gh = self._github()
        scaffold = self._scaffold()
        if not gh or not scaffold:
            await self.tg.send_message(
                chat_id, __("accounts.missing_github"), reply_markup=main_keyboard()
            )
            await UserState.clear(self.db, tid)
            return
        try:
            result = await AccountService(self.db).delete(
                tid, aid, github=gh, scaffold=scaffold
            )
        except AccountConflictError:
            await UserState.set_state(self.db, tid, ST_ACCOUNTS_MENU, {})
            await self.tg.send_message(
                chat_id,
                __("accounts.not_owned", account_id=aid),
                reply_markup=accounts_menu_keyboard(),
            )
            return
        except GitHubError as exc:
            await self._reply_github_error(chat_id, exc)
            await UserState.set_state(
                self.db, tid, ST_MANAGE_ACTION, {"account_id": aid}
            )
            return

        await UserState.set_state(self.db, tid, ST_ACCOUNTS_MENU, {})
        gh_err = result.get("github_error") or result.get("secret_error")
        if gh_err:
            await self.tg.send_message(
                chat_id,
                __(
                    "accounts.delete_partial",
                    account_id=aid,
                    error=gh_err,
                ),
                reply_markup=accounts_menu_keyboard(),
            )
        else:
            await self.tg.send_message(
                chat_id,
                __("accounts.delete_done", account_id=aid),
                reply_markup=accounts_menu_keyboard(),
            )

    async def _add_id(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        if t in _noise_buttons():
            await self.tg.send_message(chat_id, __("accounts.ignore_step"))
            await self.tg.send_message(chat_id, __("accounts.ask_id"))
            return
        aid = validate_account_id(t)
        if not aid:
            await self.tg.send_message(chat_id, __("accounts.invalid_id"))
            return
        await UserState.set_state(self.db, tid, ST_ADD_ROLE, {"account_id": aid})
        await self.tg.send_message(
            chat_id, __("accounts.ask_role"), reply_markup=roles_keyboard()
        )

    async def _add_role(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        if t in _noise_buttons():
            await self.tg.send_message(
                chat_id, __("accounts.ignore_step"), reply_markup=roles_keyboard()
            )
            return
        role = validate_role(t)
        if not role:
            await self.tg.send_message(
                chat_id, __("accounts.invalid_role"), reply_markup=roles_keyboard()
            )
            return
        state = await UserState.get_or_idle(self.db, tid)
        ctx = state.context
        ctx["role"] = role
        await UserState.set_state(self.db, tid, ST_ADD_PHONE, ctx)
        await self.tg.send_message(
            chat_id, __("accounts.ask_phone"), reply_markup=accounts_menu_keyboard()
        )

    async def _add_phone(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        if t in _noise_buttons() or validate_role(t):
            await self.tg.send_message(chat_id, __("accounts.ignore_step"))
            await self.tg.send_message(chat_id, __("accounts.ask_phone"))
            return
        phone = validate_phone(t)
        if not phone:
            await self.tg.send_message(chat_id, __("accounts.invalid_phone"))
            return
        state = await UserState.get_or_idle(self.db, tid)
        ctx = state.context
        try:
            await AccountService(self.db).assert_phone_available(
                phone,
                except_account_id=str(ctx.get("account_id") or "") or None,
            )
        except AccountConflictError as exc:
            await self.tg.send_message(
                chat_id,
                __("accounts.phone_taken", account_id=exc.account_id or "-"),
            )
            return
        ctx["phone"] = phone
        await UserState.set_state(self.db, tid, ST_ADD_CONFIRM, ctx)
        await self.tg.send_message(
            chat_id,
            __(
                "accounts.confirm",
                account_id=ctx.get("account_id"),
                role=ctx.get("role"),
                phone=phone,
            ),
            reply_markup=confirm_keyboard(),
        )

    async def _add_confirm(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        ctx = dict(state.context)
        if t != __("accounts.btn_confirm"):
            if t in _noise_buttons():
                await self.tg.send_message(
                    chat_id,
                    __(
                        "accounts.retry_confirm",
                        account_id=ctx.get("account_id"),
                        role=ctx.get("role"),
                        phone=ctx.get("phone"),
                    ),
                    reply_markup=confirm_keyboard(),
                )
                return
            await self.tg.send_message(
                chat_id, __("accounts.menu"), reply_markup=accounts_menu_keyboard()
            )
            await UserState.set_state(self.db, tid, ST_ACCOUNTS_MENU, {})
            return
        orch = self._orchestrator()
        if not orch:
            await self.tg.send_message(
                chat_id, __("accounts.missing_github"), reply_markup=main_keyboard()
            )
            await UserState.clear(self.db, tid)
            return

        await self.tg.send_message(
            chat_id,
            __("accounts.sending", account_id=ctx.get("account_id")),
            reply_markup=otp_keyboard(),
        )
        try:
            session = await orch.start_add(
                account_id=str(ctx.get("account_id")),
                role=str(ctx.get("role")),
                phone=str(ctx.get("phone")),
                created_by=tid,
            )
        except AccountConflictError as exc:
            key = {
                "phone_taken": "accounts.phone_taken",
                "account_owned_by_other": "accounts.owned_by_other",
                "account_not_owned": "accounts.not_owned",
            }.get(exc.code, "accounts.error")
            await UserState.set_state(self.db, tid, ST_ACCOUNTS_MENU, {})
            await self.tg.send_message(
                chat_id,
                __(key, account_id=exc.account_id or "-", error=exc.code),
                reply_markup=accounts_menu_keyboard(),
            )
            return
        except GitHubError as exc:
            await UserState.set_state(self.db, tid, ST_ADD_CONFIRM, ctx)
            await self._reply_github_error(chat_id, exc, ctx=ctx)
            return
        except ValueError:
            await self.tg.send_message(
                chat_id, __("accounts.invalid_phone"), reply_markup=main_keyboard()
            )
            await UserState.clear(self.db, tid)
            return

        await UserState.set_state(
            self.db,
            tid,
            ST_AWAIT_OTP,
            {
                "session_id": session.get("id"),
                "account_id": session.get("account_id"),
            },
        )
        await self.tg.send_message(
            chat_id,
            __(
                "accounts.await_otp",
                account_id=session.get("account_id"),
                phone=session.phone_mask,
                run_id=session.get("github_run_id") or "-",
            ),
            reply_markup=otp_keyboard(),
        )

    async def _login_id(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        aid = validate_account_id(t)
        if not aid:
            await self.tg.send_message(chat_id, __("accounts.invalid_id"))
            return
        await UserState.set_state(self.db, tid, ST_LOGIN_PHONE, {"account_id": aid})
        await self.tg.send_message(chat_id, __("accounts.ask_phone"))

    async def _login_phone(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        phone = validate_phone(t)
        if not phone:
            await self.tg.send_message(chat_id, __("accounts.invalid_phone"))
            return
        state = await UserState.get_or_idle(self.db, tid)
        ctx = state.context
        try:
            await AccountService(self.db).assert_phone_available(
                phone,
                except_account_id=str(ctx.get("account_id") or "") or None,
            )
        except AccountConflictError as exc:
            await self.tg.send_message(
                chat_id,
                __("accounts.phone_taken", account_id=exc.account_id or "-"),
            )
            return
        ctx["phone"] = phone
        await UserState.set_state(self.db, tid, ST_LOGIN_CONFIRM, ctx)
        await self.tg.send_message(
            chat_id,
            __(
                "accounts.confirm_login",
                account_id=ctx.get("account_id"),
                phone=phone,
            ),
            reply_markup=confirm_keyboard(),
        )

    async def _login_confirm(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        if t != __("accounts.btn_confirm"):
            await UserState.set_state(self.db, tid, ST_ACCOUNTS_MENU, {})
            await self.tg.send_message(
                chat_id, __("accounts.menu"), reply_markup=accounts_menu_keyboard()
            )
            return
        state = await UserState.get_or_idle(self.db, tid)
        ctx = state.context
        orch = self._orchestrator()
        if not orch:
            await self.tg.send_message(
                chat_id, __("accounts.missing_github"), reply_markup=main_keyboard()
            )
            await UserState.clear(self.db, tid)
            return
        await self.tg.send_message(
            chat_id,
            __("accounts.sending", account_id=ctx.get("account_id")),
            reply_markup=otp_keyboard(),
        )
        try:
            session = await orch.start_login_existing(
                account_id=str(ctx.get("account_id")),
                phone=str(ctx.get("phone")),
                created_by=tid,
            )
        except AccountConflictError as exc:
            key = {
                "phone_taken": "accounts.phone_taken",
                "account_owned_by_other": "accounts.owned_by_other",
                "account_not_owned": "accounts.not_owned",
            }.get(exc.code, "accounts.error")
            await self.tg.send_message(
                chat_id,
                __(key, account_id=exc.account_id or "-", error=exc.code),
                reply_markup=accounts_menu_keyboard(),
            )
            await UserState.set_state(self.db, tid, ST_ACCOUNTS_MENU, {})
            return
        except ValueError as exc:
            key = (
                "accounts.account_missing"
                if str(exc) == "account_missing"
                else "accounts.invalid_phone"
            )
            await self.tg.send_message(
                chat_id, __(key), reply_markup=accounts_menu_keyboard()
            )
            await UserState.set_state(self.db, tid, ST_ACCOUNTS_MENU, {})
            return
        except GitHubError as exc:
            await UserState.set_state(self.db, tid, ST_LOGIN_CONFIRM, dict(ctx))
            await self._reply_github_error(chat_id, exc, ctx=dict(ctx))
            return

        await UserState.set_state(
            self.db,
            tid,
            ST_AWAIT_OTP,
            {
                "session_id": session.get("id"),
                "account_id": session.get("account_id"),
            },
        )
        await self.tg.send_message(
            chat_id,
            __(
                "accounts.await_otp",
                account_id=session.get("account_id"),
                phone=session.phone_mask,
                run_id=session.get("github_run_id") or "-",
            ),
            reply_markup=otp_keyboard(),
        )

    async def _load_session(self, user: User) -> LoginSession | None:
        state = await UserState.get_or_idle(self.db, int(user.get("telegram_id")))
        sid = state.context.get("session_id")
        if not sid:
            return None
        return await LoginSession.find(self.db, sid)

    async def _await_otp(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        orch = self._orchestrator()
        session = await self._load_session(user)
        if not orch or not session:
            await self.tg.send_message(
                chat_id, __("accounts.no_session"), reply_markup=main_keyboard()
            )
            await UserState.clear(self.db, tid)
            return

        if t == __("accounts.btn_check_run"):
            try:
                info = await orch.refresh_run_status(session)
            except GitHubError as exc:
                await self.tg.send_message(
                    chat_id,
                    __("accounts.error", error=str(exc)),
                    reply_markup=otp_keyboard(),
                )
                return
            if info.get("login") == "done":
                await UserState.clear(self.db, tid)
                await self.tg.send_message(
                    chat_id,
                    __("accounts.done", account_id=session.get("account_id")),
                    reply_markup=main_keyboard(),
                )
                return
            if info.get("login") == "failed":
                await self.tg.send_message(
                    chat_id,
                    __(
                        "accounts.failed",
                        account_id=session.get("account_id"),
                        error=info.get("conclusion") or "failed",
                    ),
                    reply_markup=otp_keyboard(),
                )
                return
            if info.get("login") == "otp_sent":
                await self.tg.send_message(
                    chat_id,
                    __(
                        "accounts.otp_ready",
                        account_id=session.get("account_id"),
                        run_id=info.get("run_id") or "-",
                    ),
                    reply_markup=otp_keyboard(),
                )
                return
            if info.get("login") == "send_failed":
                await self.tg.send_message(
                    chat_id,
                    __(
                        "accounts.failed",
                        account_id=session.get("account_id"),
                        error=info.get("error") or "send_failed",
                    ),
                    reply_markup=otp_keyboard(),
                )
                return
            await self.tg.send_message(
                chat_id,
                __(
                    "accounts.run_status",
                    status=info.get("status") or "-",
                    conclusion=info.get("conclusion") or "-",
                    url=info.get("html_url") or "",
                ),
                reply_markup=otp_keyboard(),
            )
            return

        if t == __("accounts.btn_need_2fa"):
            await UserState.merge_context(
                self.db, tid, {}, state=ST_AWAIT_2FA
            )
            await self.tg.send_message(
                chat_id, __("accounts.ask_2fa"), reply_markup=otp_keyboard()
            )
            return

        try:
            session = await orch.submit_otp(session, t)
            session = await orch.dispatch_complete(session)
        except ValueError:
            await self.tg.send_message(
                chat_id, __("accounts.invalid_otp"), reply_markup=otp_keyboard()
            )
            return
        except GitHubError as exc:
            await self.tg.send_message(
                chat_id,
                __("accounts.error", error=str(exc)),
                reply_markup=otp_keyboard(),
            )
            return

        await UserState.merge_context(
            self.db,
            tid,
            {"session_id": session.get("id"), "account_id": session.get("account_id")},
            state=ST_AWAIT_OTP,
        )
        await self.tg.send_message(
            chat_id,
            __("accounts.otp_saved", account_id=session.get("account_id")),
            reply_markup=otp_keyboard(),
        )
        watch = self._watch_complete_and_notify(chat_id, tid, session)
        if not self._schedule(watch):
            await watch

    async def _await_2fa(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        orch = self._orchestrator()
        session = await self._load_session(user)
        if not orch or not session:
            await self.tg.send_message(
                chat_id, __("accounts.no_session"), reply_markup=main_keyboard()
            )
            await UserState.clear(self.db, tid)
            return
        try:
            session = await orch.submit_2fa(session, t)
            session = await orch.dispatch_complete(session)
        except ValueError:
            await self.tg.send_message(
                chat_id, __("accounts.invalid_2fa"), reply_markup=otp_keyboard()
            )
            return
        except GitHubError as exc:
            await self.tg.send_message(
                chat_id,
                __("accounts.error", error=str(exc)),
                reply_markup=otp_keyboard(),
            )
            return

        await UserState.merge_context(
            self.db,
            tid,
            {"session_id": session.get("id"), "account_id": session.get("account_id")},
            state=ST_AWAIT_OTP,
        )
        await self.tg.send_message(
            chat_id,
            __("accounts.twofa_saved", account_id=session.get("account_id")),
            reply_markup=otp_keyboard(),
        )
        watch = self._watch_complete_and_notify(chat_id, tid, session)
        if not self._schedule(watch):
            await watch
