"""Application and module configuration."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
MODULES_CONFIG_PATH = ROOT / "config" / "modules.json"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppConfig:
    api_id: int
    api_hash: str
    session_name: str
    phone: str | None
    log_level: str
    lock_file: Path
    root: Path
    modules: dict[str, dict[str, Any]]


def load_app_config() -> AppConfig:
    load_dotenv(ROOT / ".env")

    api_id_raw = os.environ.get("API_ID", "").strip()
    api_hash = os.environ.get("API_HASH", "").strip()
    if not api_id_raw or not api_hash:
        raise RuntimeError("API_ID and API_HASH are required in .env")

    session_name = os.environ.get("SESSION_NAME", "easy_seen").strip() or "easy_seen"
    phone = os.environ.get("PHONE", "").replace(" ", "") or None
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    lock_name = os.environ.get("LOCK_FILE", "telegram_auto.lock")
    lock_file = ROOT / lock_name

    modules = _load_modules_config()
    return AppConfig(
        api_id=int(api_id_raw),
        api_hash=api_hash,
        session_name=session_name,
        phone=phone,
        log_level=log_level,
        lock_file=lock_file,
        root=ROOT,
        modules=modules,
    )


def _load_modules_config() -> dict[str, dict[str, Any]]:
    if not MODULES_CONFIG_PATH.exists():
        logger.warning("Module config missing at %s — no modules will load", MODULES_CONFIG_PATH)
        return {}

    try:
        data = json.loads(MODULES_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Failed to read %s: %s", MODULES_CONFIG_PATH, exc)
        return {}

    modules = data.get("modules")
    if not isinstance(modules, dict):
        logger.error("Invalid modules.json: 'modules' must be an object")
        return {}

    cleaned: dict[str, dict[str, Any]] = {}
    for name, cfg in modules.items():
        if isinstance(cfg, dict):
            cleaned[str(name)] = cfg
        else:
            logger.warning("Ignoring invalid module config for %s", name)
    return cleaned


def module_enabled(cfg: dict[str, Any] | None) -> bool:
    if not cfg:
        return False
    return bool(cfg.get("enabled", False))
