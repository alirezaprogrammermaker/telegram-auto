"""Admin panel menu controller — thin router over feature controllers."""
from __future__ import annotations

from app.Http.Controllers.AccountsController import AccountsController
from app.Http.Controllers.OpsController import OpsController
from app.Http.Controllers.PanelController import PanelController
from app.Models.User import User
from app.Models.UserState import UserState
from app.Services.TelegramService import TelegramService
from app.Support.Lang import __
from config.bot import BotConfig
from config.menus import main_keyboard


class AdminController:
    def __init__(self, tg: TelegramService, config: BotConfig, ctx=None) -> None:
        self.tg = tg
        self.config = config
        self.db = config.db
        self.accounts = AccountsController(tg, config, ctx=ctx)
        self.ops = OpsController(tg, config)
        self.panel = PanelController(tg, config)

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

    async def settings(self, chat_id: int) -> None:
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
            lines.append(
                __(
                    "menu.settings_admin_line",
                    label=label,
                    telegram_id=row.get("telegram_id"),
                )
            )
        await self.tg.send_message(
            chat_id,
            "\n".join(lines),
            reply_markup=main_keyboard(),
        )

    async def dispatch_text(self, chat_id: int, user: User, text: str) -> None:
        t = (text or "").strip()

        # Feature wizards first (consume when active / entry buttons).
        if await self.accounts.handle(chat_id, user, t):
            return
        if await self.ops.handle(chat_id, user, t):
            return
        if await self.panel.handle(chat_id, user, t):
            return

        if t in {"/start", "start", "منو", "/menu"}:
            await self.welcome(chat_id, user)
            return
        if t == "/whoami":
            await self.whoami(chat_id, user)
            return
        if t in {__("menu.btn_settings"), "تنظیمات", "/admins", "⚙️ تنظیمات"}:
            await self.settings(chat_id)
            return
        if t in {__("accounts.btn_back"), "منوی اصلی"}:
            await self.welcome(chat_id, user)
            return
        if t == "/help":
            await self.tg.send_message(
                chat_id, __("menu.help"), reply_markup=main_keyboard()
            )
            return

        await self.tg.send_message(
            chat_id, __("menu.unknown"), reply_markup=main_keyboard()
        )
