"""Unique Telegram button labels for the help UI (never collide with feature menus)."""
from __future__ import annotations

from typing import Any

from app.Support.Lang import __

# Every help keyboard button starts with this — feature menus must not use it.
HELP_PREFIX = "❓ "

CATEGORY_LANG_KEYS: dict[str, str] = {
    "general": "help.btn_cat_general",
    "discovery": "help.btn_cat_discovery",
    "promo": "help.btn_cat_promo",
    "forward": "help.btn_cat_forward",
}


def category_button(category: str, row: dict[str, Any] | None = None) -> str:
    key = CATEGORY_LANG_KEYS.get(category)
    if key:
        label = __(key)
        if label != key:
            return label
    if row:
        emoji = row.get("emoji") or "📄"
        title = row.get("title") or category
        return f"{HELP_PREFIX}{emoji} {title}"
    return f"{HELP_PREFIX}{category}"


def topic_button(guide: Any) -> str:
    emoji = guide.get("emoji") or "📄"
    title = guide.get("title") or guide.get("key") or "?"
    return f"{HELP_PREFIX}{emoji} {title}"


def is_help_button(text: str) -> bool:
    return (text or "").strip().startswith(HELP_PREFIX)


def back_hub_button() -> str:
    return __("help.btn_back_hub")


def back_panel_button() -> str:
    return __("help.btn_back_panel")


def back_main_button() -> str:
    return __("help.btn_back_main")
