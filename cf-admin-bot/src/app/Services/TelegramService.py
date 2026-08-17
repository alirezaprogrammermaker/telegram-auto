"""Thin Telegram Bot API client (single place for HTTP)."""
from __future__ import annotations

import json
from typing import Any

from js import console
from workers import fetch


class TelegramService:
    def __init__(self, token: str) -> None:
        self.token = token

    async def api(self, method: str, payload: dict[str, Any] | None = None) -> dict:
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        # workers.fetch expects kwargs (method/headers/body), not a positional RequestInit.
        resp = await fetch(
            url,
            method="POST",
            headers={"content-type": "application/json"},
            body=json.dumps(payload or {}, ensure_ascii=False),
        )
        data = await resp.json()
        if hasattr(data, "to_py"):
            data = data.to_py()
        if not isinstance(data, dict):
            data = {"ok": False, "result": data}
        if not data.get("ok"):
            console.error(f"telegram {method} failed: {data}")
        return data

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: dict | None = None,
        parse_mode: str = "HTML",
    ) -> dict:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self.api("sendMessage", payload)
