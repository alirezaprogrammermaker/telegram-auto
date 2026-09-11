"""Admin-bot UI must show full E.164 phones, not D1 phone_mask."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHONE_DISPLAY = ROOT / "cf-admin-bot" / "src" / "app" / "Support" / "PhoneDisplay.py"
MESSAGES = ROOT / "cf-admin-bot" / "src" / "lang" / "fa" / "messages.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


phone_display = _load(PHONE_DISPLAY, "phone_display")
messages = _load(MESSAGES, "fa_messages")


def test_mask_phone_still_masks_for_storage() -> None:
    assert phone_display.mask_phone("+989123456711") == "+98***11"
    assert phone_display.mask_phone("123") == "***"
    assert phone_display.mask_phone("") == ""
    assert phone_display.mask_phone(None) == ""


def test_phone_for_ui_prefers_full_e164() -> None:
    assert (
        phone_display.phone_for_ui("+989123456711", "+98***11") == "+989123456711"
    )


def test_phone_for_ui_skips_masks_and_placeholders() -> None:
    assert phone_display.phone_for_ui("+98***11", "-", "***") == "-"
    assert phone_display.phone_for_ui(None, "", "-") == "-"
    assert phone_display.phone_for_ui("  +1-555-0100  ") == "+1-555-0100"


def test_account_list_and_manage_templates_render_full_phone() -> None:
    full = "+989123456711"
    masked = phone_display.mask_phone(full)
    listed = messages.MESSAGES["accounts.list_line"].format(
        id="forwarder1",
        label="Forwarder 1",
        role="forward",
        status="ready",
        phone=phone_display.phone_for_ui(full, masked),
    )
    detail = messages.MESSAGES["accounts.manage_detail"].format(
        id="forwarder1",
        label="Forwarder 1",
        role="forward",
        status="ready",
        enabled=True,
        phone=phone_display.phone_for_ui(full, masked),
    )
    status = messages.MESSAGES["status.line"].format(
        id="forwarder1",
        on="✅ فعال",
        role="forward",
        status="ready",
        phone=phone_display.phone_for_ui(full, masked),
        live="📡 ok",
        run="موفق ✅",
        url="",
    )
    await_otp = messages.MESSAGES["accounts.await_otp"].format(
        account_id="forwarder1",
        phone=phone_display.phone_for_ui(full),
        run_id="1",
    )
    for text in (listed, detail, status, await_otp):
        assert full in text
        assert masked not in text
        assert "***" not in text
