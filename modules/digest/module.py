"""Daily digest summaries for admins."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time as dt_time
from typing import Any
from zoneinfo import ZoneInfo

from telethon import TelegramClient, events

from app.base import BaseModule
from app.notify import notify_admins
from app.stats import StatsStore
from modules.channel_forward.queue import PublishQueue

logger = logging.getLogger(__name__)


def _parse_ids(raw: Any) -> set[int]:
    if not raw:
        return set()
    import os

    env = os.environ.get("ADMIN_IDS", "")
    parts = list(raw) if isinstance(raw, (list, tuple, set)) else str(raw).replace(";", ",").split(",")
    if env:
        parts.extend(str(env).replace(";", ",").split(","))
    out: set[int] = set()
    for item in parts:
        text = str(item).strip()
        if text.lstrip("-").isdigit():
            out.add(int(text))
    return out


class DigestModule(BaseModule):
    name = "digest"

    def __init__(self, client: TelegramClient, config: dict[str, Any]) -> None:
        super().__init__(client, config)
        self.hour = str(config.get("hour") or "23:00")
        self.timezone = str(config.get("timezone") or "Asia/Tehran")
        self.admin_ids = _parse_ids(config.get("admin_ids"))
        self._stats = StatsStore(timezone=self.timezone)
        self._queue = PublishQueue()
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._builder: events.NewMessage | None = None
        self._sent_day: str | None = None

    async def start(self) -> None:
        if not self.admin_ids:
            logger.warning("digest: no admin_ids configured — module idle")
        self._stopping = False
        self._task = asyncio.create_task(self._loop())
        self._builder = events.NewMessage(incoming=True, func=lambda e: e.is_private)
        self.client.add_event_handler(self._on_command, self._builder)

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._builder:
            self.client.remove_event_handler(self._on_command, self._builder)
            self._builder = None

    async def _on_command(self, event: events.NewMessage.Event) -> None:
        text = (event.raw_text or "").strip().lower()
        if text not in {"/digest", "/digest now", "digest"}:
            return
        sender = await event.get_sender()
        if sender is None or sender.id not in self.admin_ids:
            return
        await event.reply(await self._build_digest())

    async def _build_digest(self) -> str:
        pending = self._queue.pending_count()
        stats = self._stats.summary(days=1)
        return f"📰 Digest\n────────────\n{stats}\n────────────\nصف pending: {pending}"

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                tz = ZoneInfo(self.timezone)
            except Exception:
                tz = ZoneInfo("Asia/Tehran")
            now = datetime.now(tz)
            try:
                h, m = self.hour.split(":", 1)
                target = dt_time(int(h), int(m))
            except (ValueError, TypeError):
                target = dt_time(23, 0)
            day = now.date().isoformat()
            if now.time() >= target and self._sent_day != day and self.admin_ids:
                body = await self._build_digest()
                await notify_admins(self.client, self.admin_ids, body)
                self._sent_day = day
            await asyncio.sleep(60)
