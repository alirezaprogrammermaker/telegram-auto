"""GHA → Worker: pool-admin result notification."""
from __future__ import annotations

from app.Services.TelegramService import TelegramService
from app.Support.BridgeAuth import require_bridge_token
from app.Support.Lang import __
from config.bot import BotConfig
from workers import Response


class InternalPoolController:
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
            return Response.json(
                {"ok": False, "error": str(exc)[:200]}, status=502
            )
        return Response.json({"ok": True})

    def _format(self, data: dict) -> str:
        action = data.get("action") or "-"
        if not data.get("ok", True):
            return __(
                "pool.report_error",
                action=action,
                error=data.get("error") or "failed",
                url=data.get("run_url") or "",
            )

        counts = data.get("counts") or {}
        counts_txt = " · ".join(
            f"{k}={v}" for k, v in counts.items() if k != "total"
        )
        if action == "status":
            return __(
                "pool.report_status",
                total=counts.get("total", 0),
                counts=counts_txt or "-",
                url=data.get("run_url") or "",
            )
        if action == "list":
            items = data.get("items") or []
            lines = []
            for row in items[:20]:
                lines.append(
                    f"• <code>{row.get('ref')}</code> [{row.get('status')}]"
                )
            listing = "\n".join(lines) if lines else "—"
            return __(
                "pool.report_list",
                filter=data.get("status_filter") or "all",
                listing=listing,
                counts=counts_txt or "-",
                url=data.get("run_url") or "",
            )
        if action in {"approve", "reject"}:
            item = data.get("item") or {}
            return __(
                "pool.report_mutate",
                action=action,
                ref=item.get("ref") or "-",
                status=item.get("status") or "-",
                counts=counts_txt or "-",
                url=data.get("run_url") or "",
            )
        return __(
            "pool.report_generic",
            action=action,
            url=data.get("run_url") or "",
        )
