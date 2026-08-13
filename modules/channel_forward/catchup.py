"""Catch-up/backfill for missed messages while offline."""
from __future__ import annotations

import logging

from telethon.tl.types import Message

from modules.channel_forward.delivery import DeliveryEngine
from modules.channel_forward.route_config import ResolvedRoute
from modules.channel_forward.state import ForwardStateStore

logger = logging.getLogger(__name__)


async def catch_up_routes(
    client,
    routes: list[ResolvedRoute],
    engine: DeliveryEngine,
    state: ForwardStateStore,
    *,
    limit: int = 50,
) -> int:
    """Fetch and deliver messages newer than last_seen for each route."""
    delivered = 0
    for route in routes:
        if route.paused:
            continue
        last = state.get_last_seen(route.route_key)
        try:
            history = await client.get_messages(
                route.source_entity,
                limit=max(1, min(limit, 200)),
                min_id=last or 0,
            )
        except Exception:
            logger.exception("catch-up fetch failed route=%s", route.route_key)
            continue

        msgs = [m for m in history if isinstance(m, Message) and m.id]
        if not msgs:
            continue
        msgs.sort(key=lambda m: m.id)

        # Group albums by grouped_id (IDs are contiguous; pull siblings if gap).
        i = 0
        while i < len(msgs):
            msg = msgs[i]
            if msg.action is not None:
                i += 1
                continue
            batch = [msg]
            gid = getattr(msg, "grouped_id", None)
            if gid:
                j = i + 1
                while j < len(msgs) and getattr(msgs[j], "grouped_id", None) == gid:
                    batch.append(msgs[j])
                    j += 1
                # History window may have been truncated mid-album; refill.
                if len(batch) < 10:
                    try:
                        lo = min(m.id for m in batch)
                        extra = await client.get_messages(
                            route.source_entity,
                            min_id=lo - 1,
                            limit=10,
                        )
                        by_id = {m.id: m for m in batch}
                        for m in extra:
                            if (
                                isinstance(m, Message)
                                and getattr(m, "grouped_id", None) == gid
                                and m.id
                            ):
                                by_id[m.id] = m
                        batch = sorted(by_id.values(), key=lambda m: m.id)
                    except Exception:
                        logger.exception(
                            "catch-up album refill failed route=%s",
                            route.route_key,
                        )
                i = j
            else:
                i += 1
            if await engine.process_messages(batch, route, from_queue=False):
                delivered += len(batch)
    if delivered:
        logger.info("Catch-up delivered %s message(s)", delivered)
    return delivered
