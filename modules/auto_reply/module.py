"""Auto-reply to private messages (optional module)."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, RPCError

from app.base import BaseModule

logger = logging.getLogger(__name__)


class AutoReplyModule(BaseModule):
    name = "auto_reply"

    def __init__(self, client: TelegramClient, config: dict[str, Any]) -> None:
        super().__init__(client, config)
        self.reply_text = str(config.get("reply_text") or "سلام! پیام‌ات رسید ✓")
        self.cooldown = float(config.get("cooldown_seconds") or 30)
        self.whitelist = {int(x) for x in (config.get("whitelist") or []) if str(x).lstrip("-").isdigit()}
        self.allow_saved = bool(config.get("allow_saved_messages", True))
        self.skip_media_only = bool(config.get("skip_media_only", True))
        self._me_id: int | None = None
        self._last_reply_at: dict[int, float] = {}
        self._event_builder: events.NewMessage | None = None

    async def start(self) -> None:
        me = await self.client.get_me()
        self._me_id = me.id

        def _is_private(event: events.NewMessage.Event) -> bool:
            return bool(event.is_private)

        self._event_builder = events.NewMessage(func=_is_private)
        self.client.add_event_handler(self._on_message, self._event_builder)
        logger.info(
            "auto_reply ready (cooldown=%ss, whitelist=%s)",
            self.cooldown,
            sorted(self.whitelist) if self.whitelist else "all",
        )

    async def stop(self) -> None:
        if self._event_builder is not None:
            self.client.remove_event_handler(self._on_message, self._event_builder)
            self._event_builder = None

    async def _on_message(self, event: events.NewMessage.Event) -> None:
        try:
            await self._handle(event)
        except FloodWaitError as exc:
            logger.warning("auto_reply FloodWait %ss — sleeping", exc.seconds)
            await asyncio.sleep(exc.seconds)
        except RPCError as exc:
            logger.error("auto_reply RPC error: %s", exc)
        except Exception:
            logger.exception("auto_reply unexpected error")

    async def _handle(self, event: events.NewMessage.Event) -> None:
        assert self._me_id is not None
        text = (event.raw_text or "").strip()

        if text == self.reply_text:
            return
        if self.skip_media_only and not text:
            return

        chat_id = event.chat_id
        if chat_id is None:
            return

        if event.out:
            if not self.allow_saved or chat_id != self._me_id:
                return
            peer_key = self._me_id
        else:
            sender = await event.get_sender()
            if getattr(sender, "bot", False):
                return
            sender_id = getattr(sender, "id", None)
            if self.whitelist and sender_id not in self.whitelist:
                return
            peer_key = int(sender_id or chat_id)

        now = time.monotonic()
        last = self._last_reply_at.get(peer_key, 0.0)
        if now - last < self.cooldown:
            logger.debug("auto_reply cooldown active for %s", peer_key)
            return

        await event.reply(self.reply_text)
        self._last_reply_at[peer_key] = now
        where = "Saved Messages" if event.out else f"user:{peer_key}"
        logger.info("auto_reply → %s (%r)", where, text[:80])
