"""Collect group invite links from directory channels — never joins target groups."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from telethon import TelegramClient, events
from telethon.tl.types import Message

from app.base import BaseModule
from app.metrics_catalog import Discovery
from app.paths import account_id, data_path, ensure_data_dir
from app.telemetry import incr
from modules.channel_forward.refs import display_ref, ensure_joined
from modules.group_pool.pool import GroupPool, extract_links_from_text, utc_now

logger = logging.getLogger(__name__)


class LinkHarvestModule(BaseModule):
    name = "link_harvest"

    def __init__(self, client: TelegramClient, config: dict[str, Any]) -> None:
        super().__init__(client, config)
        self.directories = [
            str(x).strip()
            for x in (config.get("directories") or [])
            if str(x).strip()
        ]
        self.catch_up_limit = max(0, int(config.get("catch_up_limit") or 40))
        # Joining directory channels only (to read). Never joins harvested group links.
        self.join_directories = bool(config.get("join_directories", True))
        self.paused = bool(config.get("paused", False))
        self.pool = GroupPool()
        self._entities: list[Any] = []
        self._exclude: set[str] = set()
        self._builder: events.NewMessage | None = None
        self._raw_path = data_path("raw_links.jsonl")

    def _append_raw_log(self, row: dict[str, Any]) -> None:
        ensure_data_dir()
        with self._raw_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    async def start(self) -> None:
        if not self.directories:
            logger.warning("link_harvest: no directories — idle (use /harvest add)")
            return

        watch: list[Any] = []
        for ref in self.directories[:5]:  # hard cap per collector
            try:
                entity, _status = await ensure_joined(
                    self.client,
                    ref,
                    None,
                    label="لینکدونی",
                    auto_join=self.join_directories,
                )
                watch.append(entity)
                shown = display_ref(ref)
                self._exclude.add(str(shown).lstrip("@").lower())
                uname = getattr(entity, "username", None)
                if uname:
                    self._exclude.add(str(uname).lower())
                logger.info("link_harvest watching directory %s", shown)
            except Exception as exc:
                logger.error("link_harvest skip directory %s: %s", ref, exc)

        if not watch:
            logger.warning("link_harvest: no valid directories — idle")
            return

        self._entities = watch
        if self.catch_up_limit > 0:
            await self._catch_up()

        self._builder = events.NewMessage(chats=watch)
        self.client.add_event_handler(self._on_message, self._builder)
        logger.info(
            "link_harvest active dirs=%s catch_up=%s paused=%s",
            len(watch),
            self.catch_up_limit,
            self.paused,
        )

    async def stop(self) -> None:
        if self._builder:
            self.client.remove_event_handler(self._on_message, self._builder)
            self._builder = None

    async def _catch_up(self) -> None:
        for entity in self._entities:
            try:
                messages = await self.client.get_messages(entity, limit=self.catch_up_limit)
            except Exception as exc:
                logger.warning("link_harvest catch-up failed: %s", exc)
                continue
            # oldest → newest
            for msg in reversed(list(messages or [])):
                if isinstance(msg, Message):
                    await self._ingest(msg, entity)

    async def _on_message(self, event: events.NewMessage.Event) -> None:
        if self.paused:
            return
        msg = event.message
        if not isinstance(msg, Message):
            return
        await self._ingest(msg, await event.get_chat())

    async def _ingest(self, msg: Message, chat: Any) -> None:
        if self.paused:
            return
        text = (msg.message or "") + "\n" + (msg.text or "")
        # Also scan button URLs when present
        buttons = getattr(msg, "buttons", None) or []
        for row in buttons:
            for btn in row:
                url = getattr(btn, "url", None)
                if url:
                    text += f"\n{url}"

        source = display_ref(getattr(chat, "username", None) or getattr(chat, "id", "dir"))
        links = extract_links_from_text(text, exclude_usernames=self._exclude)
        if not links:
            return

        for ref in links:
            try:
                status, is_new = self.pool.upsert_raw(
                    ref,
                    source_channel=source,
                    message_id=int(msg.id) if msg.id else None,
                    collector_account=account_id(),
                )
                self._append_raw_log(
                    {
                        "ref": ref,
                        "status": status,
                        "is_new": is_new,
                        "source": source,
                        "message_id": msg.id,
                        "at": utc_now(),
                        "account": account_id(),
                    }
                )
                if is_new:
                    incr(Discovery.LINKS_HARVESTED)
                    logger.info("link_harvest new raw link %s from %s", ref, source)
            except Exception as exc:
                logger.debug("link_harvest skip %s: %s", ref, exc)
