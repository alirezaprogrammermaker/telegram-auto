"""Channel forward module — multi-route delivery with filters, schedule, and sync."""
from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from datetime import datetime, time as dt_time
from typing import Any
from zoneinfo import ZoneInfo

from telethon import TelegramClient, events, utils
from telethon.errors import FloodWaitError, RPCError
from telethon.tl.types import Channel, Message

from app.base import BaseModule
from app.notify import notify_admins
from app.stats import StatsStore
from modules.channel_forward.catchup import catch_up_routes
from modules.channel_forward.dedup import DedupStore
from modules.channel_forward.delivery import DeliveryEngine
from modules.channel_forward.queue import PublishQueue
from modules.channel_forward.refs import display_ref, entity_label
from modules.channel_forward.route_config import (
    ResolvedRoute,
    migrate_routes,
    resolve_route,
)
from modules.channel_forward.state import ForwardStateStore

logger = logging.getLogger(__name__)


def _parse_admin_ids(raw: Any) -> set[int]:
    if not raw:
        return set()
    items = raw if isinstance(raw, (list, tuple, set)) else str(raw).replace(";", ",").split(",")
    out: set[int] = set()
    for item in items:
        text = str(item).strip()
        if text.lstrip("-").isdigit():
            out.add(int(text))
    return out


class ChannelForwardModule(BaseModule):
    name = "channel_forward"

    def __init__(self, client: TelegramClient, config: dict[str, Any]) -> None:
        super().__init__(client, config)
        self.delay = max(0.0, float(config.get("delay_seconds") or 1.5))
        self.delay_jitter = max(0.0, float(config.get("delay_jitter_seconds") or 0.0))
        self.default_mode = str(config.get("forward_mode") or "copy").lower()
        if self.default_mode not in {"forward", "copy"}:
            self.default_mode = "copy"
        self.skip_silent = bool(config.get("skip_silent", False))
        # Cross-DC / GHA latency can delay later album parts; 1.2s was too short
        # and caused single-photo publishes. Reconcile from history on flush too.
        self.album_wait = max(0.5, float(config.get("album_wait_seconds") or 2.5))
        # Production-safe default: do not silently join channels from shared config.
        # Admin /forward add still joins intentionally (passes auto_join=True there).
        self.auto_join = bool(config.get("auto_join", False))
        self.catch_up_enabled = bool(config.get("catch_up_enabled", True))
        self.catch_up_limit = max(1, int(config.get("catch_up_limit") or 50))
        self.dry_run = bool(config.get("dry_run", False))

        alerts_cfg = config.get("alerts") if isinstance(config.get("alerts"), dict) else {}
        self.alerts_enabled = bool(alerts_cfg.get("enabled", True))
        self.alert_admin_ids = _parse_admin_ids(
            os.environ.get("ADMIN_IDS") or alerts_cfg.get("admin_ids")
        )

        report_cfg = config.get("daily_report") if isinstance(config.get("daily_report"), dict) else {}
        self.daily_report_enabled = bool(report_cfg.get("enabled", False))
        self.daily_report_hour = str(report_cfg.get("hour") or "23:00")
        self.daily_report_tz = str(report_cfg.get("timezone") or "Asia/Tehran")

        self._route_defs = migrate_routes(config)
        self._routes_by_source: dict[int, list[ResolvedRoute]] = defaultdict(list)
        self._routes_by_key: dict[str, ResolvedRoute] = {}
        self._album_buffers: dict[tuple[int, int], list[Message]] = defaultdict(list)
        self._album_tasks: dict[tuple[int, int], asyncio.Task[None]] = {}
        self._new_msg_builder: events.NewMessage | None = None
        self._edit_builder: events.MessageEdited | None = None
        self._delete_builder: events.MessageDeleted | None = None
        self._queue = PublishQueue()
        self._stats = StatsStore()
        self._state = ForwardStateStore()
        self._dedup = DedupStore()
        self._engine: DeliveryEngine | None = None
        self._publisher_task: asyncio.Task[None] | None = None
        self._report_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._all_resolved: list[ResolvedRoute] = []

    def _build_engine(self) -> DeliveryEngine:
        async def alert_fn(text: str) -> None:
            if self.alerts_enabled and self.alert_admin_ids:
                await notify_admins(self.client, self.alert_admin_ids, text)

        return DeliveryEngine(
            self.client,
            queue=self._queue,
            stats=self._stats,
            state=self._state,
            dedup=self._dedup,
            delay_seconds=self.delay,
            delay_jitter=self.delay_jitter,
            dry_run=self.dry_run,
            alert_fn=alert_fn if self.alerts_enabled else None,
        )

    async def start(self) -> None:
        if not self._route_defs:
            logger.warning(
                "channel_forward: no routes — idle (add with /forward add)"
            )
            return

        watch_entities: list[Any] = []
        self._all_resolved = []
        for route in self._route_defs:
            if not route.get("enabled", True):
                continue
            try:
                resolved_list = await resolve_route(
                    self.client,
                    route,
                    default_mode=self.default_mode,
                    auto_join=self.auto_join,
                )
            except Exception as exc:
                logger.error(
                    "Skipping route %s: %s",
                    route.get("source"),
                    exc,
                )
                if self.alerts_enabled and self.alert_admin_ids:
                    await notify_admins(
                        self.client,
                        self.alert_admin_ids,
                        f"⚠️ مسیر `{display_ref(route.get('source'))}` لود نشد: {exc}",
                    )
                continue

            for resolved in resolved_list:
                if resolved.source_id == resolved.dest_id:
                    logger.warning(
                        "Skipping route %s → same destination",
                        display_ref(resolved.source_ref),
                    )
                    continue
                self._routes_by_source[resolved.source_id].append(resolved)
                self._routes_by_key[resolved.route_key] = resolved
                if resolved.source_entity not in watch_entities:
                    watch_entities.append(resolved.source_entity)
                self._all_resolved.append(resolved)
                logger.info(
                    "Route: %s → %s (mode=%s schedule=%s paused=%s)",
                    entity_label(resolved.source_entity),
                    entity_label(resolved.dest_entity),
                    resolved.mode,
                    "ON" if resolved.schedule.enabled else "OFF",
                    resolved.paused,
                )

        if not self._routes_by_source:
            raise ValueError("No valid forward routes resolved")

        self._engine = self._build_engine()

        self._new_msg_builder = events.NewMessage(chats=watch_entities)
        self.client.add_event_handler(self._on_new_message, self._new_msg_builder)

        source_ids = list(self._routes_by_source.keys())
        self._edit_builder = events.MessageEdited(chats=watch_entities)
        self.client.add_event_handler(self._on_message_edited, self._edit_builder)
        self._delete_builder = events.MessageDeleted(chats=source_ids)
        self.client.add_event_handler(self._on_message_deleted, self._delete_builder)

        self._stopping = False
        self._publisher_task = asyncio.create_task(self._publisher_loop())
        if self.daily_report_enabled:
            self._report_task = asyncio.create_task(self._daily_report_loop())

        if self.catch_up_enabled and self._engine:
            await catch_up_routes(
                self.client,
                self._all_resolved,
                self._engine,
                self._state,
                limit=self.catch_up_limit,
            )

        logger.info(
            "channel_forward watching %s source(s), %s route(s); queue=%s dry_run=%s",
            len(self._routes_by_source),
            len(self._all_resolved),
            self._queue.pending_count(),
            self.dry_run,
        )

    async def stop(self) -> None:
        self._stopping = True
        for task in (self._publisher_task, self._report_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._publisher_task = None
        self._report_task = None

        for builder, handler in (
            (self._new_msg_builder, self._on_new_message),
            (self._edit_builder, self._on_message_edited),
            (self._delete_builder, self._on_message_deleted),
        ):
            if builder is not None:
                self.client.remove_event_handler(handler, builder)
        self._new_msg_builder = None
        self._edit_builder = None
        self._delete_builder = None

        for task in list(self._album_tasks.values()):
            task.cancel()
        self._album_tasks.clear()
        self._album_buffers.clear()
        self._routes_by_source.clear()
        self._routes_by_key.clear()
        self._all_resolved.clear()

    async def _publisher_loop(self) -> None:
        while not self._stopping:
            try:
                await self._flush_queue_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("schedule publisher loop error")
            await asyncio.sleep(20)

    async def _daily_report_loop(self) -> None:
        sent_for_day: str | None = None
        while not self._stopping:
            try:
                tz = ZoneInfo(self.daily_report_tz)
            except Exception:
                tz = ZoneInfo("Asia/Tehran")
            now = datetime.now(tz)
            try:
                hour_s, minute_s = self.daily_report_hour.split(":", 1)
                target = dt_time(int(hour_s), int(minute_s))
            except (ValueError, TypeError):
                target = dt_time(23, 0)
            day_key = now.date().isoformat()
            if now.time() >= target and sent_for_day != day_key:
                text = self._stats.summary(days=1)
                if self.alert_admin_ids:
                    await notify_admins(
                        self.client,
                        self.alert_admin_ids,
                        f"📊 گزارش روزانه\n{text}",
                    )
                sent_for_day = day_key
            await asyncio.sleep(60)

    async def _flush_queue_once(self) -> None:
        if self._engine is None:
            return
        for item in self._queue.list_pending():
            route = self._routes_by_key.get(str(item.get("route_key")))
            if route is None or route.paused:
                continue
            if not route.schedule.is_open():
                continue
            try:
                ids = [int(x) for x in (item.get("message_ids") or [])]
                fetched = await self.client.get_messages(route.source_entity, ids=ids)
                messages = [m for m in fetched if isinstance(m, Message)]
                if not messages:
                    self._queue.mark_failed(str(item["id"]), "messages missing")
                    continue
                messages.sort(key=lambda m: m.id)
                ok = await self._engine.process_messages(messages, route, from_queue=True)
                if ok:
                    self._queue.mark_done(str(item["id"]))
            except Exception as exc:
                logger.exception("failed publishing queued item %s", item.get("id"))
                self._queue.mark_failed(str(item["id"]), str(exc))

    async def _on_new_message(self, event: events.NewMessage.Event) -> None:
        try:
            await self._handle_new(event)
        except FloodWaitError as exc:
            logger.warning("channel_forward FloodWait %ss", exc.seconds)
            await asyncio.sleep(exc.seconds)
        except RPCError as exc:
            logger.error("channel_forward RPC error: %s", exc)
        except Exception:
            logger.exception("channel_forward unexpected error")

    async def _handle_new(self, event: events.NewMessage.Event) -> None:
        message = event.message
        if not isinstance(message, Message):
            return
        if message.action is not None:
            return
        if self.skip_silent and getattr(message, "silent", False):
            return

        chat_id = event.chat_id
        if chat_id is None:
            return
        routes = self._routes_by_source.get(chat_id) or []
        routes = [r for r in routes if r.dest_id != chat_id]
        if not routes:
            return

        grouped_id = message.grouped_id
        if grouped_id:
            key = (chat_id, int(grouped_id))
            buf = self._album_buffers[key]
            if not any(m.id == message.id for m in buf):
                buf.append(message)
            prev = self._album_tasks.get(key)
            if prev and not prev.done():
                prev.cancel()
            self._album_tasks[key] = asyncio.create_task(self._flush_album_later(key, routes))
            return

        await self._deliver_to_routes([message], routes)

    async def _complete_album(
        self,
        chat_id: int,
        grouped_id: int,
        messages: list[Message],
    ) -> list[Message]:
        """Fill missing album parts from history (timer may fire before all arrive)."""
        by_id = {m.id: m for m in messages if getattr(m, "id", None)}
        if not by_id:
            return []
        lo = min(by_id)
        try:
            # Telegram albums are contiguous and at most 10 items.
            fetched = await self.client.get_messages(chat_id, min_id=lo - 1, limit=10)
            for m in fetched:
                if (
                    isinstance(m, Message)
                    and getattr(m, "grouped_id", None) == grouped_id
                    and m.id
                ):
                    by_id[m.id] = m
        except Exception:
            logger.exception(
                "album reconcile failed chat=%s grouped=%s",
                chat_id,
                grouped_id,
            )
        completed = sorted(by_id.values(), key=lambda m: m.id)
        if len(completed) != len(messages):
            logger.info(
                "Album reconciled chat=%s grouped=%s %s→%s msg(s)",
                chat_id,
                grouped_id,
                len(messages),
                len(completed),
            )
        return completed

    async def _flush_album_later(
        self,
        key: tuple[int, int],
        routes: list[ResolvedRoute],
    ) -> None:
        try:
            await asyncio.sleep(self.album_wait)
            messages = self._album_buffers.pop(key, [])
            self._album_tasks.pop(key, None)
            if not messages:
                return
            chat_id, grouped_id = key
            messages = await self._complete_album(chat_id, grouped_id, messages)
            if not messages:
                return
            await self._deliver_to_routes(messages, routes)
        except asyncio.CancelledError:
            return

    async def _deliver_to_routes(
        self,
        messages: list[Message],
        routes: list[ResolvedRoute],
    ) -> None:
        if self._engine is None:
            return
        for route in routes:
            await self._engine.process_messages(messages, route, from_queue=False)

    async def _on_message_edited(self, event: events.MessageEdited.Event) -> None:
        if self._engine is None or self.dry_run:
            return
        message = event.message
        if not isinstance(message, Message):
            return
        chat_id = event.chat_id
        if chat_id is None:
            return
        for route in self._routes_by_source.get(chat_id) or []:
            if not route.delivery.sync_edits:
                continue
            dest_id = self._state.dest_for_source(route.route_key, message.id)
            if dest_id is None:
                continue
            try:
                text = apply_text_filter_safe(message, route)
                await self.client.edit_message(route.dest_entity, dest_id, text)
            except Exception:
                logger.debug("edit sync failed route=%s", route.route_key, exc_info=True)

    async def _on_message_deleted(self, event: events.MessageDeleted.Event) -> None:
        if self._engine is None or self.dry_run:
            return
        chat_id = event.chat_id
        if chat_id is None:
            return
        for msg_id in event.deleted_ids or []:
            for route in self._routes_by_source.get(chat_id) or []:
                if not route.delivery.sync_deletes:
                    continue
                dest_id = self._state.dest_for_source(route.route_key, int(msg_id))
                if dest_id is None:
                    continue
                try:
                    await self.client.delete_messages(route.dest_entity, dest_id)
                    self._state.remove_mapping(route.route_key, int(msg_id))
                except Exception:
                    logger.debug("delete sync failed route=%s", route.route_key, exc_info=True)


def apply_text_filter_safe(message: Message, route: ResolvedRoute) -> str:
    from modules.channel_forward.filters import apply_text_filter

    raw = message.message or ""
    if route.text_filter.is_active():
        return apply_text_filter(raw, route.text_filter, message.entities)
    return raw


# Backward-compatible re-exports for admin commands
from modules.channel_forward.refs import (  # noqa: E402
    can_post_to_channel,
    display_ref,
    ensure_can_post,
    ensure_joined,
    normalize_ref,
)
from modules.channel_forward.route_config import migrate_routes  # noqa: E402
