"""Anti-spam pacing, budgets, quiet hours, and circuit breaker.

Designed so outbound traffic looks like a person manually sharing posts:
randomized gaps, active hours, per-group cooldowns, and hard stop on PeerFlood.
"""
from __future__ import annotations

import logging
import random
import threading
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.paths import data_path
from app.storage import load_json, save_json

logger = logging.getLogger(__name__)

_DAY_ALIASES = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


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
    delay_bias: float = 0.62  # >0.5 prefers longer gaps (more human)
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
        for key, value in data.items():
            if hasattr(base, key):
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


class SafetyGuard:
    """Persistent pacing / health state under data/promo_safety.json."""

    def __init__(self, cfg: SafetyConfig, path: Path | None = None) -> None:
        self.cfg = cfg
        self.path = path or data_path("promo_safety.json")
        self._lock = threading.Lock()
        self._data = load_json(
            self.path,
            {
                "sends": [],
                "group_last": {},
                "flood_strikes": 0,
                "paused_until": None,
                "pause_reason": None,
            },
        )

    def _save(self) -> None:
        save_json(self.path, self._data)

    def _tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.cfg.timezone)
        except Exception:
            return ZoneInfo("Asia/Tehran")

    def now(self) -> datetime:
        return datetime.now(self._tz())

    def _parse_hhmm(self, raw: str) -> dt_time | None:
        try:
            h, m = str(raw).strip().split(":", 1)
            return dt_time(int(h), int(m))
        except (ValueError, TypeError):
            return None

    def is_active_now(self) -> tuple[bool, str]:
        paused, reason = self.circuit_status()
        if paused:
            return False, reason or "circuit open"
        now = self.now()
        day_name = next(
            (k for k, v in _DAY_ALIASES.items() if v == now.weekday()),
            None,
        )
        allowed_days = {str(d).strip().lower()[:3] for d in self.cfg.active_days}
        if day_name and day_name not in allowed_days:
            return False, f"روز غیرفعال ({day_name})"

        windows = self.cfg.active_windows or []
        if not windows:
            return True, "ok"
        t = now.time().replace(second=0, microsecond=0)
        for win in windows:
            start = self._parse_hhmm(win.get("start", ""))
            end = self._parse_hhmm(win.get("end", ""))
            if start is None or end is None:
                continue
            if start <= end and start <= t <= end:
                return True, "ok"
            if start > end and (t >= start or t <= end):  # overnight
                return True, "ok"
        return False, "خارج از بازهٔ فعال"

    def circuit_status(self) -> tuple[bool, str | None]:
        with self._lock:
            self._data = load_json(self.path, self._data)
            raw = self._data.get("paused_until")
            if not raw:
                return False, None
            try:
                until = datetime.fromisoformat(str(raw))
                if until.tzinfo is None:
                    until = until.replace(tzinfo=timezone.utc)
                until_local = until.astimezone(self._tz())
            except ValueError:
                return False, None
            if self.now() < until_local:
                return True, self._data.get("pause_reason") or f"paused until {until_local:%H:%M}"
            self._data["paused_until"] = None
            self._data["pause_reason"] = None
            self._data["flood_strikes"] = 0
            self._save()
            return False, None

    def open_circuit(self, reason: str, hours: float | None = None) -> None:
        hrs = float(hours if hours is not None else self.cfg.circuit_breaker_hours)
        until = datetime.now(timezone.utc) + timedelta(hours=max(0.25, hrs))
        with self._lock:
            self._data = load_json(self.path, self._data)
            self._data["paused_until"] = until.isoformat()
            self._data["pause_reason"] = reason
            self._save()
        logger.warning("promo circuit OPEN for %.1fh: %s", hrs, reason)
        try:
            from app.control_plane_alert import post_admin_bot_alert
            from app.paths import account_id as current_account_id

            post_admin_bot_alert(
                account_id=current_account_id(),
                message=f"promo circuit OPEN ({hrs:.1f}h): {reason}",
                severity="critical",
            )
        except Exception:
            logger.debug("control-plane alert skipped", exc_info=True)

    def note_flood_wait(self, seconds: int) -> None:
        with self._lock:
            self._data = load_json(self.path, self._data)
            strikes = int(self._data.get("flood_strikes") or 0) + 1
            self._data["flood_strikes"] = strikes
            self._save()
        logger.warning("promo FloodWait %ss (strike %s)", seconds, strikes)
        if strikes >= int(self.cfg.flood_strikes_to_pause):
            self.open_circuit(
                f"FloodWait ×{strikes} — cooldown خودکار",
                hours=self.cfg.circuit_breaker_hours,
            )

    def note_peer_flood(self) -> None:
        self.open_circuit(
            "PeerFlood — توقف ۲۴ساعته برای سلامت اکانت",
            hours=float(self.cfg.peer_flood_cooldown_hours),
        )

    def note_success(self, group_key: str) -> None:
        now_utc = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._data = load_json(self.path, self._data)
            sends = self._data.setdefault("sends", [])
            sends.append({"at": now_utc, "group": group_key})
            cutoff = datetime.now(timezone.utc) - timedelta(days=3)
            kept = []
            for item in sends:
                try:
                    ts = datetime.fromisoformat(str(item.get("at")))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts >= cutoff:
                        kept.append(item)
                except ValueError:
                    continue
            self._data["sends"] = kept[-2000:]
            self._data.setdefault("group_last", {})[group_key] = now_utc
            # Successful send cools flood strikes gradually
            strikes = int(self._data.get("flood_strikes") or 0)
            if strikes > 0:
                self._data["flood_strikes"] = strikes - 1
            self._save()

    def _count_since(self, since: datetime) -> int:
        with self._lock:
            self._data = load_json(self.path, self._data)
            n = 0
            for item in self._data.get("sends") or []:
                try:
                    ts = datetime.fromisoformat(str(item.get("at")))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts >= since:
                        n += 1
                except ValueError:
                    continue
            return n

    def budget_ok(self) -> tuple[bool, str]:
        now = datetime.now(timezone.utc)
        hourly = self._count_since(now - timedelta(hours=1))
        daily = self._count_since(now - timedelta(hours=24))
        if hourly >= self.cfg.hourly_budget:
            return False, f"سقف ساعتی ({hourly}/{self.cfg.hourly_budget})"
        if daily >= self.cfg.daily_budget:
            return False, f"سقف روزانه ({daily}/{self.cfg.daily_budget})"
        return True, "ok"

    def group_cooldown_ok(self, group_key: str) -> tuple[bool, str]:
        with self._lock:
            self._data = load_json(self.path, self._data)
            raw = (self._data.get("group_last") or {}).get(group_key)
        if not raw:
            return True, "ok"
        try:
            ts = datetime.fromisoformat(str(raw))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except ValueError:
            return True, "ok"
        delta = datetime.now(timezone.utc) - ts
        need = timedelta(minutes=self.cfg.per_group_cooldown_minutes)
        if delta < need:
            left = int((need - delta).total_seconds() // 60) + 1
            return False, f"کول‌داون گروه (~{left} دقیقه)"
        return True, "ok"

    def human_delay_seconds(self) -> float:
        lo = float(self.cfg.delay_min_seconds)
        hi = float(self.cfg.delay_max_seconds)
        bias = float(self.cfg.delay_bias)
        # Beta-like skew via power of uniform
        u = random.random() ** (1.0 / max(0.05, bias))
        return lo + (hi - lo) * min(1.0, max(0.0, u))

    def typing_seconds(self) -> float:
        return random.uniform(
            float(self.cfg.typing_min_seconds),
            float(self.cfg.typing_max_seconds),
        )

    def read_delay_seconds(self) -> float:
        if not self.cfg.read_before_send:
            return 0.0
        return random.uniform(
            float(self.cfg.read_delay_min),
            float(self.cfg.read_delay_max),
        )

    def summary_lines(self) -> list[str]:
        active, why = self.is_active_now()
        ok_b, why_b = self.budget_ok()
        now = datetime.now(timezone.utc)
        hourly = self._count_since(now - timedelta(hours=1))
        daily = self._count_since(now - timedelta(hours=24))
        paused, pause_why = self.circuit_status()
        return [
            f"active_now: {'YES' if active else 'NO'} ({why})",
            f"budget: hour {hourly}/{self.cfg.hourly_budget} · day {daily}/{self.cfg.daily_budget}"
            + ("" if ok_b else f" — {why_b}"),
            f"circuit: {'OPEN — ' + str(pause_why) if paused else 'closed'}",
            f"delay: {self.cfg.delay_min_seconds:.0f}–{self.cfg.delay_max_seconds:.0f}s (bias={self.cfg.delay_bias})",
            f"group cooldown: {self.cfg.per_group_cooldown_minutes}m",
            f"windows: {self.cfg.active_windows}",
            f"tz: {self.cfg.timezone}",
        ]
