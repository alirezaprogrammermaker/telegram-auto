"""Multi-account profiles: which modules each Telegram identity runs."""
from __future__ import annotations

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.paths import ROOT

logger = logging.getLogger(__name__)

ACCOUNTS_REGISTRY = ROOT / "config" / "accounts.json"
ACCOUNTS_DIR = ROOT / "config" / "accounts"


def load_accounts_registry() -> list[dict[str, Any]]:
    if not ACCOUNTS_REGISTRY.exists():
        return []
    try:
        data = json.loads(ACCOUNTS_REGISTRY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Failed to read %s: %s", ACCOUNTS_REGISTRY, exc)
        return []
    rows = data.get("accounts")
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("id")]


def load_account_profile(account_id: str) -> dict[str, Any] | None:
    path = ACCOUNTS_DIR / f"{account_id}.json"
    if not path.exists():
        logger.warning("Account profile missing: %s", path)
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Failed to read account profile %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        return None
    return data


def apply_account_modules(
    base_modules: dict[str, dict[str, Any]],
    account_id: str | None,
) -> dict[str, dict[str, Any]]:
    """Deep-merge account profile module overrides onto base modules.json."""
    if not account_id or account_id == "default":
        return base_modules

    profile = load_account_profile(account_id)
    if not profile:
        return base_modules

    overrides = profile.get("modules")
    if not isinstance(overrides, dict):
        logger.info("Account %s has no module overrides", account_id)
        return base_modules

    merged = deepcopy(base_modules)
    for name, patch in overrides.items():
        if not isinstance(patch, dict):
            continue
        bucket = merged.setdefault(str(name), {})
        if not isinstance(bucket, dict):
            bucket = {}
            merged[str(name)] = bucket
        # Shallow merge is enough for enabled/dry_run toggles; nested route
        # lists stay on base/runtime overlay unless fully replaced.
        for key, value in patch.items():
            if key == "routes" and isinstance(value, list):
                bucket[key] = deepcopy(value)
            elif isinstance(value, dict) and isinstance(bucket.get(key), dict):
                nested = dict(bucket[key])
                nested.update(value)
                bucket[key] = nested
            else:
                bucket[key] = value

    logger.info(
        "Applied account profile %s (%s)",
        account_id,
        profile.get("label") or account_id,
    )
    return merged


def registry_entry(account_id: str) -> dict[str, Any] | None:
    for row in load_accounts_registry():
        if str(row.get("id")) == account_id:
            return row
    return None
