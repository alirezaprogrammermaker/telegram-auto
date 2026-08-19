"""Shared HTTP client for Cloudflare admin-bot bridge (Bearer token)."""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


def bridge_configured() -> bool:
    base = (os.environ.get("ADMIN_BOT_BRIDGE_URL") or "").rstrip("/")
    token = os.environ.get("ADMIN_BOT_BRIDGE_TOKEN") or ""
    return bool(base and token)


def bridge_request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> dict[str, Any] | None:
    """Call /internal/... on the admin bot. Returns parsed JSON or None."""
    base = (os.environ.get("ADMIN_BOT_BRIDGE_URL") or "").rstrip("/")
    token = os.environ.get("ADMIN_BOT_BRIDGE_TOKEN") or ""
    if not base or not token:
        return None

    url = f"{base}{path if path.startswith('/') else '/' + path}"
    if query:
        qs = urllib.parse.urlencode(
            {k: v for k, v in query.items() if v is not None}
        )
        if qs:
            url = f"{url}?{qs}"

    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        # Explicit UA: default Python-urllib/* is often blocked by CF (403).
        "User-Agent": "telegram-auto-bridge/1.0",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        if not raw:
            return {"ok": True}
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"ok": True, "data": parsed}
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.warning("bridge %s %s failed: %s", method.upper(), path, exc)
        return None
