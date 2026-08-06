"""Channel forward module — copy/forward new posts to your channel.

Configuration (config/modules.json → modules.channel_forward):
  enabled: bool
  sources: list[str|int]   # @username, t.me links, or channel ids
  destination: str|int     # your channel
  delay_seconds: float     # pause between forwards (anti-flood)
  forward_mode: "forward" | "copy"
  skip_silent: bool
  album_wait_seconds: float
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from telethon import TelegramClient, events, utils
from telethon.errors import FloodWaitError, RPCError
from telethon.tl.types import Channel, Message

from app.base import BaseModule

logger = logging.getLogger(__name__)


def _normalize_ref(value: Any) -> str | int:
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        raise ValueError("empty channel reference")
    if text.startswith("https://t.me/") or text.startswith("http://t.me/"):
        text = text.split("t.me/", 1)[1]
    text = text.split("?")[0].strip("/")
    if text.startswith("@"):
        text = text[1:]
    if text.lstrip("-").isdigit():
        return int(text)
    return text


class ChannelForwardModule(BaseModule):
    name = "channel_forward"

    def __init__(self, client: TelegramClient, config: dict[str, Any]) -> None:
        super().__init__(client, config)
        self.delay = max(0.0, float(config.get("delay_seconds") or 1.5))
        self.mode = str(config.get("forward_mode") or "forward").lower()
        if self.mode not in {"forward", "copy"}:
            self.mode = "forward"
        self.skip_silent = bool(config.get("skip_silent", False))
        self.album_wait = max(0.2, float(config.get("album_wait_seconds") or 1.2))

        raw_sources = config.get("sources") or []
        if not isinstance(raw_sources, list):
            raise ValueError("channel_forward.sources must be a list")
        self._source_refs = [_normalize_ref(s) for s in raw_sources]
        dest = config.get("destination")
        if not dest:
            raise ValueError("channel_forward.destination is required")
        self._dest_ref = _normalize_ref(dest)

        self._source_ids: set[int] = set()
        self._dest_id: int | None = None
        self._dest_entity: Any = None
        self._album_buffers: dict[int, list[Message]] = defaultdict(list)
        self._album_tasks: dict[int, asyncio.Task[None]] = {}
        self._event_builder: events.NewMessage | None = None

    async def start(self) -> None:
        if not self._source_refs:
            raise ValueError(
                "channel_forward.sources is empty — add at least one source channel "
                "in config/modules.json"
            )

        self._dest_entity = await self.client.get_entity(self._dest_ref)
        self._dest_id = utils.get_peer_id(self._dest_entity)
        if not isinstance(self._dest_entity, Channel):
            raise ValueError("destination must be a channel/supergroup")

        resolved_sources: list[Any] = []
        for ref in self._source_refs:
            entity = await self.client.get_entity(ref)
            peer_id = utils.get_peer_id(entity)
            if peer_id == self._dest_id:
                logger.warning("Skipping source %s — same as destination", ref)
                continue
            if not isinstance(entity, Channel):
                logger.warning("Skipping source %s — not a channel", ref)
                continue
            self._source_ids.add(peer_id)
            resolved_sources.append(entity)
            logger.info("Watching source: %s (id=%s)", _entity_label(entity), peer_id)

        if not resolved_sources:
            raise ValueError("No valid source channels resolved")

        logger.info(
            "Forwarding → %s (id=%s) mode=%s delay=%ss",
            _entity_label(self._dest_entity),
            self._dest_id,
            self.mode,
            self.delay,
        )

        self._event_builder = events.NewMessage(chats=resolved_sources)
        self.client.add_event_handler(self._on_new_message, self._event_builder)

    async def stop(self) -> None:
        if self._event_builder is not None:
            self.client.remove_event_handler(self._on_new_message, self._event_builder)
            self._event_builder = None

        for task in list(self._album_tasks.values()):
            task.cancel()
        self._album_tasks.clear()
        self._album_buffers.clear()

    async def _on_new_message(self, event: events.NewMessage.Event) -> None:
        try:
            await self._handle(event)
        except FloodWaitError as exc:
            logger.warning("channel_forward FloodWait %ss", exc.seconds)
            await asyncio.sleep(exc.seconds)
        except RPCError as exc:
            logger.error("channel_forward RPC error: %s", exc)
        except Exception:
            logger.exception("channel_forward unexpected error")

    async def _handle(self, event: events.NewMessage.Event) -> None:
        message = event.message
        if not isinstance(message, Message):
            return
        if message.action is not None:
            return  # service messages
        if self.skip_silent and getattr(message, "silent", False):
            return

        chat_id = event.chat_id
        if chat_id is None or chat_id not in self._source_ids:
            return
        if chat_id == self._dest_id:
            return

        grouped_id = message.grouped_id
        if grouped_id:
            self._album_buffers[grouped_id].append(message)
            prev = self._album_tasks.get(grouped_id)
            if prev and not prev.done():
                prev.cancel()
            self._album_tasks[grouped_id] = asyncio.create_task(
                self._flush_album_later(grouped_id)
            )
            return

        await self._forward_messages([message])

    async def _flush_album_later(self, grouped_id: int) -> None:
        try:
            await asyncio.sleep(self.album_wait)
            messages = self._album_buffers.pop(grouped_id, [])
            self._album_tasks.pop(grouped_id, None)
            if messages:
                messages.sort(key=lambda m: m.id)
                await self._forward_messages(messages)
        except asyncio.CancelledError:
            return

    async def _forward_messages(self, messages: list[Message]) -> None:
        assert self._dest_entity is not None
        if not messages:
            return

        ids = [m.id for m in messages]

        try:
            if self.mode == "copy":
                first = messages[0]
                if len(messages) == 1 and not first.media:
                    await self.client.send_message(
                        self._dest_entity,
                        first.message or "",
                    )
                else:
                    await self.client.send_file(
                        self._dest_entity,
                        file=messages if len(messages) > 1 else first,
                        caption=first.message or "",
                    )
            else:
                await self.client.forward_messages(
                    entity=self._dest_entity,
                    messages=messages,
                    from_peer=messages[0].chat_id,
                )
        except FloodWaitError:
            raise
        except Exception:
            logger.exception("Batch forward failed for ids=%s — trying one-by-one", ids)
            for msg in messages:
                await self.client.forward_messages(
                    entity=self._dest_entity,
                    messages=msg,
                    from_peer=msg.chat_id,
                )
                if self.delay:
                    await asyncio.sleep(self.delay)
            return

        logger.info(
            "Forwarded %s msg(s) ids=%s from chat=%s",
            len(messages),
            ids,
            messages[0].chat_id,
        )
        if self.delay:
            await asyncio.sleep(self.delay)


def _entity_label(entity: Any) -> str:
    username = getattr(entity, "username", None)
    title = getattr(entity, "title", None)
    if username:
        return f"@{username}"
    if title:
        return str(title)
    return str(utils.get_peer_id(entity))
