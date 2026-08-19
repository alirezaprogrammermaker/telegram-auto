"""Pure forward-route helpers for the Worker (no Telethon)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Callable

from app.Support.PromoRoutes import display_ref

MEDIA_TYPES = (
    "text",
    "photo",
    "video",
    "document",
    "audio",
    "voice",
    "animation",
    "sticker",
    "video_note",
    "poll",
    "other",
)

DEFAULT_TIMEZONE = "Asia/Tehran"
_DAY_ALIASES: dict[str, int] = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}
_DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def normalize_visibility(value: Any) -> str:
    text = str(value or "private").strip().lower()
    if text in {"public", "pub", "عمومی", "shared", "share"}:
        return "public"
    return "private"


def route_destinations(route: dict[str, Any]) -> list[Any]:
    dests = route.get("destinations")
    if isinstance(dests, list):
        cleaned = [d for d in dests if d not in (None, "")]
        if cleaned:
            return cleaned
    dest = route.get("destination")
    return [dest] if dest not in (None, "") else []


@dataclass
class TextFilterConfig:
    enabled: bool = False
    remove_links: bool = False
    remove_mentions: bool = False
    remove_hashtags: bool = False
    remove_ids: bool = False
    prefix: str = ""
    suffix: str = ""
    collapse_whitespace: bool = True
    block_enabled: bool = False
    block_words: list[str] = field(default_factory=list)
    allow_enabled: bool = False
    allow_words: list[str] = field(default_factory=list)
    regex_enabled: bool = False
    regex_pattern: str = ""
    regex_must_match: bool = True
    link_replacements: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["block_words"] = list(self.block_words)
        data["allow_words"] = list(self.allow_words)
        data["link_replacements"] = dict(self.link_replacements)
        return data

    @classmethod
    def from_dict(cls, data: Any) -> TextFilterConfig:
        if not isinstance(data, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        cleaned: dict[str, Any] = {}
        for key, value in data.items():
            if key in known:
                cleaned[key] = value
        return cls(**cleaned)

    def summary_lines(self) -> list[str]:
        return [
            f"enabled={'ON' if self.enabled else 'OFF'}",
            f"links={'ON' if self.remove_links else 'OFF'} "
            f"mentions={'ON' if self.remove_mentions else 'OFF'} "
            f"hashtags={'ON' if self.remove_hashtags else 'OFF'} "
            f"ids={'ON' if self.remove_ids else 'OFF'}",
            f"prefix={self.prefix or '(خالی)'}",
            f"suffix={self.suffix or '(خالی)'}",
            f"block={'ON' if self.block_enabled else 'OFF'} "
            f"({len(self.block_words)} کلمه)",
        ]


@dataclass
class MediaFilterConfig:
    enabled: bool = False
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "allow": list(self.allow), "deny": list(self.deny)}

    @classmethod
    def from_dict(cls, data: Any) -> MediaFilterConfig:
        if not isinstance(data, dict):
            return cls()
        allow = _clean_media_types(data.get("allow"))
        deny = _clean_media_types(data.get("deny"))
        return cls(enabled=bool(data.get("enabled", False)), allow=allow, deny=deny)

    def summary_lines(self) -> list[str]:
        allow = ", ".join(self.allow) if self.allow else "(همه)"
        deny = ", ".join(self.deny) if self.deny else "(خالی)"
        return [
            f"enabled={'ON' if self.enabled else 'OFF'}",
            f"allow={allow}",
            f"deny={deny}",
        ]


def _clean_media_types(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        key = str(item).strip().lower()
        if key in MEDIA_TYPES and key not in out:
            out.append(key)
    return out


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
        return asdict(self)

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

    def summary_lines(self) -> list[str]:
        return [
            f"pin_latest={'ON' if self.pin_latest else 'OFF'}",
            f"button={self.button_text or '(خالی)'} → {self.button_url or '(خالی)'}",
            f"sync_edits={'ON' if self.sync_edits else 'OFF'} "
            f"sync_deletes={'ON' if self.sync_deletes else 'OFF'}",
        ]


@dataclass
class ScheduleWindow:
    start: str
    end: str

    def to_dict(self) -> dict[str, str]:
        return {"start": self.start, "end": self.end}

    @classmethod
    def from_dict(cls, data: Any) -> ScheduleWindow | None:
        if not isinstance(data, dict):
            return None
        start = str(data.get("start") or "").strip()
        end = str(data.get("end") or "").strip()
        if not start or not end:
            return None
        _parse_hhmm(start)
        _parse_hhmm(end)
        return cls(start=start, end=end)


@dataclass
class ScheduleConfig:
    enabled: bool = False
    timezone: str = DEFAULT_TIMEZONE
    days: list[str] = field(default_factory=list)
    windows: list[ScheduleWindow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "timezone": self.timezone,
            "days": list(self.days),
            "windows": [w.to_dict() for w in self.windows],
        }

    @classmethod
    def from_dict(cls, data: Any) -> ScheduleConfig:
        if not isinstance(data, dict):
            return cls()
        days = [str(d).strip().lower() for d in (data.get("days") or []) if str(d).strip()]
        windows: list[ScheduleWindow] = []
        for item in data.get("windows") or []:
            w = ScheduleWindow.from_dict(item)
            if w:
                windows.append(w)
        return cls(
            enabled=bool(data.get("enabled", False)),
            timezone=str(data.get("timezone") or DEFAULT_TIMEZONE),
            days=days,
            windows=windows,
        )

    def summary_lines(self) -> list[str]:
        days = ", ".join(self.days) if self.days else "(همه)"
        wins = ", ".join(f"{w.start}-{w.end}" for w in self.windows) if self.windows else "(خالی)"
        return [
            f"enabled={'ON' if self.enabled else 'OFF'}",
            f"tz={self.timezone}",
            f"days={days}",
            f"windows={wins}",
        ]


def _parse_hhmm(value: str) -> None:
    text = value.strip()
    hour_s, minute_s = text.split(":", 1)
    hour = int(hour_s)
    minute = int(minute_s)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid time: {value}")


def parse_days_csv(raw: str) -> list[str]:
    parts = [p.strip().lower() for p in raw.replace("،", ",").split(",") if p.strip()]
    if not parts:
        raise ValueError("days empty")
    out: list[str] = []
    for part in parts:
        if part in _DAY_ALIASES:
            name = _DAY_NAMES[_DAY_ALIASES[part]]
        elif part in _DAY_NAMES:
            name = part
        else:
            raise ValueError(f"bad day: {part}")
        if name not in out:
            out.append(name)
    return out


def parse_windows_csv(raw: str) -> list[ScheduleWindow]:
    text = raw.replace(" ", "")
    if not text:
        raise ValueError("windows empty")
    out: list[ScheduleWindow] = []
    for chunk in text.split(","):
        if "-" not in chunk:
            raise ValueError(f"bad window: {chunk}")
        start, end = chunk.split("-", 1)
        _parse_hhmm(start)
        _parse_hhmm(end)
        out.append(ScheduleWindow(start=start, end=end))
    return out


def unescape_admin_text(raw: str) -> str:
    return (raw or "").replace("\\n", "\n").replace("\\t", "\t")


def default_route_dict(
    source: Any,
    destination: Any,
    *,
    owner_id: int | None = None,
    visibility: str = "private",
) -> dict[str, Any]:
    return {
        "source": display_ref(source),
        "destination": display_ref(destination),
        "destinations": [display_ref(destination)],
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


def _normalize_route_item(
    item: dict[str, Any], source: Any, dests: list[Any]
) -> dict[str, Any]:
    primary = display_ref(dests[0])
    owner = item.get("owner_id")
    if owner in (None, ""):
        owner_val = None
    else:
        try:
            owner_val = int(owner)
        except (TypeError, ValueError):
            owner_val = None
    return {
        "source": display_ref(source),
        "destination": primary,
        "destinations": [display_ref(d) for d in dests],
        "enabled": bool(item.get("enabled", True)),
        "paused": bool(item.get("paused", False)),
        "forward_mode": item.get("forward_mode"),
        "filter": TextFilterConfig.from_dict(item.get("filter")).to_dict(),
        "media_filter": MediaFilterConfig.from_dict(item.get("media_filter")).to_dict(),
        "schedule": ScheduleConfig.from_dict(item.get("schedule")).to_dict(),
        "dedup": DedupConfig.from_dict(item.get("dedup")).to_dict(),
        "delivery": DeliveryConfig.from_dict(item.get("delivery")).to_dict(),
        "owner_id": owner_val,
        "visibility": (
            "public"
            if owner_val is None
            else normalize_visibility(item.get("visibility"))
        ),
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


def find_route(routes: list[dict[str, Any]], source: Any) -> dict[str, Any] | None:
    want = display_ref(source)
    for route in routes:
        if display_ref(route.get("source")) == want:
            return route
    return None


def upsert_route(
    routes: list[dict[str, Any]], route: dict[str, Any]
) -> list[dict[str, Any]]:
    src = display_ref(route.get("source"))
    out: list[dict[str, Any]] = []
    replaced = False
    for item in routes:
        if display_ref(item.get("source")) == src:
            out.append(route)
            replaced = True
        else:
            out.append(item)
    if not replaced:
        out.append(route)
    return out


def remove_route(routes: list[dict[str, Any]], source: Any) -> list[dict[str, Any]]:
    want = display_ref(source)
    return [r for r in routes if display_ref(r.get("source")) != want]


def format_routes_lines(routes: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for route in routes:
        src = display_ref(route.get("source"))
        dests = ", ".join(display_ref(d) for d in route_destinations(route)) or "—"
        mode = route.get("forward_mode") or "default"
        flags: list[str] = []
        if route.get("paused"):
            flags.append("paused")
        if not route.get("enabled", True):
            flags.append("off")
        vis = normalize_visibility(route.get("visibility"))
        flags.append(vis)
        suffix = f" [{','.join(flags)}]" if flags else ""
        lines.append(f"• {src} → {dests} ({mode}){suffix}")
    return "\n".join(lines) if lines else "—"


def apply_filter_command(filt: TextFilterConfig, parts: list[str]) -> TextFilterConfig:
    if not parts:
        return filt
    key = parts[0].strip().lower()

    if key in {"on", "off", "enable", "disable"}:
        filt.enabled = key in {"on", "enable"}
        return filt

    if key in {"block", "بلاک", "blocklist"}:
        if len(parts) == 1:
            return filt
        sub = parts[1].strip().lower()
        if sub in {"on", "off"}:
            filt.block_enabled = sub == "on"
            return filt
        if sub in {"add", "remove", "rm", "del"} and len(parts) >= 3:
            word = " ".join(parts[2:]).strip()
            words = list(filt.block_words)
            if sub == "add":
                if word and word not in words:
                    words.append(word)
                filt.block_enabled = True
                filt.block_words = words
            else:
                filt.block_words = [
                    w for w in words if w.casefold() != word.casefold()
                ]
            return filt
        if sub == "clear":
            filt.block_words = []
            filt.block_enabled = False
        return filt

    bool_keys = {
        "links": "remove_links",
        "link": "remove_links",
        "mentions": "remove_mentions",
        "mention": "remove_mentions",
        "hashtags": "remove_hashtags",
        "hashtag": "remove_hashtags",
        "ids": "remove_ids",
        "id": "remove_ids",
    }
    if key in bool_keys:
        if len(parts) < 2 or parts[1].lower() not in {"on", "off"}:
            raise ValueError(f"need on|off for {key}")
        value = parts[1].lower() == "on"
        setattr(filt, bool_keys[key], value)
        if value:
            filt.enabled = True
        return filt

    if key in {"prefix", "suffix"}:
        if len(parts) < 2:
            raise ValueError(f"need text for {key}")
        raw = " ".join(parts[1:]).strip()
        if raw.lower() in {"off", "clear", "-", "none"}:
            setattr(filt, key, "")
        else:
            setattr(filt, key, unescape_admin_text(raw))
            filt.enabled = True
        return filt

    if key == "clear":
        return TextFilterConfig()

    raise ValueError(f"unknown filter key: {key}")


def apply_schedule_command(sched: ScheduleConfig, parts: list[str]) -> ScheduleConfig:
    if not parts:
        return sched
    key = parts[0].strip().lower()

    if key in {"on", "off"}:
        if key == "on" and not sched.windows:
            raise ValueError("set hours first")
        sched.enabled = key == "on"
        return sched

    if key in {"tz", "timezone"} and len(parts) >= 2:
        sched.timezone = parts[1].strip()
        return sched

    if key == "days" and len(parts) >= 2:
        sched.days = parse_days_csv(" ".join(parts[1:]))
        return sched

    if key in {"hours", "windows"} and len(parts) >= 2:
        sched.windows = parse_windows_csv("".join(parts[1:]))
        return sched

    if key == "clear":
        return ScheduleConfig()

    raise ValueError(f"unknown schedule key: {key}")


def apply_media_command(mf: MediaFilterConfig, parts: list[str]) -> MediaFilterConfig:
    if not parts:
        return mf
    key = parts[0].strip().lower()
    if key in {"on", "off"}:
        mf.enabled = key == "on"
        return mf
    if key == "allow" and len(parts) >= 2:
        mf.allow = _clean_media_types(
            [p.strip().lower() for p in " ".join(parts[1:]).replace("،", ",").split(",")]
        )
        mf.enabled = True
        return mf
    if key == "deny" and len(parts) >= 2:
        mf.deny = _clean_media_types(
            [p.strip().lower() for p in " ".join(parts[1:]).replace("،", ",").split(",")]
        )
        return mf
    raise ValueError("media: on|off|allow types|deny types")


def apply_dedup_command(dd: DedupConfig, parts: list[str]) -> DedupConfig:
    if not parts:
        return dd
    key = parts[0].strip().lower()
    if key in {"on", "off"}:
        dd.enabled = key == "on"
        return dd
    if len(parts) >= 2 and parts[1].isdigit():
        dd.window_hours = max(1, int(parts[1]))
    return dd


def apply_delivery_command(dlv: DeliveryConfig, parts: list[str]) -> DeliveryConfig:
    if len(parts) < 2:
        raise ValueError("delivery: pin on|button text url|sync on on")
    key = parts[0].strip().lower()
    if key == "pin":
        dlv.pin_latest = parts[1].lower() == "on"
        return dlv
    if key == "button" and len(parts) >= 3:
        dlv.button_text = parts[1]
        dlv.button_url = parts[2]
        return dlv
    if key == "sync":
        dlv.sync_edits = parts[1].lower() == "on"
        if len(parts) >= 3:
            dlv.sync_deletes = parts[2].lower() == "on"
        return dlv
    raise ValueError("delivery: pin|button|sync")


def mutate_route(
    routes: list[dict[str, Any]],
    source: str,
    mutator: Callable[[dict[str, Any]], None],
) -> list[dict[str, Any]]:
    route = find_route(routes, source)
    if not route:
        raise ValueError("route_missing")
    mutator(route)
    return upsert_route(routes, route)
