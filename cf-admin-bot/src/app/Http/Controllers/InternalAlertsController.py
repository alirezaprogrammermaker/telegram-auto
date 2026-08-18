"""GHA/runner → Worker: FloodWait / circuit alerts to account owner."""
from __future__ import annotations

from app.Models.Account import Account
from app.Models.User import User
from app.Services.TelegramService import TelegramService
from app.Support.BridgeAuth import require_bridge_token
from app.Support.Lang import __
from config.bot import BotConfig
from workers import Response


class InternalAlertsController:
    def __init__(self, env) -> None:
        self.config = BotConfig(env)
        self.db = self.config.db

    async def handle(self, request) -> Response:
        denied = require_bridge_token(request, self.config)
        if denied is not None:
            return denied

        try:
            data = await request.json()
            if hasattr(data, "to_py"):
                data = data.to_py()
        except Exception:
            return Response.json({"ok": False, "error": "bad_json"}, status=400)

        if not isinstance(data, dict):
            return Response.json({"ok": False, "error": "bad_json"}, status=400)

        account_id = str(data.get("account_id") or "").strip().lower()
        message = str(data.get("message") or data.get("text") or "").strip()
        severity = str(data.get("severity") or "warning").strip().lower()
        if not account_id or not message:
            return Response.json(
                {"ok": False, "error": "missing_fields"}, status=400
            )

        row = await Account.find(self.db, account_id)
        chat_id = None
        if row and int(row.get("user_id") or 0):
            owner = await User.find(self.db, int(row.get("user_id")))
            if owner:
                chat_id = int(owner.get("chat_id") or owner.get("telegram_id") or 0)
        if not chat_id:
            # Fallback: notify bootstrap admins' telegram ids if present in D1 as users
            chat_id = int(row.get("user_id") or 0) if row else 0
        if not chat_id:
            return Response.json(
                {"ok": False, "error": "owner_unknown"}, status=404
            )

        body = __(
            "alerts.flood",
            account_id=account_id,
            severity=severity,
            message=message[:500],
        )
        tg = TelegramService(self.config.telegram_token)
        try:
            await tg.send_message(chat_id, body)
        except Exception as exc:
            return Response.json(
                {"ok": False, "error": str(exc)[:200]}, status=502
            )
        return Response.json({"ok": True, "notified": chat_id})
