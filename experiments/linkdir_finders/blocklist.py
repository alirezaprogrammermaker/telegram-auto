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
        # Smoke / CI test refs
        "linkdir_py_smoke",
        "linkdir_smoke",
        "py_smoke",
        "catalog_smoke",
    }
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
        out.append(row)
    return out
