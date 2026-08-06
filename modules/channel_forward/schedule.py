"""Per-route publish schedule with timezone support."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Asia/Tehran"

_DAY_ALIASES: dict[str, int] = {
    "mon": 0,
    "monday": 0,
    "دوشنبه": 0,
    "tue": 1,
    "tuesday": 1,
    "سه‌شنبه": 1,
    "سهشنبه": 1,
    "wed": 2,
    "wednesday": 2,
    "چهارشنبه": 2,
    "thu": 3,
    "thursday": 3,
    "پنجشنبه": 3,
    "fri": 4,
    "friday": 4,
    "جمعه": 4,
    "sat": 5,
    "saturday": 5,
    "شنبه": 5,
    "sun": 6,
    "sunday": 6,
    "یکشنبه": 6,
}

_DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _parse_hhmm(value: str) -> time:
    text = value.strip()
    hour_s, minute_s = text.split(":", 1)
    hour = int(hour_s)
    minute = int(minute_s)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid time: {value}")
    return time(hour=hour, minute=minute)


@dataclass
class ScheduleWindow:
    start: str  # HH:MM
    end: str  # HH:MM

    def contains(self, now_t: time) -> bool:
        start_t = _parse_hhmm(self.start)
        end_t = _parse_hhmm(self.end)
        if start_t <= end_t:
            return start_t <= now_t <= end_t
        # overnight window e.g. 22:00-02:00
        return now_t >= start_t or now_t <= end_t

    def to_dict(self) -> dict[str, str]:
        return {"start": self.start, "end": self.end}

    @classmethod
    def from_dict(cls, data: Any) -> ScheduleWindow | None:
        if not isinstance(data, dict):
            return None
        start = str(data.get("start") or "").strip()
        end = str(data.get("end") or "").strip()
        if not start or not end:
            return None
        _parse_hhmm(start)
        _parse_hhmm(end)
        return cls(start=start, end=end)


@dataclass
class ScheduleConfig:
    enabled: bool = False
    timezone: str = DEFAULT_TIMEZONE
    days: list[str] = field(default_factory=lambda: list(_DAY_NAMES))
    windows: list[ScheduleWindow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "timezone": self.timezone,
            "days": list(self.days),
            "windows": [w.to_dict() for w in self.windows],
        }

    @classmethod
    def from_dict(cls, data: Any) -> ScheduleConfig:
        if not isinstance(data, dict):
            return cls()
        days_raw = data.get("days") or list(_DAY_NAMES)
        days: list[str] = []
        for item in days_raw:
            key = str(item).strip().lower()
            if key in _DAY_ALIASES:
                days.append(_DAY_NAMES[_DAY_ALIASES[key]])
            elif key in _DAY_NAMES:
                days.append(key)
        if not days:
            days = list(_DAY_NAMES)

        windows: list[ScheduleWindow] = []
        for item in data.get("windows") or []:
            win = ScheduleWindow.from_dict(item)
            if win:
                windows.append(win)

        tz = str(data.get("timezone") or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
        try:
            ZoneInfo(tz)
        except ZoneInfoNotFoundError:
            tz = DEFAULT_TIMEZONE

        return cls(
            enabled=bool(data.get("enabled", False)),
            timezone=tz,
            days=days,
            windows=windows,
        )

    def tzinfo(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            return ZoneInfo(DEFAULT_TIMEZONE)

    def now(self) -> datetime:
        return datetime.now(self.tzinfo())

    def is_open(self, at: datetime | None = None) -> bool:
        if not self.enabled:
            return True
        if not self.windows:
            # enabled but no windows → treat as closed until configured
            return False
        moment = at or self.now()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=self.tzinfo())
        else:
            moment = moment.astimezone(self.tzinfo())

        day_name = _DAY_NAMES[moment.weekday()]
        if day_name not in self.days:
            return False
        now_t = moment.timetz().replace(tzinfo=None)
        return any(window.contains(now_t) for window in self.windows)

    def summary_lines(self) -> list[str]:
        lines = [
            f"enabled: {'ON' if self.enabled else 'OFF'}",
            f"timezone: {self.timezone}",
            f"days: {', '.join(self.days) if self.days else '(none)'}",
        ]
        if not self.windows:
            lines.append("windows: (none)")
        else:
            for w in self.windows:
                lines.append(f"window: {w.start}-{w.end}")
        open_now = self.is_open()
        lines.append(f"now_open: {'YES' if open_now else 'NO'} ({self.now().strftime('%Y-%m-%d %H:%M')})")
        return lines


def parse_days_csv(text: str) -> list[str]:
    parts = [p.strip().lower() for p in text.replace("،", ",").split(",") if p.strip()]
    out: list[str] = []
    for part in parts:
        if part in _DAY_ALIASES:
            name = _DAY_NAMES[_DAY_ALIASES[part]]
        elif part in _DAY_NAMES:
            name = part
        else:
            raise ValueError(f"روز نامعتبر: {part}")
        if name not in out:
            out.append(name)
    if not out:
        raise ValueError("حداقل یک روز لازم است")
    return out


def parse_windows_csv(text: str) -> list[ScheduleWindow]:
    """Parse '09:00-12:00,18:00-22:00'."""
    chunks = [c.strip() for c in text.replace("،", ",").split(",") if c.strip()]
    windows: list[ScheduleWindow] = []
    for chunk in chunks:
        if "-" not in chunk:
            raise ValueError(f"بازه نامعتبر: {chunk} (مثال 09:00-12:00)")
        start, end = chunk.split("-", 1)
        windows.append(ScheduleWindow(start=start.strip(), end=end.strip()))
        _parse_hhmm(windows[-1].start)
        _parse_hhmm(windows[-1].end)
    if not windows:
        raise ValueError("حداقل یک بازه ساعت لازم است")
    return windows
