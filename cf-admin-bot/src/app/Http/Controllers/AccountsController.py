"""Accounts menu + login wizard (conversation state machine)."""
from __future__ import annotations

from app.Models.LoginSession import LoginSession
from app.Models.User import User
from app.Models.UserState import UserState
from app.Services.AccountScaffoldService import (
    validate_account_id,
    validate_phone,
    validate_role,
)
from app.Services.GitHubService import GitHubError, GitHubService
from app.Services.LoginOrchestratorService import LoginOrchestratorService
from app.Services.TelegramService import TelegramService
from app.Support.Lang import __
from config.bot import BotConfig
from config.menus import (
    accounts_menu_keyboard,
    confirm_keyboard,
    main_keyboard,
    otp_keyboard,
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


class AccountsController:
    def __init__(self, tg: TelegramService, config: BotConfig) -> None:
        self.tg = tg
        self.config = config
        self.db = config.db

    def _orchestrator(self) -> LoginOrchestratorService | None:
        if not self.config.github_ready():
            return None
        gh = GitHubService(
            self.config.github_token,
            self.config.github_repo,
            branch=self.config.github_branch,
        )
        return LoginOrchestratorService(self.db, gh)

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

        if t in {"/cancel", __("accounts.btn_cancel"), "انصراف"}:
            if state.is_active or t == "/cancel":
                await self.cancel(chat_id, user)
                return True

        if t in {__("accounts.btn_back"), "منوی اصلی"} and str(
            state.get("state")
        ) in {ST_ACCOUNTS_MENU, "idle"}:
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
        return False

    async def _menu_choice(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        if t == __("accounts.btn_list"):
            await self._list(chat_id)
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
        await self.tg.send_message(
            chat_id, __("accounts.menu"), reply_markup=accounts_menu_keyboard()
        )

    async def _list(self, chat_id: int) -> None:
        orch = self._orchestrator()
        if not orch:
            await self.tg.send_message(
                chat_id,
                __("accounts.missing_github"),
                reply_markup=accounts_menu_keyboard(),
            )
            return
        try:
            rows = await orch.list_accounts_view()
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
                    enabled=row.get("enabled"),
                    status=row.get("status") or "-",
                    phone=row.get("phone_mask") or "-",
                )
            )
        await self.tg.send_message(
            chat_id, "\n".join(lines), reply_markup=accounts_menu_keyboard()
        )

    async def _add_id(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
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
        phone = validate_phone(t)
        if not phone:
            await self.tg.send_message(chat_id, __("accounts.invalid_phone"))
            return
        state = await UserState.get_or_idle(self.db, tid)
        ctx = state.context
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
        if t != __("accounts.btn_confirm"):
            await self.tg.send_message(
                chat_id, __("accounts.menu"), reply_markup=accounts_menu_keyboard()
            )
            await UserState.set_state(
                self.db, int(user.get("telegram_id")), ST_ACCOUNTS_MENU, {}
            )
            return
        tid = int(user.get("telegram_id"))
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
            session = await orch.start_add(
                account_id=str(ctx.get("account_id")),
                role=str(ctx.get("role")),
                phone=str(ctx.get("phone")),
                created_by=tid,
            )
        except GitHubError as exc:
            msg = str(exc)
            key = "accounts.exists" if "already exists" in msg else "accounts.error"
            await self.tg.send_message(
                chat_id,
                __(key, error=msg) if key == "accounts.error" else __(key),
                reply_markup=accounts_menu_keyboard(),
            )
            await UserState.set_state(self.db, tid, ST_ACCOUNTS_MENU, {})
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
            await self.tg.send_message(
                chat_id,
                __("accounts.error", error=str(exc)),
                reply_markup=accounts_menu_keyboard(),
            )
            await UserState.set_state(self.db, tid, ST_ACCOUNTS_MENU, {})
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
