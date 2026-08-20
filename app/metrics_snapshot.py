"""Lightweight runtime metrics for bridge heartbeat (no Telethon)."""
from __future__ import annotations

from typing import Any

from app.paths import data_path
from app.stats import StatsStore
from app.storage import load_json


def _forward_queue_pending() -> int:
    data = load_json(data_path("publish_queue.json"), {"items": []})
    items = data.get("items") if isinstance(data, dict) else []
    return sum(
        1
        for item in (items or [])
        if isinstance(item, dict) and item.get("status") in {"pending", "ready", None}
    )


def _promo_queue_pending() -> int:
    try:
        from modules.promo_spread.queue import PromoQueue

        q = PromoQueue()
        if hasattr(q, "pending_count"):
            return int(q.pending_count())
    except Exception:
        pass
    data = load_json(data_path("promo_queue.json"), {"items": []})
    return sum(
        1
        for item in (data.get("items") or [])
        if isinstance(item, dict) and item.get("status") == "pending"
    )


def _stats_today() -> dict[str, Any]:
    store = StatsStore()
    data = load_json(store.path, {"days": {}})
    day = store._today_key()
    bucket = (data.get("days") or {}).get(day) or {}
    return {
        "day": day,
        "forwarded": int(bucket.get("forwarded", 0)),
        "blocked": int(bucket.get("blocked", 0)),
        "queued": int(bucket.get("queued", 0)),
        "published_scheduled": int(bucket.get("published_scheduled", 0)),
        "filtered_copy": int(bucket.get("filtered_copy", 0)),
        "failed": int(bucket.get("failed", 0)),
    }


def _promo_circuit() -> dict[str, Any]:
    data = load_json(data_path("promo_safety.json"), {})
    if not isinstance(data, dict):
        data = {}
    return {
        "is_open": bool(data.get("paused_until")),
        "paused_until": data.get("paused_until"),
        "pause_reason": data.get("pause_reason") or "",
        "flood_strikes": int(data.get("flood_strikes") or 0),
    }


def _promo_schedule() -> dict[str, Any]:
    """Whether promo worker would send right now (quiet hours / circuit)."""
    try:
        from modules.promo_spread.safety import SafetyConfig, SafetyGuard

        runtime = load_json(data_path("modules.runtime.json"), {})
        promo_cfg = {}
        if isinstance(runtime, dict):
            promo_cfg = runtime.get("promo_spread") or {}
        if not isinstance(promo_cfg, dict):
            promo_cfg = {}
        safety_raw = promo_cfg.get("safety") if isinstance(promo_cfg.get("safety"), dict) else {}
        cfg = SafetyConfig.from_dict(safety_raw)
        guard = SafetyGuard(cfg)
        active, why = guard.is_active_now()
        ok_b, why_b = guard.budget_ok()
        return {
            "active_now": bool(active),
            "reason": "" if active else str(why or ""),
            "budget_ok": bool(ok_b),
            "budget_reason": "" if ok_b else str(why_b or ""),
            "timezone": cfg.timezone,
            "windows": list(cfg.active_windows or []),
        }
    except Exception:
        return {
            "active_now": None,
            "reason": "",
            "budget_ok": None,
            "budget_reason": "",
            "timezone": "",
            "windows": [],
        }


def collect_runtime_metrics() -> dict[str, Any]:
    """Snapshot for heartbeat meta_json.metrics."""
    return {
        "stats_today": _stats_today(),
        "forward_queue_pending": _forward_queue_pending(),
        "promo_queue_pending": _promo_queue_pending(),
        "promo_circuit": _promo_circuit(),
        "promo_schedule": _promo_schedule(),
    }
