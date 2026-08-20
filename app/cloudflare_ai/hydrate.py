"""Hydrate the local Cloudflare AI store from the admin-bot bridge.

GitHub Actions runners start with an empty ``data/`` directory, so
``data/pool/cloudflare_ai.json`` never exists and the provider would find zero
accounts. When ``ADMIN_BOT_BRIDGE_URL``/``ADMIN_BOT_BRIDGE_TOKEN`` are set we
pull the account list from the bot's export endpoint and cache it to the local
JSON file for the rest of the run. Every failure path is silent by design: the
caller gets a store with whatever accounts it already had.
"""

from __future__ import annotations

import logging
from typing import Any

from app.cloudflare_ai.store import CloudflareAIStore

logger = logging.getLogger(__name__)

EXPORT_PATH = "/internal/cfai/export"


def _accounts_from_payload(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """Accept both ``{"store": {...}}`` and flat ``{"accounts": [...]}`` shapes."""
    store = payload.get("store")
    source = store if isinstance(store, dict) else payload
    rows = source.get("accounts")
    if not isinstance(rows, list):
        return [], None
    config = source.get("config")
    default_model = None
    if isinstance(config, dict):
        default_model = str(config.get("default_model") or "") or None
    accounts = [row for row in rows if isinstance(row, dict) and _usable_row(row)]
    return accounts, default_model


def _usable_row(row: dict[str, Any]) -> bool:
    token = str(row.get("api_token") or row.get("api_key") or "").strip()
    acc_id = str(row.get("account_id") or "").strip().lower()
    if not token or not str(row.get("name") or "").strip():
        return False
    return len(acc_id) == 32 and all(c in "0123456789abcdef" for c in acc_id)


def hydrate_from_bridge(store: CloudflareAIStore) -> int:
    """Import accounts from the bridge into ``store``. Returns rows added."""
    try:
        from app.bridge_client import bridge_configured, bridge_request

        if not bridge_configured():
            return 0
        payload = bridge_request(
            "GET", EXPORT_PATH, query={"secrets": 1}, timeout=15.0
        )
        if not payload or not payload.get("ok", True):
            return 0
        accounts, default_model = _accounts_from_payload(payload)
        if not accounts:
            return 0
        added = store.upsert_accounts(accounts)
        if default_model:
            try:
                store.set_default_model(default_model)
            except ValueError:
                pass
        if added:
            logger.info("hydrated %s Cloudflare AI account(s) from bridge", added)
        return added
    except Exception as exc:  # noqa: BLE001 - hydration must never break callers
        logger.warning("Cloudflare AI store hydration failed: %s", exc)
        return 0


def ensure_store(store: CloudflareAIStore | None = None) -> CloudflareAIStore:
    """Return a store guaranteed to have been given a chance at accounts."""
    store = store or CloudflareAIStore()
    if store.usable_accounts():
        return store
    hydrate_from_bridge(store)
    return store
