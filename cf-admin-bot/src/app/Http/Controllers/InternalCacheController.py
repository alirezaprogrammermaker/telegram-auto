"""GHA → Worker: account-cache-admin result notification."""
from __future__ import annotations

import json

from app.Services.TelegramService import TelegramService
from app.Support.BridgeAuth import require_bridge_token
from app.Support.Lang import __
from config.bot import BotConfig
from workers import Response


class InternalCacheController:
    def __init__(self, env) -> None:
        self.config = BotConfig(env)

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

        chat_raw = data.get("notify_chat_id") or data.get("notify_user_id")
        try:
            chat_id = int(chat_raw)
        except (TypeError, ValueError):
            return Response.json({"ok": False, "error": "missing_notify"}, status=400)

        body = self._format(data)
        tg = TelegramService(self.config.telegram_token)
        try:
            await tg.send_message(chat_id, body)
        except Exception as exc:
            return Response.json({"ok": False, "error": str(exc)[:200]}, status=502)
        return Response.json({"ok": True})

    def _format(self, data: dict) -> str:
        action = data.get("action") or "-"
        account_id = data.get("account_id") or "-"
        url = data.get("run_url") or ""
        if not data.get("ok", True):
            return __(
                "cache.report_error",
                account_id=account_id,
                action=action,
                error=data.get("error") or "failed",
                url=url,
            )
        if "queue" in data:
            if "cleared" in data:
                return __(
                    "cache.queue_cleared",
                    account_id=account_id,
                    queue=data.get("queue"),
                    cleared=data.get("cleared"),
                    url=url,
                )
            return __(
                "cache.queue_status",
                account_id=account_id,
                queue=data.get("queue"),
                pending=data.get("pending"),
                url=url,
            )
        dump = data.get("data")
        preview = ""
        if isinstance(dump, dict):
            preview = json.dumps(dump, ensure_ascii=False)[:800]
        return __(
            "cache.dump",
            account_id=account_id,
            action=action,
            exists=data.get("exists"),
            preview=preview or "—",
            url=url,
        )
