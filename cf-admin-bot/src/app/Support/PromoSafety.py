"""Pure promo safety config helpers for the Worker (no Telethon)."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any


@dataclass
class SafetyConfig:
    timezone: str = "Asia/Tehran"
    active_days: list[str] = field(
        default_factory=lambda: ["sat", "sun", "mon", "tue", "wed", "thu", "fri"]
    )
    active_windows: list[dict[str, str]] = field(
        default_factory=lambda: [
            {"start": "09:30", "end": "13:00"},
            {"start": "16:00", "end": "22:00"},
        ]
    )
    delay_min_seconds: float = 70.0
    delay_max_seconds: float = 190.0
    delay_bias: float = 0.62
    per_group_cooldown_minutes: int = 50
    hourly_budget: int = 5
    daily_budget: int = 28
    typing_min_seconds: float = 1.8
    typing_max_seconds: float = 5.0
    read_before_send: bool = True
    read_delay_min: float = 4.0
    read_delay_max: float = 14.0
    shuffle_targets: bool = True
    flood_strikes_to_pause: int = 2
    peer_flood_cooldown_hours: int = 24
    circuit_breaker_hours: float = 8.0
    require_member: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "timezone": self.timezone,
            "active_days": list(self.active_days),
            "active_windows": [dict(w) for w in self.active_windows],
            "delay_min_seconds": self.delay_min_seconds,
            "delay_max_seconds": self.delay_max_seconds,
            "delay_bias": self.delay_bias,
            "per_group_cooldown_minutes": self.per_group_cooldown_minutes,
            "hourly_budget": self.hourly_budget,
            "daily_budget": self.daily_budget,
            "typing_min_seconds": self.typing_min_seconds,
            "typing_max_seconds": self.typing_max_seconds,
            "read_before_send": self.read_before_send,
            "read_delay_min": self.read_delay_min,
            "read_delay_max": self.read_delay_max,
            "shuffle_targets": self.shuffle_targets,
            "flood_strikes_to_pause": self.flood_strikes_to_pause,
            "peer_flood_cooldown_hours": self.peer_flood_cooldown_hours,
            "circuit_breaker_hours": self.circuit_breaker_hours,
            "require_member": self.require_member,
        }

    @classmethod
    def from_dict(cls, data: Any) -> SafetyConfig:
        base = cls()
        if not isinstance(data, dict):
            return base
        known = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key in known:
                setattr(base, key, value)
        base.delay_min_seconds = float(base.delay_min_seconds)
        base.delay_max_seconds = float(base.delay_max_seconds)
        if base.delay_max_seconds < base.delay_min_seconds:
            base.delay_max_seconds = base.delay_min_seconds
        base.delay_bias = min(0.95, max(0.05, float(base.delay_bias)))
        base.hourly_budget = max(1, int(base.hourly_budget))
        base.daily_budget = max(1, int(base.daily_budget))
        base.per_group_cooldown_minutes = max(5, int(base.per_group_cooldown_minutes))
        return base

    def summary_lines(self) -> list[str]:
        wins = ", ".join(
            f"{w.get('start', '?')}-{w.get('end', '?')}" for w in self.active_windows
        ) or "—"
        return [
            f"tz={self.timezone}",
            f"delay={self.delay_min_seconds:.0f}–{self.delay_max_seconds:.0f}s "
            f"(bias={self.delay_bias})",
            f"budget: daily {self.daily_budget} · hourly {self.hourly_budget}",
            f"cooldown={self.per_group_cooldown_minutes}m",
            f"windows={wins}",
            f"days={','.join(self.active_days)}",
        ]


def parse_windows(raw: str) -> list[dict[str, str]]:
    windows: list[dict[str, str]] = []
    for part in raw.replace("،", ",").split(","):
        part = part.strip()
        if not part or "-" not in part:
            continue
        start, end = part.split("-", 1)
        windows.append({"start": start.strip(), "end": end.strip()})
    return windows


def apply_safety_command(safety: SafetyConfig, parts: list[str]) -> SafetyConfig:
    if not parts:
        return safety
    sub = parts[0].strip().lower()
    patch = safety.to_dict()

    if sub == "delay" and len(parts) >= 3:
        patch["delay_min_seconds"] = float(parts[1])
        patch["delay_max_seconds"] = float(parts[2])
    elif sub == "budget":
        i = 1
        while i + 1 < len(parts):
            key = parts[i].lower()
            val = int(parts[i + 1])
            if key == "daily":
                patch["daily_budget"] = val
            elif key == "hourly":
                patch["hourly_budget"] = val
            i += 2
    elif sub == "windows" and len(parts) >= 2:
        wins = parse_windows(" ".join(parts[1:]))
        if not wins:
            raise ValueError("bad windows format")
        patch["active_windows"] = wins
    elif sub == "cooldown" and len(parts) >= 2:
        patch["per_group_cooldown_minutes"] = int(parts[1])
    elif sub == "tz" and len(parts) >= 2:
        patch["timezone"] = parts[1]
    elif sub == "days" and len(parts) >= 2:
        days = [
            p.strip().lower()[:3]
            for p in " ".join(parts[1:]).replace("،", ",").split(",")
            if p.strip()
        ]
        if not days:
            raise ValueError("bad days")
        patch["active_days"] = days
    else:
        raise ValueError(f"unknown safety command: {sub}")

    return SafetyConfig.from_dict(patch)
