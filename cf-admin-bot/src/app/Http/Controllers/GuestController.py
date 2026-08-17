"""Guest (non-admin) replies."""
from __future__ import annotations

from app.Models.User import User
from app.Services.TelegramService import TelegramService
from app.Support.Lang import __
from config.menus import guest_keyboard


class GuestController:
    def __init__(self, tg: TelegramService) -> None:
        self.tg = tg

    async def start(self, chat_id: int) -> None:
        await self.tg.send_message(
            chat_id,
            __("auth.welcome_guest", chat_id=chat_id),
            reply_markup=guest_keyboard(),
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
            reply_markup=guest_keyboard(),
        )

    async def denied(self, chat_id: int) -> None:
        await self.tg.send_message(
            chat_id,
            __("auth.denied"),
            reply_markup=guest_keyboard(),
        )
