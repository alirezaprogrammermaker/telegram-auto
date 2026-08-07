"""Media-type filtering for forwarded messages."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any

from telethon.tl.types import Message, MessageMediaDocument, MessageMediaPhoto

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


@dataclass
class MediaFilterConfig:
    enabled: bool = False
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "allow": list(self.allow),
            "deny": list(self.deny),
        }

    @classmethod
    def from_dict(cls, data: Any) -> MediaFilterConfig:
        if not isinstance(data, dict):
            return cls()
        allow = _clean_types(data.get("allow"))
        deny = _clean_types(data.get("deny"))
        return cls(enabled=bool(data.get("enabled", False)), allow=allow, deny=deny)

    def summary_lines(self) -> list[str]:
        allow = ", ".join(self.allow) if self.allow else "(همه)"
        deny = ", ".join(self.deny) if self.deny else "(خالی)"
        return [
            f"enabled: {'ON' if self.enabled else 'OFF'}",
            f"allow: {allow}",
            f"deny: {deny}",
        ]


def _clean_types(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        key = str(item).strip().lower()
        if key in MEDIA_TYPES and key not in out:
            out.append(key)
    return out


def detect_media_type(message: Message) -> str:
    if not message.media:
        return "text" if (message.message or "").strip() else "other"

    media = message.media
    if isinstance(media, MessageMediaPhoto):
        return "photo"
    if isinstance(media, MessageMediaDocument):
        doc = media.document
        if doc is None:
            return "document"
        mime = getattr(doc, "mime_type", "") or ""
        attrs = {type(a).__name__ for a in (getattr(doc, "attributes", None) or [])}
        if "DocumentAttributeAnimated" in attrs:
            return "animation"
        if "DocumentAttributeSticker" in attrs:
            return "sticker"
        if "DocumentAttributeVideo" in attrs:
            if "DocumentAttributeVideo" in attrs and any(
                getattr(a, "round_message", False)
                for a in (getattr(doc, "attributes", None) or [])
                if type(a).__name__ == "DocumentAttributeVideo"
            ):
                return "video_note"
            return "video"
        if "DocumentAttributeAudio" in attrs:
            for a in getattr(doc, "attributes", None) or []:
                if type(a).__name__ == "DocumentAttributeAudio" and getattr(a, "voice", False):
                    return "voice"
            return "audio"
        if mime.startswith("video/"):
            return "video"
        if mime.startswith("audio/"):
            return "audio"
        return "document"
    if type(media).__name__ == "MessageMediaPoll":
        return "poll"
    return "other"


def media_allowed(message: Message, cfg: MediaFilterConfig) -> bool:
    if not cfg.enabled:
        return True
    kind = detect_media_type(message)
    if cfg.deny and kind in cfg.deny:
        return False
    if cfg.allow:
        return kind in cfg.allow
    return True
