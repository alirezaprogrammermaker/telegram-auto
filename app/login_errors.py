"""Parse and report Telegram login failures (especially FloodWait) to the admin bot."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_FLOOD_RE = re.compile(r"^flood_wait:(\d+)(?::until=(\S+))?$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def format_flood_wait_error(wait_seconds: int, *, now: datetime | None = None) -> str:
    wait = max(0, int(wait_seconds))
    until = (now or utc_now()) + timedelta(seconds=wait)
    return f"flood_wait:{wait}:until={until.isoformat()}"


def parse_flood_wait(error: str | None) -> dict[str, Any] | None:
    raw = str(error or "").strip()
    match = _FLOOD_RE.match(raw)
    if not match:
        return None
    wait = int(match.group(1))
    until_raw = match.group(2)
    until: datetime | None = None
    if until_raw:
        try:
            until = datetime.fromisoformat(until_raw.replace("Z", "+00:00"))
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
        except ValueError:
            until = None
    return {"wait_seconds": wait, "until": until}


def remaining_flood_wait(error: str | None, *, now: datetime | None = None) -> int | None:
    parsed = parse_flood_wait(error)
    if not parsed:
        return None
    stamp = now or utc_now()
    until = parsed.get("until")
    if isinstance(until, datetime):
        left = int((until - stamp).total_seconds())
        return max(0, left)
    return max(0, int(parsed["wait_seconds"]))


def wait_label(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes = max(1, rem // 60) if seconds else 0
    if hours and rem % 60 and minutes == 0:
        minutes = 1
    if hours:
        return f"{hours} ساعت و {minutes} دقیقه" if minutes else f"{hours} ساعت"
    if seconds < 60:
        return f"{seconds} ثانیه"
    return f"{minutes} دقیقه"


def report_login_result(account_id: str, result: dict[str, Any]) -> None:
    """Best-effort POST so jellymanagerbot can show FloodWait instead of workflow_failure."""
    aid = (account_id or "").strip()
    if not aid or not result:
        return
    try:
        from app.bridge_client import bridge_configured, bridge_request

        if not bridge_configured():
            return
        payload = {
            "status": result.get("status"),
            "error": result.get("error"),
            "wait_seconds": result.get("wait_seconds"),
            "hint": result.get("hint"),
            "action": result.get("action") or "send",
        }
        bridge_request("POST", f"/internal/login/{aid}/result", payload=payload, timeout=15.0)
    except Exception as exc:  # noqa: BLE001 - reporting must never break login
        logger.warning("login result report failed: %s", exc)
