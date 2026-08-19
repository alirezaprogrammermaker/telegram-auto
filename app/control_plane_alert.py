"""Post control-plane alerts to Cloudflare admin-bot (best-effort)."""
from __future__ import annotations

import logging
from typing import Any

from app.bridge_client import bridge_request

logger = logging.getLogger(__name__)


def post_admin_bot_alert(
    *,
    account_id: str,
    message: str,
    severity: str = "warning",
    extra: dict[str, Any] | None = None,
) -> bool:
    """POST /internal/alerts — no-op if bridge env missing."""
    payload: dict[str, Any] = {
        "account_id": account_id,
        "message": message,
        "severity": severity,
    }
    if extra:
        payload["extra"] = extra
    resp = bridge_request("POST", "/internal/alerts", payload=payload, timeout=12.0)
    return bool(resp and resp.get("ok", True))
