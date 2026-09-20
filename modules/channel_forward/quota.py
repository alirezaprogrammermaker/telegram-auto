"""Shared per-destination daily publish cap (calendar day in route timezone)."""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.paths import data_path
from app.storage import load_json, save_json

DEFAULT_TIMEZONE = "Asia/Tehran"
_lock = threading.Lock()


def dest_quota_key(dest_ref: Any) -> str:
    if isinstance(dest_ref, int):
        return str(dest_ref)
    text = str(dest_ref or "").strip()
    if text.startswith("@"):
        text = text[1:]
    return text.lower()


def calendar_day(timezone: str, *, at: datetime | None = None) -> str:
    try:
        tz = ZoneInfo(timezone or DEFAULT_TIMEZONE)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo(DEFAULT_TIMEZONE)
    moment = at or datetime.now(tz)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz)
    else:
        moment = moment.astimezone(tz)
    return moment.date().isoformat()


class DailyQuotaStore:
    """Count successful publishes per destination per calendar day.

    Routes that share a destination share this counter, so ``max_posts_per_day``
    on each route is enforced as a destination-wide cap.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_path("daily_quota.json")
        self._data: dict[str, Any] = load_json(self.path, {"dests": {}})

    def _save(self) -> None:
        save_json(self.path, self._data)

    def _reload(self) -> dict[str, Any]:
        self._data = load_json(self.path, {"dests": {}})
        dests = self._data.setdefault("dests", {})
        if not isinstance(dests, dict):
            dests = {}
            self._data["dests"] = dests
        return dests

    def _prune(self, dests: dict[str, Any], *, keep_days: int = 14) -> None:
        keep = max(1, keep_days)
        for key, days in list(dests.items()):
            if not isinstance(days, dict):
                dests.pop(key, None)
                continue
            for old in sorted(days)[:-keep]:
                days.pop(old, None)
            if not days:
                dests.pop(key, None)

    def count(
        self,
        dest_key: str,
        *,
        timezone: str = DEFAULT_TIMEZONE,
        at: datetime | None = None,
    ) -> int:
        day = calendar_day(timezone, at=at)
        with _lock:
            dests = self._reload()
            bucket = dests.get(dest_key) or {}
            try:
                return int(bucket.get(day) or 0)
            except (TypeError, ValueError):
                return 0

    def at_limit(
        self,
        dest_key: str,
        *,
        limit: int,
        timezone: str = DEFAULT_TIMEZONE,
        at: datetime | None = None,
    ) -> bool:
        if limit <= 0:
            return False
        return self.count(dest_key, timezone=timezone, at=at) >= limit

    def try_consume(
        self,
        dest_key: str,
        *,
        limit: int,
        timezone: str = DEFAULT_TIMEZONE,
        at: datetime | None = None,
    ) -> bool:
        """Reserve one successful-publish slot. No-op (allowed) when limit <= 0."""
        if limit <= 0:
            return True
        day = calendar_day(timezone, at=at)
        with _lock:
            dests = self._reload()
            bucket = dests.setdefault(dest_key, {})
            try:
                current = int(bucket.get(day) or 0)
            except (TypeError, ValueError):
                current = 0
            if current >= limit:
                return False
            bucket[day] = current + 1
            self._prune(dests)
            self._save()
            return True

    def refund(
        self,
        dest_key: str,
        *,
        timezone: str = DEFAULT_TIMEZONE,
        at: datetime | None = None,
    ) -> None:
        day = calendar_day(timezone, at=at)
        with _lock:
            dests = self._reload()
            bucket = dests.get(dest_key)
            if not isinstance(bucket, dict):
                return
            try:
                current = int(bucket.get(day) or 0)
            except (TypeError, ValueError):
                current = 0
            if current <= 1:
                bucket.pop(day, None)
            else:
                bucket[day] = current - 1
            if not bucket:
                dests.pop(dest_key, None)
            self._save()
