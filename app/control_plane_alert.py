"""Post control-plane alerts to Cloudflare admin-bot (best-effort)."""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


def post_admin_bot_alert(
    *,
    account_id: str,
    message: str,
    severity: str = "warning",
    extra: dict[str, Any] | None = None,
) -> bool:
    """POST /internal/alerts — no-op if bridge env missing."""
    base = (os.environ.get("ADMIN_BOT_BRIDGE_URL") or "").rstrip("/")
    token = os.environ.get("ADMIN_BOT_BRIDGE_TOKEN") or ""
    if not base or not token:
        return False
    payload: dict[str, Any] = {
        "account_id": account_id,
        "message": message,
        "severity": severity,
    }
    if extra:
        payload["extra"] = extra
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/internal/alerts",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            resp.read()
        return True
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("admin-bot alert failed: %s", exc)
        return False
