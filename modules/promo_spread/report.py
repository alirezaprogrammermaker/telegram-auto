"""Best-effort promo delivery reports to admin-bot D1 via bridge webhook."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _account_id() -> str:
    try:
        from app.paths import account_id

        return (account_id() or "").strip().lower()
    except Exception:
        return ""


def report_promo_seen(
    *,
    post_key: str,
    source_ref: str,
    source_id: int,
    message_ids: list[int],
    jobs: list[dict[str, Any]],
    mode: str | None = None,
) -> None:
    """POST /internal/promo/seen — post received + queued targets."""
    aid = _account_id()
    if not aid or not post_key:
        return
    payload = {
        "account_id": aid,
        "post_key": str(post_key),
        "source_ref": source_ref,
        "source_id": int(source_id),
        "message_ids": list(message_ids),
        "total_targets": len(jobs),
        "mode": mode,
        "jobs": jobs,
    }
    _post("/internal/promo/seen", payload)


def report_promo_delivery(
    *,
    job_id: str,
    post_key: str,
    group_ref: str,
    status: str,
    source_ref: str | None = None,
    source_id: int | None = None,
    message_ids: list[int] | None = None,
    group_id: int | None = None,
    error: str | None = None,
    mode: str | None = None,
) -> None:
    """POST /internal/promo/delivery — one group outcome."""
    aid = _account_id()
    if not aid or not job_id or not post_key:
        return
    payload = {
        "account_id": aid,
        "job_id": str(job_id),
        "post_key": str(post_key),
        "group_ref": group_ref,
        "status": status,
        "source_ref": source_ref,
        "source_id": source_id,
        "message_ids": list(message_ids or []),
        "group_id": group_id,
        "error": error,
        "mode": mode,
    }
    _post("/internal/promo/delivery", payload)


def _post(path: str, payload: dict[str, Any]) -> None:
    try:
        from app.bridge_client import bridge_configured, bridge_request

        if not bridge_configured():
            return
        resp = bridge_request("POST", path, payload=payload, timeout=12.0)
        if not resp or not resp.get("ok", True):
            logger.warning("promo report %s soft-fail: %s", path, resp)
    except Exception as exc:  # noqa: BLE001 - never break delivery path
        logger.warning("promo report %s failed: %s", path, exc)
