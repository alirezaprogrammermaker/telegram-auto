"""Refs to skip in linkdir snowball / search enrich (official Telegram, smoke tests, junk)."""
from __future__ import annotations

import re
from typing import Any

# Lowercase usernames without @ — always skipped unless config disables defaults.
_DEFAULT_USERNAMES: frozenset[str] = frozenset(
    {
        # Official Telegram / Pavel Durov
        "telegram",
        "durov",
        "telegramtips",
        "telegramnews",
        "telegramsupport",
        "botnews",
        "spambot",
        "premiumbot",
        "joinbot",
        "stickers",
        "contest",
        "telegrambot",
        "tginfo",
        "gif",
        "wiki",
        "vodka",
        # Smoke / CI test refs
        "linkdir_py_smoke",
        "linkdir_smoke",
        "py_smoke",
        "catalog_smoke",
    }
)

# Soft title/username hints — skip before resolve when matching.
_SOFT_BLOCK_RE = re.compile(
    r"(?i)\b("
    r"canva|photoshop|netflix|spotify|chatgpt|"
    r"کتاب|book\s*club|دوست[ی]?ابی|dating|"
    r"official\s*news|pavel\s*durov"
    r")\b"
)

_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,}$")


def normalize_username(ref: str | None) -> str | None:
    text = (ref or "").strip()
    if not text:
        return None
    if text.lower().startswith("@"):
        text = text[1:]
    text = text.lower()
    if _USERNAME_RE.fullmatch(text):
        return text
    return None


def blocklist_from_config(cfg: dict[str, Any] | None = None) -> set[str]:
    bl = (cfg or {}).get("blocklist") or {}
    out: set[str] = set()
    if bl.get("use_defaults", True):
        out.update(_DEFAULT_USERNAMES)
    for raw in bl.get("usernames") or []:
        u = normalize_username(str(raw))
        if u:
            out.add(u)
    return out


def is_blocked(ref: str | None, *, cfg: dict[str, Any] | None = None) -> bool:
    u = normalize_username(ref)
    if not u:
        return False
    return u in blocklist_from_config(cfg)


def looks_like_blocked_text(*parts: str | None) -> bool:
    blob = " ".join(str(p or "") for p in parts)
    return bool(blob and _SOFT_BLOCK_RE.search(blob))


def filter_blocked_rows(
    rows: list[dict[str, Any]],
    *,
    cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    blocked = blocklist_from_config(cfg)
    out: list[dict[str, Any]] = []
    for row in rows:
        uname = normalize_username(str(row.get("username") or row.get("ref") or ""))
        if uname and uname in blocked:
            continue
        if looks_like_blocked_text(row.get("title"), row.get("username"), row.get("about")):
            continue
        out.append(row)
    return out


def prefilter_ref(
    ref: str,
    *,
    cfg: dict[str, Any] | None = None,
    title: str | None = None,
) -> bool:
    """Return True if this ref is worth resolving (not blocked / soft-blocked)."""
    if is_blocked(ref, cfg=cfg):
        return False
    if looks_like_blocked_text(ref, title):
        return False
    return True
