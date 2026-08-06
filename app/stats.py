"""Persistent daily counters for forward/filter/schedule events."""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.config import ROOT
from app.storage import load_json, save_json

_DEFAULT_TZ = "Asia/Tehran"
_lock = threading.Lock()


class StatsStore:
    def __init__(self, path: Path | None = None, timezone: str = _DEFAULT_TZ) -> None:
        self.path = path or (ROOT / "data" / "stats.json")
        self.timezone = timezone
        self._data: dict[str, Any] = load_json(self.path, {"days": {}})

    def _today_key(self) -> str:
        try:
            tz = ZoneInfo(self.timezone)
        except Exception:
            tz = ZoneInfo(_DEFAULT_TZ)
        return datetime.now(tz).date().isoformat()

    def _ensure_day(self, day: str) -> dict[str, Any]:
        days = self._data.setdefault("days", {})
        bucket = days.setdefault(
            day,
            {
                "forwarded": 0,
                "blocked": 0,
                "queued": 0,
                "published_scheduled": 0,
                "filtered_copy": 0,
                "routes": {},
            },
        )
        return bucket

    def incr(self, metric: str, *, route: str | None = None, amount: int = 1) -> None:
        with _lock:
            day = self._today_key()
            bucket = self._ensure_day(day)
            bucket[metric] = int(bucket.get(metric, 0)) + amount
            if route:
                routes = bucket.setdefault("routes", {})
                r = routes.setdefault(
                    route,
                    {
                        "forwarded": 0,
                        "blocked": 0,
                        "queued": 0,
                        "published_scheduled": 0,
                    },
                )
                r[metric] = int(r.get(metric, 0)) + amount
            # keep last ~60 days
            keys = sorted(self._data.get("days", {}))
            for old in keys[:-60]:
                self._data["days"].pop(old, None)
            save_json(self.path, self._data)

    def summary(self, *, days: int = 1) -> str:
        with _lock:
            self._data = load_json(self.path, {"days": {}})
            all_days = sorted(self._data.get("days", {}), reverse=True)[: max(1, days)]
            if not all_days:
                return "📊 آمار: هنوز داده‌ای نیست."

            lines = [f"📊 آمار ({self.timezone})", "────────────"]
            for day in all_days:
                b = self._ensure_day(day)
                lines.append(f"📅 {day}")
                lines.append(f"• ارسال‌شده: {b.get('forwarded', 0)}")
                lines.append(f"• بلاک‌شده: {b.get('blocked', 0)}")
                lines.append(f"• صف زمان‌بندی: {b.get('queued', 0)}")
                lines.append(f"• انتشار از صف: {b.get('published_scheduled', 0)}")
                routes = b.get("routes") or {}
                if routes:
                    lines.append("  مسیرها:")
                    for name, vals in list(routes.items())[:10]:
                        lines.append(
                            f"  - `{name}` fwd={vals.get('forwarded', 0)} "
                            f"block={vals.get('blocked', 0)} "
                            f"queue={vals.get('queued', 0)}"
                        )
                lines.append("")
            return "\n".join(lines).strip()
