"""Application and module configuration."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.accounts import apply_account_modules
from app.paths import ROOT, account_id, data_dir, ensure_data_dir, lock_file_path, runtime_modules_path

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
    flood_sleep_threshold: int
    account_id: str
    data_dir: Path


def load_app_config() -> AppConfig:
    load_dotenv(ROOT / ".env")
    ensure_data_dir()

    api_id_raw = os.environ.get("API_ID", "").strip()
    api_hash = os.environ.get("API_HASH", "").strip()
    if not api_id_raw or not api_hash:
        raise RuntimeError("API_ID and API_HASH are required in .env")

    session_name = os.environ.get("SESSION_NAME", "easy_seen").strip() or "easy_seen"
    phone = os.environ.get("PHONE", "").replace(" ", "") or None
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    acc = account_id()

    try:
        flood_threshold = int(os.environ.get("FLOOD_SLEEP_THRESHOLD", "120"))
    except ValueError:
        flood_threshold = 120

    modules = _load_modules_config()
    modules = apply_account_modules(modules, acc)

    logger.info(
        "Config account_id=%s session=%s data_dir=%s",
        acc,
        session_name,
        data_dir(),
    )

    return AppConfig(
        api_id=int(api_id_raw),
        api_hash=api_hash,
        session_name=session_name,
        phone=phone,
        log_level=log_level,
        lock_file=lock_file_path(),
        root=ROOT,
        modules=modules,
        flood_sleep_threshold=max(0, flood_threshold),
        account_id=acc,
        data_dir=data_dir(),
    )


def _load_modules_config() -> dict[str, dict[str, Any]]:
    # Prefer runtime overlay (persisted under data/) so routes added via chat
    # survive GitHub Actions job restarts. Fall back to repo config.
    for path in (runtime_modules_path(), MODULES_CONFIG_PATH):
        loaded = _read_modules_file(path)
        if loaded is not None:
            if path == runtime_modules_path():
                logger.info("Loaded module config from runtime overlay %s", path)
            return loaded

    logger.warning("Module config missing — no modules will load")
    return {}


def _read_modules_file(path: Path) -> dict[str, dict[str, Any]] | None:
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Failed to read %s: %s", path, exc)
        return None

    modules = data.get("modules")
    if not isinstance(modules, dict):
        logger.error("Invalid modules file %s: 'modules' must be an object", path)
        return None

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
