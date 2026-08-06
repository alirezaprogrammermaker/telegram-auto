"""Channel forward module — route each source channel to its own destination.

Configuration (config/modules.json → modules.channel_forward):
  enabled: bool
  routes: [
    {
      "source": "@from_channel",
      "destination": "@to_channel",
      "enabled": true,
      "forward_mode": "copy" | "forward"   # optional override
    }
  ]
  delay_seconds: float
  forward_mode: "forward" | "copy"   # default for routes without override
  skip_silent: bool
  album_wait_seconds: float

Legacy (auto-migrated):
  sources: [...] + destination: "..."  → one route per source to same dest
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from telethon import TelegramClient, events, utils
from telethon.errors import (
    ChannelPrivateError,
    FloodWaitError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    RPCError,
    UserAlreadyParticipantError,
    UserNotParticipantError,
)
from telethon.tl.functions.channels import JoinChannelRequest, GetParticipantRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import (
    Channel,
    ChannelParticipantAdmin,
    ChannelParticipantCreator,
    Message,
)

from app.base import BaseModule
from app.progress import ProgressMessenger
from app.stats import StatsStore
from modules.channel_forward.access import normalize_visibility
from modules.channel_forward.filters import TextFilterConfig, apply_text_filter
from modules.channel_forward.queue import PublishQueue
from modules.channel_forward.schedule import ScheduleConfig

logger = logging.getLogger(__name__)


def normalize_ref(value: Any) -> str | int:
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


def display_ref(value: Any) -> str:
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    if not text:
        return text
    if text.startswith("@") or text.lstrip("-").isdigit() or "t.me/" in text:
        return text if text.startswith("@") or "t.me/" in text or text.startswith("-") else f"@{text}"
    return f"@{text}"


def _invite_hash(value: Any) -> str | None:
    text = str(value).strip()
    if "joinchat/" in text:
        return text.split("joinchat/", 1)[1].split("?")[0].strip("/")
    if "/+" in text:
        return text.split("/+", 1)[1].split("?")[0].strip("/")
    if text.startswith("+"):
        return text[1:]
    return None


async def can_post_to_channel(client: TelegramClient, channel: Any) -> tuple[bool, str]:
    """Return (ok, reason) — whether the logged-in account can post in channel."""
    if not isinstance(channel, Channel):
        return False, "مقصد کانال/سوپرگروه نیست"

    if getattr(channel, "creator", False):
        return True, "owner"

    me = await client.get_me()
    try:
        result = await client(GetParticipantRequest(channel, me))
    except UserNotParticipantError:
        return False, "عضو کانال مقصد نیستی"
    except RPCError as exc:
        return False, f"خطا در بررسی دسترسی: {exc.__class__.__name__}"

    participant = result.participant
    is_broadcast = bool(getattr(channel, "broadcast", False))

    if isinstance(participant, ChannelParticipantCreator):
        return True, "owner"

    if isinstance(participant, ChannelParticipantAdmin):
        rights = participant.admin_rights
        if not is_broadcast:
            return True, "group-admin"
        if rights is None:
            return False, "ادمین هستی ولی حق ارسال مشخص نیست"
        if getattr(rights, "post_messages", False):
            return True, "admin:post_messages"
        return False, "ادمین هستی ولی حق Post Messages نداری"

    if not is_broadcast:
        return True, "group-member"
    return False, "فقط عضو عادی هستی؛ برای ارسال باید ادمین با حق پست باشی"


async def ensure_joined(
    client: TelegramClient,
    ref: Any,
    progress: ProgressMessenger | None = None,
    *,
    label: str = "کانال",
) -> tuple[Any, str]:
    """Join public/invite channel if needed. Returns (entity, status)."""
    shown = display_ref(ref)
    if progress:
        await progress.step(f"بررسی عضویت {label}: `{shown}`")

    invite = _invite_hash(ref)
    if invite:
        if progress:
            await progress.step(f"لینک دعوت تشخیص داده شد — تلاش برای جوین `{shown}`")
        try:
            updates = await client(ImportChatInviteRequest(invite))
            entity = None
            chats = getattr(updates, "chats", None) or []
            if chats:
                entity = chats[0]
            if entity is None:
                entity = await client.get_entity(normalize_ref(ref))
            if progress:
                await progress.step(f"جوین شدم به {label}: `{shown}`")
            return entity, "joined_invite"
        except UserAlreadyParticipantError:
            entity = await client.get_entity(normalize_ref(ref))
            if progress:
                await progress.step(f"از قبل عضو {label} بودم: `{shown}`")
            return entity, "already"
        except (InviteHashInvalidError, InviteHashExpiredError) as exc:
            raise ValueError(f"لینک دعوت نامعتبر/منقضی است: `{shown}`") from exc
        except FloodWaitError:
            raise
        except RPCError as exc:
            raise ValueError(f"جوین با دعوت ناموفق: {exc.__class__.__name__}") from exc

    try:
        entity = await client.get_entity(normalize_ref(ref))
    except (ValueError, ChannelPrivateError) as exc:
        raise ValueError(
            f"کانال `{shown}` پیدا نشد یا خصوصی است. اگر خصوصی است لینک دعوت بده."
        ) from exc

    if not isinstance(entity, Channel):
        raise ValueError(f"`{shown}` کانال نیست")

    me = await client.get_me()
    try:
        await client(GetParticipantRequest(entity, me))
        if progress:
            await progress.step(f"از قبل عضو {label} هستم: `{shown}`")
        return entity, "already"
    except UserNotParticipantError:
        pass
    except RPCError:
        # Some channels hide participants; try join anyway
        pass

    if progress:
        await progress.step(f"عضو نیستم — جوین به {label}: `{shown}`")

    try:
        await client(JoinChannelRequest(entity))
    except UserAlreadyParticipantError:
        if progress:
            await progress.step(f"از قبل عضو {label} بودم: `{shown}`")
        return entity, "already"
    except ChannelPrivateError as exc:
        raise ValueError(
            f"کانال `{shown}` خصوصی است و بدون دعوت نمی‌شود جوین شد."
        ) from exc
    except FloodWaitError:
        raise
    except RPCError as exc:
        raise ValueError(
            f"نتوانستم به `{shown}` جوین شوم: {exc.__class__.__name__}"
        ) from exc

    if progress:
        await progress.step(f"جوین شدم به {label}: `{shown}`")
    return entity, "joined"


async def ensure_can_post(
    client: TelegramClient,
    dest_ref: Any,
    progress: ProgressMessenger | None = None,
    *,
    auto_join: bool = True,
) -> tuple[Any, str]:
    """Join (optional) + verify post rights on destination."""
    if progress:
        await progress.step(f"بررسی کانال مقصد: `{display_ref(dest_ref)}`")

    if auto_join:
        entity, _join_status = await ensure_joined(
            client,
            dest_ref,
            progress,
            label="مقصد",
        )
    else:
        entity = await client.get_entity(normalize_ref(dest_ref))

    if progress:
        await progress.step("بررسی حق ارسال پست در مقصد")

    ok, reason = await can_post_to_channel(client, entity)
    if not ok:
        raise ValueError(
            f"در مقصد `{display_ref(dest_ref)}` نمی‌توانی پست بگذاری ({reason}). "
            "اکانت را ادمین کانال مقصد کن و حق Post Messages را بده."
        )
    if progress:
        await progress.step(f"حق پست تأیید شد ({reason})")
    return entity, reason


def migrate_routes(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return routes list; migrate legacy sources+destination if needed."""
    raw_routes = config.get("routes")
    if isinstance(raw_routes, list) and raw_routes:
        cleaned: list[dict[str, Any]] = []
        for item in raw_routes:
            if not isinstance(item, dict):
                continue
            source = item.get("source") or item.get("from")
            dest = item.get("destination") or item.get("to")
            if not source or not dest:
                continue
            cleaned.append(
                {
                    "source": source,
                    "destination": dest,
                    "enabled": bool(item.get("enabled", True)),
                    "forward_mode": item.get("forward_mode"),
                    "filter": TextFilterConfig.from_dict(item.get("filter")).to_dict(),
                    "schedule": ScheduleConfig.from_dict(item.get("schedule")).to_dict(),
                    "owner_id": item.get("owner_id"),
                    # legacy routes without owner stay visible to all admins
                    "visibility": (
                        "public"
                        if item.get("owner_id") in (None, "")
                        else normalize_visibility(item.get("visibility"))
                    ),
                }
            )
        return cleaned

    # Legacy single-destination model
    sources = config.get("sources") or []
    dest = config.get("destination")
    if dest and isinstance(sources, list):
        return [
            {
                "source": src,
                "destination": dest,
                "enabled": True,
                "forward_mode": None,
                "filter": TextFilterConfig().to_dict(),
                "schedule": ScheduleConfig().to_dict(),
                "owner_id": None,
                "visibility": "public",
            }
            for src in sources
            if src
        ]
    return []


@dataclass
class ResolvedRoute:
    source_ref: str | int
    dest_ref: str | int
    source_id: int
    dest_id: int
    source_entity: Any
    dest_entity: Any
    mode: str
    text_filter: TextFilterConfig
    schedule: ScheduleConfig
    route_key: str


class ChannelForwardModule(BaseModule):
    name = "channel_forward"

    def __init__(self, client: TelegramClient, config: dict[str, Any]) -> None:
        super().__init__(client, config)
        self.delay = max(0.0, float(config.get("delay_seconds") or 1.5))
        self.default_mode = str(config.get("forward_mode") or "copy").lower()
        if self.default_mode not in {"forward", "copy"}:
            self.default_mode = "copy"
        self.skip_silent = bool(config.get("skip_silent", False))
        self.album_wait = max(0.2, float(config.get("album_wait_seconds") or 1.2))

        self._route_defs = migrate_routes(config)
        self._routes_by_source: dict[int, ResolvedRoute] = {}
        self._routes_by_key: dict[str, ResolvedRoute] = {}
        self._album_buffers: dict[tuple[int, int], list[Message]] = defaultdict(list)
        self._album_tasks: dict[tuple[int, int], asyncio.Task[None]] = {}
        self._event_builder: events.NewMessage | None = None
        self._queue = PublishQueue()
        self._stats = StatsStore()
        self._publisher_task: asyncio.Task[None] | None = None
        self._stopping = False

    async def start(self) -> None:
        if not self._route_defs:
            raise ValueError(
                "channel_forward.routes is empty — add routes with "
                "`/forward add <source> <destination>`"
            )

        watch_entities: list[Any] = []
        for route in self._route_defs:
            if not route.get("enabled", True):
                continue
            try:
                resolved = await self._resolve_route(route)
            except Exception as exc:
                logger.error(
                    "Skipping route %s → %s: %s",
                    route.get("source"),
                    route.get("destination"),
                    exc,
                )
                continue

            if resolved.source_id == resolved.dest_id:
                logger.warning(
                    "Skipping route %s → same as destination",
                    display_ref(resolved.source_ref),
                )
                continue

            self._routes_by_source[resolved.source_id] = resolved
            self._routes_by_key[resolved.route_key] = resolved
            watch_entities.append(resolved.source_entity)
            logger.info(
                "Route: %s → %s (mode=%s schedule=%s)",
                _entity_label(resolved.source_entity),
                _entity_label(resolved.dest_entity),
                resolved.mode,
                "ON" if resolved.schedule.enabled else "OFF",
            )

        if not self._routes_by_source:
            raise ValueError("No valid forward routes resolved")

        self._event_builder = events.NewMessage(chats=watch_entities)
        self.client.add_event_handler(self._on_new_message, self._event_builder)
        self._stopping = False
        self._publisher_task = asyncio.create_task(self._publisher_loop())
        logger.info(
            "channel_forward watching %s route(s); queue=%s",
            len(self._routes_by_source),
            self._queue.pending_count(),
        )

    async def _resolve_route(
        self,
        route: dict[str, Any],
        progress: ProgressMessenger | None = None,
    ) -> ResolvedRoute:
        source_raw = route["source"]
        dest_raw = route["destination"]
        mode = str(route.get("forward_mode") or self.default_mode).lower()
        if mode not in {"forward", "copy"}:
            mode = self.default_mode

        if progress:
            await progress.step(f"بررسی کانال مبدأ: `{display_ref(source_raw)}`")

        source_entity, join_status = await ensure_joined(
            self.client,
            source_raw,
            progress,
            label="مبدأ",
        )
        if not isinstance(source_entity, Channel):
            raise ValueError(f"source is not a channel: {source_raw}")
        logger.info(
            "Source %s join-status=%s",
            display_ref(source_raw),
            join_status,
        )

        dest_entity, post_reason = await ensure_can_post(
            self.client,
            dest_raw,
            progress,
            auto_join=True,
        )
        logger.info(
            "Destination %s post-check OK (%s)",
            display_ref(dest_raw),
            post_reason,
        )

        return ResolvedRoute(
            source_ref=normalize_ref(source_raw),
            dest_ref=normalize_ref(dest_raw),
            source_id=utils.get_peer_id(source_entity),
            dest_id=utils.get_peer_id(dest_entity),
            source_entity=source_entity,
            dest_entity=dest_entity,
            mode=mode,
            text_filter=TextFilterConfig.from_dict(route.get("filter")),
            schedule=ScheduleConfig.from_dict(route.get("schedule")),
            route_key=display_ref(source_raw),
        )

    async def stop(self) -> None:
        self._stopping = True
        if self._publisher_task is not None:
            self._publisher_task.cancel()
            try:
                await self._publisher_task
            except asyncio.CancelledError:
                pass
            self._publisher_task = None

        if self._event_builder is not None:
            self.client.remove_event_handler(self._on_new_message, self._event_builder)
            self._event_builder = None

        for task in list(self._album_tasks.values()):
            task.cancel()
        self._album_tasks.clear()
        self._album_buffers.clear()
        self._routes_by_source.clear()
        self._routes_by_key.clear()

    async def _publisher_loop(self) -> None:
        while not self._stopping:
            try:
                await self._flush_queue_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("schedule publisher loop error")
            await asyncio.sleep(20)

    async def _flush_queue_once(self) -> None:
        for item in self._queue.list_pending():
            route = self._routes_by_key.get(str(item.get("route_key")))
            if route is None:
                # route removed/disabled
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
                await self._deliver_messages(messages, route, from_queue=True)
                self._queue.mark_done(str(item["id"]))
                self._stats.incr("published_scheduled", route=route.route_key)
            except Exception as exc:
                logger.exception("failed publishing queued item %s", item.get("id"))
                self._queue.mark_failed(str(item["id"]), str(exc))

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
            return
        if self.skip_silent and getattr(message, "silent", False):
            return

        chat_id = event.chat_id
        if chat_id is None:
            return
        route = self._routes_by_source.get(chat_id)
        if route is None:
            return
        if chat_id == route.dest_id:
            return

        grouped_id = message.grouped_id
        if grouped_id:
            key = (chat_id, int(grouped_id))
            self._album_buffers[key].append(message)
            prev = self._album_tasks.get(key)
            if prev and not prev.done():
                prev.cancel()
            self._album_tasks[key] = asyncio.create_task(self._flush_album_later(key))
            return

        await self._forward_messages([message], route)

    async def _flush_album_later(self, key: tuple[int, int]) -> None:
        try:
            await asyncio.sleep(self.album_wait)
            messages = self._album_buffers.pop(key, [])
            self._album_tasks.pop(key, None)
            if not messages:
                return
            messages.sort(key=lambda m: m.id)
            route = self._routes_by_source.get(key[0])
            if route is None:
                return
            await self._forward_messages(messages, route)
        except asyncio.CancelledError:
            return

    async def _forward_messages(
        self,
        messages: list[Message],
        route: ResolvedRoute,
    ) -> None:
        if not messages:
            return

        first = messages[0]
        blocked = route.text_filter.find_blocked_word(first.message or "")
        if blocked:
            logger.info(
                "Blocked route=%s word=%r ids=%s",
                route.route_key,
                blocked,
                [m.id for m in messages],
            )
            self._stats.incr("blocked", route=route.route_key)
            return

        if route.schedule.enabled and not route.schedule.is_open():
            item_id = self._queue.add(
                route_key=route.route_key,
                source_id=route.source_id,
                dest_id=route.dest_id,
                message_ids=[m.id for m in messages],
                mode=route.mode,
                filter_cfg=route.text_filter.to_dict(),
            )
            logger.info(
                "Queued for schedule route=%s item=%s ids=%s",
                route.route_key,
                item_id,
                [m.id for m in messages],
            )
            self._stats.incr("queued", route=route.route_key)
            return

        await self._deliver_messages(messages, route, from_queue=False)

    async def _deliver_messages(
        self,
        messages: list[Message],
        route: ResolvedRoute,
        *,
        from_queue: bool,
    ) -> None:
        ids = [m.id for m in messages]
        dest = route.dest_entity
        text_filter = route.text_filter
        use_filter = text_filter.is_active()
        use_copy = route.mode == "copy" or use_filter

        try:
            if use_copy:
                first = messages[0]
                raw_text = first.message or ""
                text = (
                    apply_text_filter(raw_text, text_filter, first.entities)
                    if use_filter
                    else raw_text
                )

                if len(messages) == 1 and not first.media:
                    if text:
                        await self.client.send_message(dest, text)
                    elif not use_filter:
                        await self.client.send_message(dest, raw_text or "")
                else:
                    await self.client.send_file(
                        dest,
                        file=messages if len(messages) > 1 else first,
                        caption=text,
                    )
                if use_filter:
                    self._stats.incr("filtered_copy", route=route.route_key)
            else:
                await self.client.forward_messages(
                    entity=dest,
                    messages=messages,
                    from_peer=messages[0].chat_id,
                )
        except FloodWaitError:
            raise
        except Exception:
            logger.exception(
                "Batch forward failed ids=%s route=%s→%s — one-by-one",
                ids,
                route.source_id,
                route.dest_id,
            )
            for msg in messages:
                await self.client.forward_messages(
                    entity=dest,
                    messages=msg,
                    from_peer=msg.chat_id,
                )
                if self.delay:
                    await asyncio.sleep(self.delay)
            if not from_queue:
                self._stats.incr("forwarded", route=route.route_key)
            return

        logger.info(
            "Forwarded %s msg(s) ids=%s  %s → %s filter=%s queued_origin=%s",
            len(messages),
            ids,
            route.source_id,
            route.dest_id,
            use_filter,
            from_queue,
        )
        if not from_queue:
            self._stats.incr("forwarded", route=route.route_key)
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
