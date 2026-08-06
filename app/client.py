"""Telegram client factory."""
from __future__ import annotations

from telethon import TelegramClient

from app.config import AppConfig

# Keep these stable across every login. Telegram flags accounts whose
# reported device fingerprint keeps changing between sessions.
DEVICE_MODEL = "EasySeen Desktop"
SYSTEM_VERSION = "Windows 10"
APP_VERSION = "0.1.0"


def build_client(config: AppConfig) -> TelegramClient:
    session_path = str(config.root / config.session_name)
    return TelegramClient(
        session_path,
        config.api_id,
        config.api_hash,
        device_model=DEVICE_MODEL,
        system_version=SYSTEM_VERSION,
        app_version=APP_VERSION,
        lang_code="en",
        system_lang_code="en",
        # Ride out short FLOOD_WAIT penalties instead of erroring out and
        # retrying immediately, which is what escalates into a real ban.
        flood_sleep_threshold=config.flood_sleep_threshold,
        connection_retries=5,
        retry_delay=5,
        request_retries=3,
        auto_reconnect=True,
    )
