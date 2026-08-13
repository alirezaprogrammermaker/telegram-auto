"""Unified message delivery pipeline for channel_forward."""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Callable, Awaitable

from telethon import TelegramClient
from telethon.errors import FloodWaitError, MediaCaptionTooLongError, MessageTooLongError
from telethon.tl.types import Message, KeyboardButtonUrl, ReplyInlineMarkup

from app.stats import StatsStore
from modules.channel_forward.dedup import DedupStore, content_fingerprint
from modules.channel_forward.filters import TextFilterConfig, apply_text_filter, matches_content_rules
from modules.channel_forward.media_filter import media_allowed
from modules.channel_forward.queue import PublishQueue
from modules.channel_forward.route_config import ResolvedRoute
from modules.channel_forward.state import ForwardStateStore

logger = logging.getLogger(__name__)

AlertFn = Callable[[str], Awaitable[None]]

# Telegram hard limits (UTF-16 code units ≈ chars for Persian/ASCII).
MEDIA_CAPTION_LIMIT = 1024
TEXT_MESSAGE_LIMIT = 4096


def clip_telegram_text(text: str, limit: int) -> str:
    """Trim text to Telegram length limits, keeping a short ellipsis marker."""
    if not text or len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1].rstrip() + "…"


class DeliveryEngine:
    def __init__(
        self,
        client: TelegramClient,
        *,
        queue: PublishQueue,
        stats: StatsStore,
        state: ForwardStateStore,
        dedup: DedupStore,
        delay_seconds: float = 1.5,
        delay_jitter: float = 0.0,
        dry_run: bool = False,
        alert_fn: AlertFn | None = None,
    ) -> None:
        self.client = client
        self.queue = queue
        self.stats = stats
        self.state = state
        self.dedup = dedup
        self.delay_seconds = max(0.0, delay_seconds)
        self.delay_jitter = max(0.0, delay_jitter)
        self.dry_run = dry_run
        self._alert = alert_fn

    async def _notify(self, text: str) -> None:
        if self._alert:
            try:
                await self._alert(text)
            except Exception:
                logger.debug("alert delivery failed", exc_info=True)

    async def process_messages(
        self,
        messages: list[Message],
        route: ResolvedRoute,
        *,
        from_queue: bool = False,
    ) -> bool:
        if not messages or route.paused:
            return False

        first = messages[0]
        text_body = first.message or ""

        blocked = route.text_filter.find_blocked_word(text_body)
        if blocked:
            logger.info("Blocked route=%s word=%r", route.route_key, blocked)
            self.stats.incr("blocked", route=route.route_key)
            return False

        if not matches_content_rules(text_body, route.text_filter):
            logger.info("Skipped by allow/regex route=%s", route.route_key)
            self.stats.incr("filtered_skip", route=route.route_key)
            return False

        if not media_allowed(first, route.media_filter):
            logger.info("Skipped by media filter route=%s", route.route_key)
            self.stats.incr("media_skipped", route=route.route_key)
            return False

        fp = content_fingerprint(first)
        if route.dedup.enabled and self.dedup.is_duplicate(
            route.route_key, fp, route.dedup.window_hours
        ):
            logger.info("Dedup skip route=%s", route.route_key)
            self.stats.incr("dedup_skipped", route=route.route_key)
            return False

        if route.schedule.enabled and not route.schedule.is_open() and not from_queue:
            self.queue.add(
                route_key=route.route_key,
                source_id=route.source_id,
                dest_id=route.dest_id,
                message_ids=[m.id for m in messages],
                mode=route.mode,
                filter_cfg=route.text_filter.to_dict(),
            )
            self.stats.incr("queued", route=route.route_key)
            return False

        if self.dry_run:
            logger.info(
                "DRY-RUN would forward %s ids=%s route=%s",
                len(messages),
                [m.id for m in messages],
                route.route_key,
            )
            self.stats.incr("dry_run", route=route.route_key)
            return True

        ok = await self._deliver(messages, route, from_queue=from_queue)
        if ok and route.dedup.enabled:
            self.dedup.remember(route.route_key, fp)
        return ok

    async def _deliver(
        self,
        messages: list[Message],
        route: ResolvedRoute,
        *,
        from_queue: bool,
    ) -> bool:
        ids = [m.id for m in messages]
        dest = route.dest_entity
        text_filter = route.text_filter
        delivery = route.delivery
        use_filter = text_filter.is_active() or bool(
            delivery.media_prefix or delivery.media_suffix
        )
        use_copy = route.mode == "copy" or use_filter

        try:
            sent_ids: list[int] = []
            if use_copy:
                first = messages[0]
                # Caption can sit on any album item, not always the first.
                caption_src = next(
                    (m for m in messages if (m.message or "").strip()),
                    first,
                )
                raw_text = caption_src.message or ""
                has_media = bool(first.media) or len(messages) > 1
                if has_media and (delivery.media_prefix or delivery.media_suffix):
                    parts: list[str] = []
                    if delivery.media_prefix:
                        parts.append(delivery.media_prefix.rstrip())
                    if raw_text:
                        parts.append(raw_text)
                    if delivery.media_suffix:
                        parts.append(delivery.media_suffix.lstrip())
                    raw_text = "\n".join(parts).strip()

                text = (
                    apply_text_filter(raw_text, text_filter, caption_src.entities)
                    if use_filter
                    else raw_text
                )
                buttons = _inline_buttons(delivery.button_text, delivery.button_url)

                if len(messages) == 1 and not first.media:
                    text = clip_telegram_text(text, TEXT_MESSAGE_LIMIT)
                    if text:
                        sent = await self.client.send_message(dest, text, buttons=buttons)
                    elif not use_filter:
                        sent = await self.client.send_message(dest, raw_text or "", buttons=buttons)
                    else:
                        sent = None
                else:
                    caption = clip_telegram_text(text, MEDIA_CAPTION_LIMIT)
                    if caption != text:
                        logger.warning(
                            "Caption truncated route=%s %s→%s chars",
                            route.route_key,
                            len(text),
                            len(caption),
                        )
                    try:
                        sent = await self.client.send_file(
                            dest,
                            file=messages if len(messages) > 1 else first,
                            caption=caption,
                            buttons=buttons,
                        )
                    except MediaCaptionTooLongError:
                        # Defensive retry (entity/UTF-16 edge cases).
                        shorter = clip_telegram_text(caption, MEDIA_CAPTION_LIMIT - 64)
                        sent = await self.client.send_file(
                            dest,
                            file=messages if len(messages) > 1 else first,
                            caption=shorter,
                            buttons=buttons,
                        )
                if sent is not None:
                    if isinstance(sent, list):
                        sent_ids = [m.id for m in sent if hasattr(m, "id")]
                    else:
                        sent_ids = [sent.id]
                if use_filter:
                    self.stats.incr("filtered_copy", route=route.route_key)
            else:
                sent = await self.client.forward_messages(
                    entity=dest,
                    messages=messages,
                    from_peer=messages[0].chat_id,
                )
                if isinstance(sent, list):
                    sent_ids = [m.id for m in sent if hasattr(m, "id")]
                elif sent is not None:
                    sent_ids = [sent.id]

            for src, dst in zip(messages, sent_ids or []):
                self.state.record_mapping(route.route_key, src.id, dst)
            self.state.set_last_seen(route.route_key, max(m.id for m in messages))

            if delivery.pin_latest and sent_ids:
                try:
                    await self.client.pin_message(dest, sent_ids[-1], notify=False)
                except Exception:
                    logger.debug("pin failed route=%s", route.route_key, exc_info=True)

            logger.info(
                "Delivered %s msg(s) ids=%s route=%s queued=%s",
                len(messages),
                ids,
                route.route_key,
                from_queue,
            )
            metric = "published_scheduled" if from_queue else "forwarded"
            self.stats.incr(metric, route=route.route_key)
            await self._sleep_delay()
            return True

        except FloodWaitError:
            raise
        except (MediaCaptionTooLongError, MessageTooLongError) as exc:
            logger.warning(
                "Length limit hit ids=%s route=%s (%s) — falling back to forward",
                ids,
                route.route_key,
                exc.__class__.__name__,
            )
            return await self._forward_fallback(
                messages, route, from_queue=from_queue, reason=exc.__class__.__name__
            )
        except Exception as exc:
            logger.exception(
                "Batch deliver failed ids=%s route=%s",
                ids,
                route.route_key,
            )
            await self._notify(f"⚠️ خطا در ارسال `{route.route_key}`: {exc.__class__.__name__}")
            return await self._forward_fallback(
                messages, route, from_queue=from_queue, reason=exc.__class__.__name__
            )

    async def _forward_fallback(
        self,
        messages: list[Message],
        route: ResolvedRoute,
        *,
        from_queue: bool,
        reason: str,
    ) -> bool:
        dest = route.dest_entity
        try:
            for msg in messages:
                sent = await self.client.forward_messages(
                    entity=dest,
                    messages=msg,
                    from_peer=msg.chat_id,
                )
                dst_id = sent.id if sent and hasattr(sent, "id") else None
                if dst_id:
                    self.state.record_mapping(route.route_key, msg.id, dst_id)
                await self._sleep_delay()
            self.state.set_last_seen(route.route_key, max(m.id for m in messages))
            self.stats.incr(
                "published_scheduled" if from_queue else "forwarded",
                route=route.route_key,
            )
            logger.info(
                "Fallback forward OK ids=%s route=%s reason=%s",
                [m.id for m in messages],
                route.route_key,
                reason,
            )
            return True
        except Exception as exc2:
            await self._notify(f"❌ fallback هم شکست `{route.route_key}`: {exc2}")
            self.stats.incr("failed", route=route.route_key)
            return False

    async def _sleep_delay(self) -> None:
        if self.delay_seconds <= 0 and self.delay_jitter <= 0:
            return
        extra = random.uniform(0, self.delay_jitter) if self.delay_jitter else 0.0
        await asyncio.sleep(self.delay_seconds + extra)


def _inline_buttons(text: str, url: str) -> ReplyInlineMarkup | None:
    text = (text or "").strip()
    url = (url or "").strip()
    if not text or not url:
        return None
    return ReplyInlineMarkup(rows=[[KeyboardButtonUrl(text=text, url=url)]])
