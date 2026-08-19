"""Anti-ban guardrails for linkdir discovery experiments.

Design goals:
- Prefer read-only + CheckChatInvite peek (never join by default)
- Hard daily budgets persisted under data/pool/
- Jittered delays, FloodWait / PeerFlood circuit breaker
- Stop early instead of pushing Telegram limits
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import date, datetime, timezone
from typing import Any

from app.paths import ensure_pool_dir, pool_path
from app.storage import load_json, save_json

logger = logging.getLogger("linkdir_finders.safety")

SAFETY_FILE = "linkdir_safety.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _today() -> str:
    return date.today().isoformat()


class SafetyGuard:
    """Persistent rate / budget / circuit controller."""

    def __init__(
        self,
        cfg: dict[str, Any] | None = None,
        *,
        collector_id: str | None = None,
    ) -> None:
        ensure_pool_dir()
        cid = (collector_id or "").strip().lower()
        if cid:
            self.path = pool_path(f"linkdir_safety_{cid}.json")
        else:
            self.path = pool_path(SAFETY_FILE)
        self.collector_id = cid or None
        self.cfg = dict(cfg or {})
        self._data = load_json(
            self.path,
            {
                "version": 1,
                "collector_id": self.collector_id,
                "day": _today(),
                "counters": {},
                "circuit_until": None,
                "circuit_reason": None,
                "history": [],
            },
        )
        self._rollover_day()

    # ---- config helpers ----
    def _f(self, key: str, default: float) -> float:
        try:
            return float(self.cfg.get(key, default))
        except (TypeError, ValueError):
            return default

    def _i(self, key: str, default: int) -> int:
        try:
            return int(self.cfg.get(key, default))
        except (TypeError, ValueError):
            return default

    def _b(self, key: str, default: bool) -> bool:
        return bool(self.cfg.get(key, default))

    def _rollover_day(self) -> None:
        today = _today()
        if self._data.get("day") != today:
            self._data["day"] = today
            self._data["counters"] = {}
            self._save()

    def _save(self) -> None:
        self._data["updated_at"] = utc_now()
        save_json(self.path, self._data)

    def counters(self) -> dict[str, int]:
        self._rollover_day()
        raw = self._data.get("counters") or {}
        return {str(k): int(v) for k, v in raw.items()} if isinstance(raw, dict) else {}

    def _bump(self, name: str, n: int = 1) -> int:
        self._rollover_day()
        counters = self._data.setdefault("counters", {})
        if not isinstance(counters, dict):
            counters = {}
            self._data["counters"] = counters
        counters[name] = int(counters.get(name) or 0) + n
        self._save()
        return int(counters[name])

    # ---- circuit ----
    def circuit_open(self) -> bool:
        until = self._data.get("circuit_until")
        if not until:
            return False
        try:
            dt = datetime.fromisoformat(str(until).replace("Z", "+00:00"))
        except ValueError:
            return False
        if datetime.now(timezone.utc) >= dt:
            self._data["circuit_until"] = None
            self._data["circuit_reason"] = None
            self._save()
            return False
        return True

    def open_circuit(self, hours: float, reason: str) -> None:
        hours = max(1.0, float(hours))
        until = datetime.now(timezone.utc).timestamp() + hours * 3600.0
        self._data["circuit_until"] = datetime.fromtimestamp(
            until, tz=timezone.utc
        ).replace(microsecond=0).isoformat()
        self._data["circuit_reason"] = reason
        hist = self._data.setdefault("history", [])
        if isinstance(hist, list):
            hist.append({"at": utc_now(), "event": "circuit", "reason": reason, "hours": hours})
            self._data["history"] = hist[-50:]
        self._save()
        logger.warning("circuit OPEN %.1fh reason=%s", hours, reason)

    def note_flood_wait(self, seconds: int) -> None:
        self._bump("flood_waits")
        # Conservative: pause for at least wait+buffer, min 2h on big waits
        hours = max(2.0, (int(seconds) + 120) / 3600.0)
        if int(seconds) >= 300:
            hours = max(hours, 6.0)
        self.open_circuit(hours, f"FloodWait {seconds}s")

    def note_peer_flood(self) -> None:
        self._bump("peer_floods")
        self.open_circuit(self._f("peer_flood_circuit_hours", 48.0), "PeerFlood")

    # ---- budgets ----
    def allow(self, action: str) -> tuple[bool, str]:
        """Check whether an action is still within today's budget."""
        if self.circuit_open():
            return False, f"circuit:{self._data.get('circuit_reason')}"

        limits = {
            "seed_read": self._i("daily_seed_reads", 25),
            "resolve_username": self._i("daily_resolve_usernames", 35),
            "invite_peek": self._i("daily_invite_peeks", 15),
            "message_fetch": self._i("daily_message_fetches", 40),
            "profile_sample": self._i("daily_profile_samples", 35),
            "join": self._i("daily_joins", 0),  # default 0 = never join
        }
        if action not in limits:
            return True, "ok"
        used = int(self.counters().get(action) or 0)
        lim = limits[action]
        if used >= lim:
            return False, f"budget:{action}:{used}/{lim}"
        return True, "ok"

    def record(self, action: str, n: int = 1) -> None:
        self._bump(action, n)

    # ---- pacing ----
    async def sleep(self, kind: str = "default") -> None:
        """Human-like jittered pause between actions."""
        ranges = {
            "seed_read": (
                self._f("delay_seed_min", 4.0),
                self._f("delay_seed_max", 9.0),
            ),
            "resolve": (
                self._f("delay_resolve_min", 3.5),
                self._f("delay_resolve_max", 8.0),
            ),
            "invite_peek": (
                self._f("delay_invite_min", 5.0),
                self._f("delay_invite_max", 12.0),
            ),
            "hop": (
                self._f("delay_hop_min", 8.0),
                self._f("delay_hop_max", 18.0),
            ),
            "default": (
                self._f("delay_min", 3.0),
                self._f("delay_max", 7.0),
            ),
        }
        lo, hi = ranges.get(kind, ranges["default"])
        if hi < lo:
            lo, hi = hi, lo
        await asyncio.sleep(random.uniform(lo, hi))

    def allow_joins(self) -> bool:
        return self._b("allow_joins", False) and self._i("daily_joins", 0) > 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "day": self._data.get("day"),
            "counters": self.counters(),
            "circuit_open": self.circuit_open(),
            "circuit_until": self._data.get("circuit_until"),
            "circuit_reason": self._data.get("circuit_reason"),
            "allow_joins": self.allow_joins(),
        }
