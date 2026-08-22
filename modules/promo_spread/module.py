"""Promo spread: multi-route channel posts → groups with human-like pacing."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from telethon import TelegramClient, events
from telethon.errors import (
    ChatWriteForbiddenError,
    FloodWaitError,
    PeerFloodError,
    RPCError,
    SlowModeWaitError,
    UserBannedInChannelError,
)
from telethon.tl import types as tl_types
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import Message

from app.base import BaseModule
from app.metrics_catalog import Promo
from app.notify import notify_admins
from app.telemetry import incr
from modules.channel_forward.refs import display_ref
from modules.promo_spread.queue import PromoQueue
from modules.promo_spread.report import report_promo_delivery, report_promo_seen
from modules.promo_spread.routes import migrate_routes
from modules.promo_spread.safety import SafetyConfig, SafetyGuard
from modules.promo_spread.targets import ensure_promo_group, ensure_source_channel

logger = logging.getLogger(__name__)

DEFAULT_SEEN_REACTION = "🕊"
DEFAULT_ACK_REACTION = "👍"
# The worker ticks every ~6s; collapse repeated blocks into one telemetry sample.
SKIP_SAMPLE_SECONDS = 300.0


@dataclass
class ResolvedPromoRoute:
    source_ref: str
    source_entity: Any
    source_id: int
    groups: list[tuple[Any, str, int]] = field(default_factory=list)  # entity, ref, id
    mode: str = "forward"
    paused: bool = False


class PromoSpreadModule(BaseModule):
    name = "promo_spread"

    def __init__(self, client: TelegramClient, config: dict[str, Any]) -> None:
        super().__init__(client, config)
        self.dry_run = bool(config.get("dry_run", True))
        self.global_paused = bool(config.get("paused", False))
        self.default_mode = str(config.get("mode") or "forward").lower()
        if self.default_mode not in {"forward", "copy"}:
            self.default_mode = "forward"
        self.route_defs = migrate_routes(config)
        self.album_wait = max(0.8, float(config.get("album_wait_seconds") or 2.5))
        # Joining invite links on startup can surprise you; admin /promo add may still join.
        self.auto_join = bool(config.get("auto_join", False))
        self.safety_cfg = SafetyConfig.from_dict(config.get("safety"))
        self.guard = SafetyGuard(self.safety_cfg)
        self.queue = PromoQueue()
        raw_seen = config.get("seen_reaction", DEFAULT_SEEN_REACTION)
        if raw_seen is False or raw_seen is None:
            self.seen_reaction = ""
        else:
            self.seen_reaction = str(raw_seen).strip() or DEFAULT_SEEN_REACTION
        raw_ack = config.get("ack_reaction", DEFAULT_ACK_REACTION)
        if raw_ack is False or raw_ack is None:
            self.ack_reaction = ""
        else:
            self.ack_reaction = str(raw_ack).strip() or DEFAULT_ACK_REACTION

        self._routes_by_source: dict[int, ResolvedPromoRoute] = {}
        self._group_entities: dict[int, Any] = {}  # group_id -> entity
        self._album_buffers: dict[tuple[int, int], list[Message]] = defaultdict(list)
        self._album_tasks: dict[tuple[int, int], asyncio.Task[None]] = {}
        self._worker: asyncio.Task[None] | None = None
        self._builder: events.NewMessage | None = None
        self._stopping = False
        self._skip_samples: dict[str, float] = {}

    async def start(self) -> None:
        if not self.route_defs:
            logger.warning("promo_spread: no routes — idle (use /promo add)")
            return

        watch: list[Any] = []
        for raw in self.route_defs:
            if not raw.get("enabled", True):
                continue
            source = raw.get("source")
            groups = raw.get("groups") or []
            if not source:
                continue
            # Always join/resolve the source first — even when groups are still
            # empty (admin just registered the ad channel). Skipping here was
            # why new promo accounts never auto-joined @source.
            try:
                source_entity, src_label = await ensure_source_channel(
                    self.client, source, auto_join=self.auto_join
                )
                logger.info(
                    "promo source ready %s (auto_join=%s groups=%s)",
                    src_label,
                    self.auto_join,
                    len(groups),
                )
            except Exception as exc:
                logger.error("promo source skip %s: %s", source, exc)
                continue

            if not groups:
                logger.warning(
                    "promo route %s has no groups yet — source joined, waiting for groups",
                    src_label,
                )
                continue

            resolved_groups: list[tuple[Any, str, int]] = []
            for ref in groups:
                try:
                    entity, label, gid = await ensure_promo_group(
                        self.client, ref, auto_join=self.auto_join
                    )
                    resolved_groups.append((entity, label, gid))
                    self._group_entities[gid] = entity
                    logger.info("promo %s → group %s", src_label, label)
                except Exception as exc:
                    logger.error("promo group skip %s (source=%s): %s", ref, src_label, exc)

            if not resolved_groups:
                logger.error("promo route %s: no valid groups", src_label)
                continue

            mode = str(raw.get("mode") or self.default_mode).lower()
            if mode not in {"forward", "copy"}:
                mode = self.default_mode
            route = ResolvedPromoRoute(
                source_ref=src_label,
                source_entity=source_entity,
                source_id=int(source_entity.id),
                groups=resolved_groups,
                mode=mode,
                paused=bool(raw.get("paused", False)),
            )
            chat_key = self._chat_key(source_entity)
            self._routes_by_source[chat_key] = route
            if source_entity not in watch:
                watch.append(source_entity)
            logger.info(
                "promo route: %s → %s group(s) mode=%s paused=%s",
                src_label,
                len(resolved_groups),
                mode,
                route.paused,
            )

        if not self._routes_by_source:
            logger.warning("promo_spread: no valid routes — idle")
            return

        self._builder = events.NewMessage(chats=watch)
        self.client.add_event_handler(self._on_new_message, self._builder)
        self._stopping = False
        self._worker = asyncio.create_task(self._worker_loop())
        logger.info(
            "promo_spread watching %s source(s); dry_run=%s global_paused=%s auto_join=%s",
            len(self._routes_by_source),
            self.dry_run,
            self.global_paused,
            self.auto_join,
        )

    def _chat_key(self, entity: Any) -> int:
        try:
            from telethon import utils

            return int(utils.get_peer_id(entity))
        except Exception:
            return int(entity.id)

    async def stop(self) -> None:
        self._stopping = True
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None
        if self._builder:
            self.client.remove_event_handler(self._on_new_message, self._builder)
            self._builder = None
        for task in list(self._album_tasks.values()):
            task.cancel()
        self._album_tasks.clear()
        self._album_buffers.clear()
        self._routes_by_source.clear()
        self._group_entities.clear()

    async def _on_new_message(self, event: events.NewMessage.Event) -> None:
        try:
            message = event.message
            if not isinstance(message, Message) or message.action is not None:
                return
            chat_id = event.chat_id
            if chat_id is None:
                return
            route = self._routes_by_source.get(int(chat_id))
            if route is None:
                return
            if route.paused or self.global_paused:
                return

            grouped_id = message.grouped_id
            if grouped_id:
                key = (int(chat_id), int(grouped_id))
                buf = self._album_buffers[key]
                if not any(m.id == message.id for m in buf):
                    buf.append(message)
                prev = self._album_tasks.get(key)
                if prev and not prev.done():
                    prev.cancel()
                self._album_tasks[key] = asyncio.create_task(self._flush_album(key, route))
                return

            await self._enqueue_post(route, [message])
        except Exception:
            logger.exception("promo_spread on_new_message failed")

    async def _flush_album(self, key: tuple[int, int], route: ResolvedPromoRoute) -> None:
        try:
            await asyncio.sleep(self.album_wait)
            messages = self._album_buffers.pop(key, [])
            self._album_tasks.pop(key, None)
            if not messages:
                return
            chat_id, grouped_id = key
            by_id = {m.id: m for m in messages if m.id}
            try:
                lo = min(by_id)
                fetched = await self.client.get_messages(chat_id, min_id=lo - 1, limit=10)
                for m in fetched:
                    if (
                        isinstance(m, Message)
                        and getattr(m, "grouped_id", None) == grouped_id
                        and m.id
                    ):
                        by_id[m.id] = m
            except Exception:
                logger.debug("promo album reconcile failed", exc_info=True)
            await self._enqueue_post(route, sorted(by_id.values(), key=lambda m: m.id))
        except asyncio.CancelledError:
            return

    async def _enqueue_post(self, route: ResolvedPromoRoute, messages: list[Message]) -> None:
        if not messages:
            return
        ids = [m.id for m in messages if m.id]
        if not ids:
            return
        post_key = f"{route.source_id}:{min(ids)}-{max(ids)}"
        targets = list(route.groups)
        if self.safety_cfg.shuffle_targets:
            random.shuffle(targets)

        created = 0
        jobs: list[dict[str, Any]] = []
        for _entity, label, gid in targets:
            item_id = self.queue.enqueue(
                source_id=route.source_id,
                group_ref=label,
                group_id=gid,
                message_ids=ids,
                mode=route.mode,
                post_key=post_key,
            )
            if item_id:
                created += 1
                jobs.append(
                    {
                        "job_id": item_id,
                        "group_ref": label,
                        "group_id": gid,
                        "mode": route.mode,
                    }
                )
        logger.info(
            "promo enqueued %s (%s) → %s job(s)",
            post_key,
            route.source_ref,
            created,
        )
        if created > 0:
            report_promo_seen(
                post_key=post_key,
                source_ref=route.source_ref,
                source_id=route.source_id,
                message_ids=ids,
                jobs=jobs,
                mode=route.mode,
            )
            await self._react_seen(route, ids, post_key)

    async def _react_seen(
        self, route: ResolvedPromoRoute, message_ids: list[int], post_key: str
    ) -> None:
        if not self.seen_reaction:
            return
        if not self.queue.try_claim_post_seen(post_key):
            return
        await self._react_on_source(
            source_entity=route.source_entity,
            message_ids=message_ids,
            emoticons=[self.seen_reaction],
            post_key=post_key,
            kind="seen",
        )

    async def _worker_loop(self) -> None:
        await asyncio.sleep(random.uniform(8, 25))
        while not self._stopping:
            try:
                await self._worker_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("promo worker loop error")
            await asyncio.sleep(random.uniform(4, 9))

    async def _worker_once(self) -> None:
        if self.global_paused:
            self._note_skip(Promo.SKIPPED_PAUSED)
            return
        active, why = self.guard.is_active_now()
        if not active:
            logger.debug("promo idle: %s", why)
            self._note_skip(Promo.SKIPPED_QUIET)
            return
        ok_b, why_b = self.guard.budget_ok()
        if not ok_b:
            logger.debug("promo budget block: %s", why_b)
            self._note_skip(Promo.SKIPPED_BUDGET)
            return

        item = self.queue.pop_next()
        if item is None:
            return

        group_key = str(item.get("group_ref") or item.get("group_id"))
        cool_ok, cool_why = self.guard.group_cooldown_ok(group_key)
        if not cool_ok:
            self.queue.defer(str(item["id"]), cool_why)
            incr(Promo.SKIPPED_COOLDOWN)
            return

        delay = self.guard.human_delay_seconds()
        logger.info(
            "promo pacing %.0fs before %s (post=%s)",
            delay,
            group_key,
            item.get("post_key"),
        )
        await asyncio.sleep(delay)

        active, _ = self.guard.is_active_now()
        if not active or self.global_paused:
            return
        ok_b, _ = self.guard.budget_ok()
        if not ok_b:
            return

        await self._deliver_item(item)

    def _note_skip(self, metric: str) -> None:
        """Sample a blocked tick — only while posts are actually waiting."""
        if not self._pending_work():
            return
        now = time.monotonic()
        if now - self._skip_samples.get(metric, 0.0) < SKIP_SAMPLE_SECONDS:
            return
        self._skip_samples[metric] = now
        incr(metric)

    def _pending_work(self) -> bool:
        try:
            return bool(self.queue.list_pending())
        except Exception:  # noqa: BLE001 - telemetry must not break the worker
            return False

    def _source_entity_for(self, source_id: int) -> Any | None:
        for route in self._routes_by_source.values():
            if route.source_id == source_id:
                return route.source_entity
        return None

    def _report_item(
        self,
        item: dict[str, Any],
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        report_promo_delivery(
            job_id=str(item.get("id") or ""),
            post_key=str(item.get("post_key") or ""),
            group_ref=str(item.get("group_ref") or ""),
            status=status,
            source_ref=None,
            source_id=int(item["source_id"]) if item.get("source_id") is not None else None,
            message_ids=[int(x) for x in (item.get("message_ids") or [])],
            group_id=int(item["group_id"]) if item.get("group_id") is not None else None,
            error=error,
            mode=str(item.get("mode") or self.default_mode),
        )

    async def _deliver_item(self, item: dict[str, Any]) -> None:
        item_id = str(item["id"])
        group_ref = str(item.get("group_ref"))
        group_id = int(item["group_id"])
        source_id = int(item["source_id"])
        message_ids = [int(x) for x in (item.get("message_ids") or [])]
        mode = str(item.get("mode") or self.default_mode)

        entity = self._group_entities.get(group_id)
        if entity is None:
            try:
                entity, group_ref, group_id = await ensure_promo_group(
                    self.client, group_ref, auto_join=False
                )
                self._group_entities[group_id] = entity
            except Exception as exc:
                self.queue.mark_failed(item_id, str(exc), retry=False)
                self._report_item(item, status="failed", error=str(exc)[:300])
                await self._maybe_ack_source_post(item)
                return

        source_entity = self._source_entity_for(source_id)
        if source_entity is None:
            self.queue.mark_failed(item_id, "source route gone", retry=False)
            self._report_item(item, status="failed", error="source route gone")
            await self._maybe_ack_source_post(item)
            return

        if self.dry_run:
            logger.info(
                "DRY-RUN promo would send ids=%s → %s mode=%s source=%s",
                message_ids,
                group_ref,
                mode,
                source_id,
            )
            self.guard.note_success(group_ref)
            self.queue.mark_done(item_id)
            self._report_item(item, status="dry_run")
            await self._maybe_ack_source_post(item)
            return

        try:
            read_delay = self.guard.read_delay_seconds()
            if read_delay > 0:
                await asyncio.sleep(read_delay * 0.35)
                try:
                    await self.client.get_messages(source_entity, ids=message_ids)
                except Exception:
                    logger.debug("promo read prefetch failed", exc_info=True)
                await asyncio.sleep(read_delay * 0.65)

            typing_for = self.guard.typing_seconds()
            async with self.client.action(entity, "typing"):
                await asyncio.sleep(typing_for)

            messages = await self.client.get_messages(source_entity, ids=message_ids)
            msgs = [m for m in messages if isinstance(m, Message)]
            if not msgs:
                self.queue.mark_failed(item_id, "source messages missing", retry=False)
                self._report_item(item, status="failed", error="source messages missing")
                await self._maybe_ack_source_post(item)
                return
            msgs.sort(key=lambda m: m.id)

            if mode == "copy":
                first = msgs[0]
                caption = next((m.message or "" for m in msgs if (m.message or "").strip()), "")
                if len(msgs) == 1 and not first.media:
                    await self.client.send_message(entity, caption or first.message or "")
                else:
                    await self.client.send_file(
                        entity,
                        file=msgs if len(msgs) > 1 else first,
                        caption=caption[:1024] if caption else None,
                    )
            else:
                await self.client.forward_messages(
                    entity=entity,
                    messages=msgs,
                    from_peer=source_entity,
                )

            self.guard.note_success(group_ref)
            self.queue.mark_done(item_id)
            logger.info("promo delivered ids=%s → %s", message_ids, group_ref)
            self._report_item(item, status="delivered")
            await self._maybe_ack_source_post(item)

        except FloodWaitError as exc:
            incr(Promo.FLOOD_WAIT)
            self.guard.note_flood_wait(int(exc.seconds))
            self.queue.defer(item_id, f"FloodWait {exc.seconds}s")
            self._report_item(item, status="deferred", error=f"FloodWait {exc.seconds}s")
            await asyncio.sleep(int(exc.seconds) + random.randint(5, 20))
        except PeerFloodError:
            incr(Promo.PEER_FLOOD)
            self.guard.note_peer_flood()
            self.queue.defer(item_id, "PeerFlood")
            self._report_item(item, status="deferred", error="PeerFlood")
            await self._alert("⛔ PeerFlood — promo به‌صورت خودکار ۲۴ساعت متوقف شد")
        except SlowModeWaitError as exc:
            self.queue.defer(item_id, f"SlowMode {exc.seconds}s")
            self._report_item(item, status="deferred", error=f"SlowMode {exc.seconds}s")
            await asyncio.sleep(int(exc.seconds) + 3)
        except (ChatWriteForbiddenError, UserBannedInChannelError) as exc:
            self.queue.mark_failed(item_id, exc.__class__.__name__, retry=False)
            self._report_item(item, status="failed", error=exc.__class__.__name__)
            await self._alert(f"⚠️ نوشتن در `{group_ref}` ممنوع: {exc.__class__.__name__}")
            await self._maybe_ack_source_post(item)
        except RPCError as exc:
            logger.exception("promo RPC fail → %s", group_ref)
            self.queue.mark_failed(item_id, exc.__class__.__name__, retry=True)
            # Only report failed when retries are exhausted (status flipped off pending).
            pending_ids = {str(i.get("id")) for i in self.queue.list_pending()}
            if item_id not in pending_ids:
                self._report_item(item, status="failed", error=exc.__class__.__name__)
            else:
                self._report_item(
                    item, status="deferred", error=f"retry:{exc.__class__.__name__}"
                )
            await self._maybe_ack_source_post(item)
        except Exception as exc:
            logger.exception("promo unexpected → %s", group_ref)
            self.queue.mark_failed(item_id, str(exc), retry=True)
            pending_ids = {str(i.get("id")) for i in self.queue.list_pending()}
            if item_id not in pending_ids:
                self._report_item(item, status="failed", error=str(exc)[:300])
            else:
                self._report_item(item, status="deferred", error=f"retry:{exc}"[:300])
            await self._maybe_ack_source_post(item)

    async def _maybe_ack_source_post(self, item: dict[str, Any]) -> None:
        """React 👍 on the ad-channel post once every destination job has settled."""
        if not self.ack_reaction:
            return
        post_key = str(item.get("post_key") or "")
        if not self.queue.try_claim_post_ack(post_key):
            return
        source_id = int(item.get("source_id") or 0)
        message_ids = [
            int(x)
            for x in (item.get("message_ids") or [])
            if str(x).lstrip("-").isdigit()
        ]
        if not source_id or not message_ids:
            return
        source_entity = self._source_entity_for(source_id)
        if source_entity is None:
            logger.warning("promo ack skipped: source gone for %s", post_key)
            return
        # Keep dove if we marked seen, then thumbs for "finished".
        emoticons = []
        if self.seen_reaction:
            emoticons.append(self.seen_reaction)
        emoticons.append(self.ack_reaction)
        await self._react_on_source(
            source_entity=source_entity,
            message_ids=message_ids,
            emoticons=emoticons,
            post_key=post_key,
            kind="ack",
        )

    async def _react_on_source(
        self,
        *,
        source_entity: Any,
        message_ids: list[int],
        emoticons: list[str],
        post_key: str,
        kind: str,
    ) -> None:
        clean = [e for e in emoticons if e]
        if not clean or not message_ids:
            return
        msg_id = min(int(x) for x in message_ids)
        try:
            await self.client(
                SendReactionRequest(
                    peer=source_entity,
                    msg_id=msg_id,
                    reaction=[
                        tl_types.ReactionEmoji(emoticon=e) for e in clean
                    ],
                )
            )
            logger.info(
                "promo %s reaction %s on source msg %s (%s)",
                kind,
                "".join(clean),
                msg_id,
                post_key,
            )
            self._note_reaction(kind)
        except Exception as exc:
            # Channels that disallow multi-react: retry with the last emoji only.
            if len(clean) > 1:
                try:
                    await self.client(
                        SendReactionRequest(
                            peer=source_entity,
                            msg_id=msg_id,
                            reaction=[
                                tl_types.ReactionEmoji(emoticon=clean[-1])
                            ],
                        )
                    )
                    logger.info(
                        "promo %s reaction fallback %s on source msg %s (%s)",
                        kind,
                        clean[-1],
                        msg_id,
                        post_key,
                    )
                    self._note_reaction(kind)
                    return
                except Exception as exc2:
                    logger.warning(
                        "promo %s reaction failed for %s: %s",
                        kind,
                        post_key,
                        exc2.__class__.__name__,
                    )
                    return
            logger.warning(
                "promo %s reaction failed for %s: %s",
                kind,
                post_key,
                exc.__class__.__name__,
            )

    @staticmethod
    def _note_reaction(kind: str) -> None:
        metric = Promo.REACTION_ACK if kind == "ack" else Promo.REACTION_SEEN
        incr(metric)

    async def _alert(self, text: str) -> None:
        import os

        raw = os.environ.get("ADMIN_IDS", "")
        ids = set()
        for part in str(raw).replace(";", ",").split(","):
            if part.strip().lstrip("-").isdigit():
                ids.add(int(part.strip()))
        if ids:
            await notify_admins(self.client, ids, text)
        try:
            from app.control_plane_alert import post_admin_bot_alert
            from app.paths import account_id as current_account_id

            post_admin_bot_alert(
                account_id=current_account_id(),
                message=text,
                severity="warning",
            )
        except Exception:
            pass
