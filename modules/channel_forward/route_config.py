"""Route configuration schema, migration, and resolution."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from telethon import TelegramClient, utils
from telethon.tl.types import Channel

from modules.channel_forward.access import normalize_visibility
from modules.channel_forward.filters import TextFilterConfig
from modules.channel_forward.media_filter import MediaFilterConfig
from modules.channel_forward.refs import (
    display_ref,
    ensure_can_post,
    ensure_joined,
    normalize_ref,
    route_key,
)
from modules.channel_forward.schedule import ScheduleConfig
from app.progress import ProgressMessenger

logger = logging.getLogger(__name__)


@dataclass
class DedupConfig:
    enabled: bool = False
    window_hours: int = 24

    def to_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "window_hours": max(1, int(self.window_hours))}

    @classmethod
    def from_dict(cls, data: Any) -> DedupConfig:
        if not isinstance(data, dict):
            return cls()
        try:
            hours = int(data.get("window_hours") or 24)
        except (TypeError, ValueError):
            hours = 24
        return cls(enabled=bool(data.get("enabled", False)), window_hours=max(1, hours))


@dataclass
class DeliveryConfig:
    pin_latest: bool = False
    button_text: str = ""
    button_url: str = ""
    sync_edits: bool = True
    sync_deletes: bool = True
    preserve_reply: bool = False
    media_prefix: str = ""
    media_suffix: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pin_latest": self.pin_latest,
            "button_text": self.button_text,
            "button_url": self.button_url,
            "sync_edits": self.sync_edits,
            "sync_deletes": self.sync_deletes,
            "preserve_reply": self.preserve_reply,
            "media_prefix": self.media_prefix,
            "media_suffix": self.media_suffix,
        }

    @classmethod
    def from_dict(cls, data: Any) -> DeliveryConfig:
        if not isinstance(data, dict):
            return cls()
        return cls(
            pin_latest=bool(data.get("pin_latest", False)),
            button_text=str(data.get("button_text") or ""),
            button_url=str(data.get("button_url") or ""),
            sync_edits=bool(data.get("sync_edits", True)),
            sync_deletes=bool(data.get("sync_deletes", True)),
            preserve_reply=bool(data.get("preserve_reply", False)),
            media_prefix=str(data.get("media_prefix") or ""),
            media_suffix=str(data.get("media_suffix") or ""),
        )


def route_destinations(route: dict[str, Any]) -> list[Any]:
    dests = route.get("destinations")
    if isinstance(dests, list):
        cleaned = [d for d in dests if d not in (None, "")]
        if cleaned:
            return cleaned
    dest = route.get("destination")
    return [dest] if dest not in (None, "") else []


def default_route_dict(
    source: Any,
    destination: Any,
    *,
    owner_id: int | None = None,
    visibility: str = "private",
) -> dict[str, Any]:
    return {
        "source": source,
        "destination": destination,
        "destinations": [destination],
        "enabled": True,
        "paused": False,
        "forward_mode": None,
        "owner_id": owner_id,
        "visibility": visibility,
        "filter": TextFilterConfig().to_dict(),
        "media_filter": MediaFilterConfig().to_dict(),
        "schedule": ScheduleConfig().to_dict(),
        "dedup": DedupConfig().to_dict(),
        "delivery": DeliveryConfig().to_dict(),
    }


def migrate_routes(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_routes = config.get("routes")
    if isinstance(raw_routes, list) and raw_routes:
        cleaned: list[dict[str, Any]] = []
        for item in raw_routes:
            if not isinstance(item, dict):
                continue
            source = item.get("source") or item.get("from")
            dests = route_destinations(item)
            if not source or not dests:
                continue
            cleaned.append(_normalize_route_item(item, source, dests))
        return cleaned

    sources = config.get("sources") or []
    dest = config.get("destination")
    if dest and isinstance(sources, list):
        return [
            default_route_dict(src, dest, owner_id=None, visibility="public")
            for src in sources
            if src
        ]
    return []


def _normalize_route_item(
    item: dict[str, Any],
    source: Any,
    dests: list[Any],
) -> dict[str, Any]:
    primary = dests[0]
    return {
        "source": source,
        "destination": primary,
        "destinations": list(dests),
        "enabled": bool(item.get("enabled", True)),
        "paused": bool(item.get("paused", False)),
        "forward_mode": item.get("forward_mode"),
        "filter": TextFilterConfig.from_dict(item.get("filter")).to_dict(),
        "media_filter": MediaFilterConfig.from_dict(item.get("media_filter")).to_dict(),
        "schedule": ScheduleConfig.from_dict(item.get("schedule")).to_dict(),
        "dedup": DedupConfig.from_dict(item.get("dedup")).to_dict(),
        "delivery": DeliveryConfig.from_dict(item.get("delivery")).to_dict(),
        "owner_id": item.get("owner_id"),
        "visibility": (
            "public"
            if item.get("owner_id") in (None, "")
            else normalize_visibility(item.get("visibility"))
        ),
    }


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
    media_filter: MediaFilterConfig
    schedule: ScheduleConfig
    dedup: DedupConfig
    delivery: DeliveryConfig
    route_key: str
    paused: bool = False


async def resolve_route(
    client: TelegramClient,
    route: dict[str, Any],
    *,
    default_mode: str,
    progress: ProgressMessenger | None = None,
) -> list[ResolvedRoute]:
    source_raw = route["source"]
    mode = str(route.get("forward_mode") or default_mode).lower()
    if mode not in {"forward", "copy"}:
        mode = default_mode

    if progress:
        await progress.step(f"بررسی کانال مبدأ: `{display_ref(source_raw)}`")

    source_entity, join_status = await ensure_joined(
        client,
        source_raw,
        progress,
        label="مبدأ",
    )
    from telethon.tl.types import Channel

    if not isinstance(source_entity, Channel):
        raise ValueError(f"source is not a channel: {source_raw}")

    logger.info(
        "Source %s join-status=%s",
        display_ref(source_raw),
        join_status,
    )

    resolved: list[ResolvedRoute] = []
    text_filter = TextFilterConfig.from_dict(route.get("filter"))
    media_filter = MediaFilterConfig.from_dict(route.get("media_filter"))
    schedule = ScheduleConfig.from_dict(route.get("schedule"))
    dedup = DedupConfig.from_dict(route.get("dedup"))
    delivery = DeliveryConfig.from_dict(route.get("delivery"))
    paused = bool(route.get("paused", False))

    for dest_raw in route_destinations(route):
        dest_entity, post_reason = await ensure_can_post(
            client,
            dest_raw,
            progress,
            auto_join=True,
        )
        logger.info(
            "Destination %s post-check OK (%s)",
            display_ref(dest_raw),
            post_reason,
        )
        key = route_key(source_raw, dest_raw)
        resolved.append(
            ResolvedRoute(
                source_ref=normalize_ref(source_raw),
                dest_ref=normalize_ref(dest_raw),
                source_id=utils.get_peer_id(source_entity),
                dest_id=utils.get_peer_id(dest_entity),
                source_entity=source_entity,
                dest_entity=dest_entity,
                mode=mode,
                text_filter=text_filter,
                media_filter=media_filter,
                schedule=schedule,
                dedup=dedup,
                delivery=delivery,
                route_key=key,
                paused=paused,
            )
        )
    return resolved
