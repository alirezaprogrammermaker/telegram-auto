"""Durable, batched activity telemetry pushed to the admin-bot bridge.

Every module records what it did through :func:`incr` / :func:`gauge`. Counters
are bucketed per local day and persisted to ``data/<account>/telemetry.json``
so a crashed or rescheduled GitHub Actions runner never loses activity that was
already observed. A background flush (piggybacked on the command-poller
heartbeat) ships the buffer to ``POST /internal/stats/ingest``; whatever the
bridge refuses stays buffered for the next attempt.

One-shot scripts (linkdir pipeline, seed jobs) get an ``atexit`` flush for free.
"""
from __future__ import annotations

import atexit
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.metrics_catalog import METRIC_KEY_RE
from app.paths import account_id as resolve_account_id
from app.paths import data_path
from app.storage import load_json, save_json

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "Asia/Tehran"
INGEST_PATH = "/internal/stats/ingest"

_RETAIN_DAYS = 14
_MIN_FLUSH_INTERVAL = 45.0
_MAX_METRICS_PER_FLUSH = 400


class Telemetry:
    """Per-day counter buffer with best-effort delivery to the admin bot."""

    def __init__(
        self,
        *,
        path: Path | None = None,
        account_id: str | None = None,
        timezone: str = DEFAULT_TIMEZONE,
    ) -> None:
        self.path = path or data_path("telemetry.json")
        self.timezone = timezone
        self._account_id = account_id
        self._lock = threading.RLock()
        self._last_flush = 0.0
        self._data = self._load()

    # ---------------------------------------------------------------- record

    def incr(self, metric: str, amount: int = 1, *, day: str | None = None) -> None:
        """Add ``amount`` to a daily counter. Unknown/invalid keys are dropped."""
        self.incr_many({metric: amount}, day=day)

    def incr_many(self, metrics: dict[str, int], *, day: str | None = None) -> None:
        clean = {
            key: int(value)
            for key, value in (metrics or {}).items()
            if self._valid(key) and int(value or 0)
        }
        if not clean:
            return
        bucket_day = day or self.today()
        with self._lock:
            days = self._data.setdefault("days", {})
            bucket = days.setdefault(bucket_day, {})
            for key, value in clean.items():
                bucket[key] = int(bucket.get(key, 0)) + value
            self._prune()
            self._save()

    def gauge(self, metric: str, value: float) -> None:
        """Record a latest-value metric (queue depth, catalog size, …)."""
        if not self._valid(metric):
            return
        with self._lock:
            self._data.setdefault("gauges", {})[metric] = float(value)
            self._save()

    # ----------------------------------------------------------------- flush

    def flush(self, *, force: bool = False, timeout: float = 12.0) -> bool:
        """Ship buffered counters. Returns True when the bridge accepted them."""
        now = time.monotonic()
        if not force and now - self._last_flush < _MIN_FLUSH_INTERVAL:
            return False

        with self._lock:
            days = {
                day: dict(counters)
                for day, counters in (self._data.get("days") or {}).items()
                if counters
            }
            gauges = dict(self._data.get("gauges") or {})
        if not days and not gauges:
            self._last_flush = now
            return False

        payload = {
            "account_id": self.account_id,
            "timezone": self.timezone,
            "days": self._cap(days),
            "gauges": gauges,
        }
        if not self._send(payload, timeout=timeout):
            return False

        self._last_flush = time.monotonic()
        self._settle(payload["days"], gauges)
        return True

    def _settle(self, days: dict[str, dict[str, int]], gauges: dict[str, float]) -> None:
        """Subtract what was delivered, keeping increments that raced the flush."""
        with self._lock:
            buffered_days = self._data.setdefault("days", {})
            for day, counters in days.items():
                bucket = buffered_days.get(day) or {}
                for key, sent in counters.items():
                    remaining = int(bucket.get(key, 0)) - int(sent)
                    if remaining > 0:
                        bucket[key] = remaining
                    else:
                        bucket.pop(key, None)
                if bucket:
                    buffered_days[day] = bucket
                else:
                    buffered_days.pop(day, None)
            buffered_gauges = self._data.setdefault("gauges", {})
            for key, sent in gauges.items():
                if buffered_gauges.get(key) == sent:
                    buffered_gauges.pop(key, None)
            self._save()

    def _send(self, payload: dict[str, Any], *, timeout: float) -> bool:
        try:
            from app.bridge_client import bridge_configured, bridge_request

            if not bridge_configured():
                return False
            resp = bridge_request("POST", INGEST_PATH, payload=payload, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - telemetry never breaks callers
            logger.debug("telemetry: flush failed: %s", exc)
            return False
        if not resp or not resp.get("ok", False):
            logger.debug("telemetry: bridge rejected flush: %s", resp)
            return False
        return True

    # ---------------------------------------------------------------- helpers

    @property
    def account_id(self) -> str:
        if self._account_id:
            return self._account_id
        try:
            return (resolve_account_id() or "").strip().lower() or "default"
        except Exception:
            return "default"

    def today(self) -> str:
        try:
            tz = ZoneInfo(self.timezone)
        except Exception:
            tz = ZoneInfo(DEFAULT_TIMEZONE)
        return datetime.now(tz).date().isoformat()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "account_id": self.account_id,
                "days": {
                    day: dict(counters)
                    for day, counters in (self._data.get("days") or {}).items()
                },
                "gauges": dict(self._data.get("gauges") or {}),
            }

    def today_counters(self) -> dict[str, int]:
        with self._lock:
            return dict((self._data.get("days") or {}).get(self.today()) or {})

    @staticmethod
    def _valid(metric: str) -> bool:
        if metric and METRIC_KEY_RE.match(metric):
            return True
        logger.debug("telemetry: ignoring malformed metric %r", metric)
        return False

    @staticmethod
    def _cap(days: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
        """Bound a single request so a long offline stretch cannot blow up D1."""
        out: dict[str, dict[str, int]] = {}
        budget = _MAX_METRICS_PER_FLUSH
        for day in sorted(days, reverse=True):
            if budget <= 0:
                break
            counters = dict(list(days[day].items())[:budget])
            if counters:
                out[day] = counters
                budget -= len(counters)
        return out

    def _prune(self) -> None:
        days = self._data.get("days") or {}
        for stale in sorted(days)[:-_RETAIN_DAYS]:
            days.pop(stale, None)

    def _load(self) -> dict[str, Any]:
        raw = load_json(self.path, {"days": {}, "gauges": {}})
        if not isinstance(raw, dict):
            return {"days": {}, "gauges": {}}
        raw.setdefault("days", {})
        raw.setdefault("gauges", {})
        return raw

    def _save(self) -> None:
        try:
            save_json(self.path, self._data)
        except Exception as exc:  # noqa: BLE001
            logger.debug("telemetry: persist failed: %s", exc)


_instance: Telemetry | None = None
_instance_lock = threading.Lock()


def telemetry() -> Telemetry:
    """Process-wide singleton, created on first use."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = Telemetry()
                atexit.register(_flush_at_exit)
    return _instance


def incr(metric: str, amount: int = 1) -> None:
    try:
        telemetry().incr(metric, amount)
    except Exception:  # noqa: BLE001 - callers are hot paths
        logger.debug("telemetry: incr failed", exc_info=True)


def incr_many(metrics: dict[str, int]) -> None:
    try:
        telemetry().incr_many(metrics)
    except Exception:  # noqa: BLE001
        logger.debug("telemetry: incr_many failed", exc_info=True)


def gauge(metric: str, value: float) -> None:
    try:
        telemetry().gauge(metric, value)
    except Exception:  # noqa: BLE001
        logger.debug("telemetry: gauge failed", exc_info=True)


def flush(*, force: bool = False) -> bool:
    try:
        return telemetry().flush(force=force)
    except Exception:  # noqa: BLE001
        logger.debug("telemetry: flush failed", exc_info=True)
        return False


def reset_for_tests() -> None:
    global _instance
    with _instance_lock:
        _instance = None


def _flush_at_exit() -> None:
    if _instance is not None:
        _instance.flush(force=True, timeout=6.0)
