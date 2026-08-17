"""Webhook orchestrator (Laravel Controller style)."""
from __future__ import annotations

from js import console

from app.Http.Controllers.AdminController import AdminController
from app.Http.Controllers.GuestController import GuestController
from app.Services.AuthService import AuthService
from app.Services.TelegramService import TelegramService
from app.Support.Lang import __
from config.bot import BotConfig
from config.menus import main_keyboard
from workers import Response


class WebhookController:
    def __init__(self, env) -> None:
        self.config = BotConfig(env)
        self.auth = AuthService(self.config)
        self.tg = TelegramService(self.config.telegram_token)

    async def handle(self, request) -> Response:
        if not self.config.telegram_token:
            console.error("TELEGRAM_BOT_TOKEN missing")
            return Response.json(
                {"ok": False, "error": __("error.no_token")}, status=500
            )

        secret = self.config.webhook_secret
        if secret:
            hdr = request.headers.get("X-Telegram-Bot-Api-Secret-Token") or ""
            if hdr != secret:
                return Response.json(
                    {"ok": False, "error": __("error.unauthorized")}, status=401
                )

        try:
            update = await request.json()
            if hasattr(update, "to_py"):
                update = update.to_py()
        except Exception as exc:
            console.error(f"bad json: {exc}")
            return Response.json(
                {"ok": False, "error": __("error.bad_json")}, status=400
            )

        try:
            await self._dispatch(update if isinstance(update, dict) else {})
        except Exception as exc:
            console.error(f"handler error: {exc}")

        return Response.json({"ok": True})

    async def _dispatch(self, update: dict) -> None:
        message = update.get("message") or update.get("edited_message")
        if not isinstance(message, dict):
            return

        chat = message.get("chat") or {}
        from_user = message.get("from") or {}
        chat_id = int(chat.get("id") or 0)
        user_id = int(from_user.get("id") or 0)
        text = str(message.get("text") or "")

        user = await self.auth.resolve_user(
            telegram_id=user_id,
            chat_id=chat_id,
            username=str(from_user["username"]) if from_user.get("username") else None,
            first_name=str(from_user["first_name"]) if from_user.get("first_name") else None,
            last_name=str(from_user["last_name"]) if from_user.get("last_name") else None,
        )

        promoted = await self.auth.attempt_password_login(user, text)
        if promoted is not None:
            await self.tg.send_message(
                chat_id,
                __("auth.promoted"),
                reply_markup=main_keyboard(),
            )
            return

        guest = GuestController(self.tg)
        admin = AdminController(self.tg, self.config)

        if not user.is_admin:
            t = text.strip()
            if t in {"/start", "start", "/help"}:
                await guest.start(chat_id)
                return
            if t == "/whoami":
                await guest.whoami(chat_id, user)
                return
            await guest.denied(chat_id)
            return

        await admin.dispatch_text(chat_id, user, text)
