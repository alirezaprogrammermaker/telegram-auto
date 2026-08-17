"""Authentication / role promotion (Laravel Auth-ish service)."""
from __future__ import annotations

from app.Models.User import User
from config.bot import BotConfig


class AuthService:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.db = config.db

    async def resolve_user(
        self,
        *,
        telegram_id: int,
        chat_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> User:
        await User.ensure_schema(self.db)
        user = await User.upsert_from_telegram(
            self.db,
            telegram_id=telegram_id,
            chat_id=chat_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        if (
            telegram_id in self.config.bootstrap_admin_ids
            and not user.is_admin
        ):
            user = await user.promote_to_admin(self.db)
        return user

    def password_matches(self, text: str) -> bool:
        expected = self.config.admin_password
        return bool(expected) and text == expected

    async def attempt_password_login(self, user: User, text: str) -> User | None:
        if not self.password_matches(text):
            return None
        return await user.promote_to_admin(self.db)
