"""Telegram client factory."""
from __future__ import annotations

from telethon import TelegramClient

from app.config import AppConfig


def build_client(config: AppConfig) -> TelegramClient:
    session_path = str(config.root / config.session_name)
    return TelegramClient(
        session_path,
        config.api_id,
        config.api_hash,
        device_model="EasySeen Desktop",
        system_version="Windows 10",
        app_version="0.1.0",
        lang_code="en",
        system_lang_code="en",
    )
