"""Telegram reply keyboard layouts and label → command mapping for admins."""

from __future__ import annotations

from typing import Literal

from telethon import Button

KeyboardMenu = Literal["main", "cfai"]

# --- Main admin menu ---------------------------------------------------------

MAIN_BTN_HELP = "📋 دستورات مدیر"
MAIN_BTN_MODULES = "🧩 وضعیت ماژول"
MAIN_BTN_CFAI = "🤖 Cloudflare AI"

# --- Cloudflare AI submenu ---------------------------------------------------

CFAI_BTN_STATUS = "📊 وضعیت CF AI"
CFAI_BTN_ACCOUNTS = "📋 لیست حساب‌ها"
CFAI_BTN_TEST = "🧪 تست اتصال"
CFAI_BTN_MODEL = "🎯 مدل پیش‌فرض"
CFAI_BTN_HELP = "❓ راهنمای CF AI"
CFAI_BTN_BACK = "⬅️ منوی اصلی"

_KEYBOARD_COMMANDS: dict[str, str] = {
    MAIN_BTN_HELP: "/help",
    MAIN_BTN_MODULES: "/modules",
    CFAI_BTN_STATUS: "/cfai status",
    CFAI_BTN_ACCOUNTS: "/cfai accounts",
    CFAI_BTN_TEST: "/cfai test",
    CFAI_BTN_MODEL: "/cfai model",
    CFAI_BTN_HELP: "/cfai help",
}

_KEYBOARD_NAVIGATION: dict[str, KeyboardMenu] = {
    MAIN_BTN_CFAI: "cfai",
    CFAI_BTN_BACK: "main",
}

_MENU_PROMPTS: dict[KeyboardMenu, str] = {
    "main": "منوی اصلی — از دکمه‌ها یا `/help` استفاده کن.",
    "cfai": (
        "مدیریت Cloudflare Workers AI\n"
        "از دکمه‌ها یا `/cfai help` استفاده کن.\n"
        "افزودن/حذف حساب فقط با دستور slash انجام می‌شود."
    ),
}


def keyboard_rows(menu: KeyboardMenu) -> list[list]:
    """Build Telethon Button rows for the requested menu."""
    if menu == "cfai":
        return [
            [Button.text(CFAI_BTN_STATUS), Button.text(CFAI_BTN_ACCOUNTS)],
            [Button.text(CFAI_BTN_TEST), Button.text(CFAI_BTN_MODEL)],
            [Button.text(CFAI_BTN_HELP)],
            [Button.text(CFAI_BTN_BACK, resize=True)],
        ]
    return [
        [Button.text(MAIN_BTN_HELP), Button.text(MAIN_BTN_MODULES)],
        [Button.text(MAIN_BTN_CFAI, resize=True)],
    ]


def menu_prompt(menu: KeyboardMenu) -> str:
    return _MENU_PROMPTS[menu]


def all_keyboard_labels() -> frozenset[str]:
    return frozenset(_KEYBOARD_COMMANDS) | frozenset(_KEYBOARD_NAVIGATION)


def is_keyboard_label(text: str) -> bool:
    return text.strip() in all_keyboard_labels()


def keyboard_command_for(text: str) -> str | None:
    """Map a button label to an equivalent slash command, if any."""
    return _KEYBOARD_COMMANDS.get(text.strip())


def keyboard_navigation_for(text: str) -> KeyboardMenu | None:
    """Map a button label to a submenu navigation target, if any."""
    return _KEYBOARD_NAVIGATION.get(text.strip())
