"""Optional text filters for channel_forward copy mode."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Iterable

from telethon.helpers import add_surrogate, del_surrogate

_LINK_RE = re.compile(
    r"(?i)\b(?:https?://|www\.)\S+|t\.me/\S+|telegram\.me/\S+|tg://\S+"
)
_MENTION_RE = re.compile(r"@[A-Za-z0-9_]{3,}")
_HASHTAG_RE = re.compile(r"#[\w\u0600-\u06FF\u0750-\u077F]+", re.UNICODE)
_ID_RE = re.compile(r"(?<![\w/])-?\d{6,}(?![\w/])")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_MULTI_NL_RE = re.compile(r"\n{3,}")

_LINK_ENTITY_TYPES = {"MessageEntityUrl", "MessageEntityTextUrl"}
_MENTION_ENTITY_TYPES = {"MessageEntityMention", "MessageEntityMentionName"}
_HASHTAG_ENTITY_TYPES = {"MessageEntityHashtag"}


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

    def is_active(self) -> bool:
        if not self.enabled:
            return False
        return bool(
            self.remove_links
            or self.remove_mentions
            or self.remove_hashtags
            or self.remove_ids
            or self.prefix.strip()
            or self.suffix.strip()
            or self.link_replacements
        )

    def find_blocked_word(self, text: str | None) -> str | None:
        if not self.block_enabled or not self.block_words:
            return None
        hay = (text or "").casefold()
        for word in self.block_words:
            token = str(word).strip()
            if token and token.casefold() in hay:
                return token
        return None

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
            if key not in known:
                continue
            if key in {"prefix", "suffix", "regex_pattern"}:
                cleaned[key] = str(value or "")
            elif key in {"block_words", "allow_words"}:
                words: list[str] = []
                if isinstance(value, list):
                    for item in value:
                        text = str(item).strip()
                        if text and text not in words:
                            words.append(text)
                cleaned[key] = words
            elif key == "link_replacements":
                repl: dict[str, str] = {}
                if isinstance(value, dict):
                    for k, v in value.items():
                        ks = str(k).strip()
                        if ks:
                            repl[ks] = str(v or "")
                cleaned[key] = repl
            elif key in {
                "enabled",
                "remove_links",
                "remove_mentions",
                "remove_hashtags",
                "remove_ids",
                "collapse_whitespace",
                "block_enabled",
                "allow_enabled",
                "regex_enabled",
                "regex_must_match",
            }:
                cleaned[key] = bool(value)
            else:
                cleaned[key] = value
        return cls(**cleaned)

    def summary_lines(self) -> list[str]:
        def flag(name: str, on: bool) -> str:
            return f"{name}: {'ON' if on else 'OFF'}"

        words = ", ".join(self.block_words) if self.block_words else "(خالی)"
        allow = ", ".join(self.allow_words) if self.allow_words else "(خالی)"
        lines = [
            flag("enabled", self.enabled),
            flag("remove_links (لینک)", self.remove_links),
            flag("remove_mentions (منشن)", self.remove_mentions),
            flag("remove_hashtags (هشتگ)", self.remove_hashtags),
            flag("remove_ids (آیدی)", self.remove_ids),
            flag("collapse_whitespace", self.collapse_whitespace),
            flag("block_enabled (بلاک‌لیست)", self.block_enabled),
            f"block_words: {words}",
            flag("allow_enabled", self.allow_enabled),
            f"allow_words: {allow}",
            flag("regex_enabled", self.regex_enabled),
            f"regex_pattern: {_preview(self.regex_pattern)}",
            f"regex_must_match: {self.regex_must_match}",
            f"link_replacements: {len(self.link_replacements)}",
            f"prefix: {_preview(self.prefix)}",
            f"suffix: {_preview(self.suffix)}",
        ]
        return lines


def _preview(text: str, limit: int = 40) -> str:
    raw = text.replace("\n", "\\n")
    if not raw:
        return "(خالی)"
    if len(raw) > limit:
        return repr(raw[:limit] + "…")
    return repr(raw)


def unescape_admin_text(text: str) -> str:
    return text.replace("\\n", "\n")


def _should_drop_entity(entity: Any, cfg: TextFilterConfig) -> bool:
    name = type(entity).__name__
    if cfg.remove_links and name in _LINK_ENTITY_TYPES:
        return True
    if cfg.remove_mentions and name in _MENTION_ENTITY_TYPES:
        return True
    if cfg.remove_hashtags and name in _HASHTAG_ENTITY_TYPES:
        return True
    return False


def _strip_entities(text: str, entities: Iterable[Any] | None, cfg: TextFilterConfig) -> str:
    if not entities:
        return text
    targets = [e for e in entities if _should_drop_entity(e, cfg)]
    if not targets:
        return text

    sur = add_surrogate(text)
    for ent in sorted(targets, key=lambda e: e.offset, reverse=True):
        start = int(ent.offset)
        end = start + int(ent.length)
        if start < 0 or end > len(sur) or start >= end:
            continue
        sur = sur[:start] + " " + sur[end:]
    return del_surrogate(sur)


def apply_text_filter(
    text: str | None,
    cfg: TextFilterConfig,
    entities: Iterable[Any] | None = None,
) -> str:
    body = text or ""
    if not cfg.enabled and not cfg.link_replacements:
        return body

    body = _strip_entities(body, entities, cfg)

    for src, dst in (cfg.link_replacements or {}).items():
        if src:
            body = body.replace(src, dst)

    if cfg.remove_links:
        body = _LINK_RE.sub(" ", body)
    if cfg.remove_mentions:
        body = _MENTION_RE.sub(" ", body)
    if cfg.remove_hashtags:
        body = _HASHTAG_RE.sub(" ", body)
    if cfg.remove_ids:
        body = _ID_RE.sub(" ", body)

    if cfg.collapse_whitespace:
        body = _MULTI_SPACE_RE.sub(" ", body)
        body = _MULTI_NL_RE.sub("\n\n", body)
        body = "\n".join(line.strip() for line in body.splitlines())
        body = body.strip()

    parts: list[str] = []
    if cfg.prefix:
        parts.append(cfg.prefix.rstrip())
    if body:
        parts.append(body)
    if cfg.suffix:
        parts.append(cfg.suffix.lstrip())
    return "\n".join(parts).strip()


def matches_content_rules(text: str | None, cfg: TextFilterConfig) -> bool:
    body = text or ""
    if cfg.allow_enabled and cfg.allow_words:
        hay = body.casefold()
        if not any(w.casefold() in hay for w in cfg.allow_words if str(w).strip()):
            return False
    if cfg.regex_enabled and cfg.regex_pattern.strip():
        try:
            matched = re.search(cfg.regex_pattern, body, re.UNICODE) is not None
        except re.error:
            return True
        if cfg.regex_must_match and not matched:
            return False
        if not cfg.regex_must_match and matched:
            return False
    return True
