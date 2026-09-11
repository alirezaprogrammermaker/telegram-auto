"""Phone helpers for D1 storage vs Telegram bot UI.

Account phone numbers are stored in D1 ``accounts.phone_e164`` (full E.164).
``phone_mask`` is a derived column for non-UI/log contexts only.

GitHub secrets hold Telethon session blobs (``TELEGRAM_SESSION_B64*``), not
the phone number. Temporary ``LOGIN_PHONE`` is a manage.ps1 fallback only.
"""
from __future__ import annotations


def mask_phone(phone: str | None) -> str:
    """Mask a number for non-UI storage/logs (e.g. ``+98***11``)."""
    if not phone:
        return ""
    digits = phone.strip()
    if len(digits) <= 4:
        return "***"
    return digits[:3] + "***" + digits[-2:]


def phone_for_ui(*candidates: str | None) -> str:
    """First non-empty full phone for Telegram UI. Never returns a mask."""
    for raw in candidates:
        text = str(raw or "").strip()
        if not text or text in {"-", "***"}:
            continue
        if "***" in text:
            continue
        return text
    return "-"
