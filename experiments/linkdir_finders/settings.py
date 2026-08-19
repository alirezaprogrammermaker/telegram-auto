"""Load experiment config (flexible knobs — not production modules)."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

_DEFAULTS: dict[str, Any] = {
    "session_name": "easy_seen",
    "sessions": ["easy_seen"],
    "queries": [
        "لینکدونی",
        "تبادل لینک",
        "لینک رایگان",
        "link exchange",
        "links directory",
    ],
    "safety": {
        "allow_joins": False,
        "daily_joins": 0,
        "daily_seed_reads": 20,
        "daily_resolve_usernames": 30,
        "daily_invite_peeks": 12,
        "daily_message_fetches": 30,
        "daily_profile_samples": 30,
        "peer_flood_circuit_hours": 48.0,
        "delay_seed_min": 4.0,
        "delay_seed_max": 9.0,
        "delay_resolve_min": 3.5,
        "delay_resolve_max": 8.0,
        "delay_invite_min": 5.0,
        "delay_invite_max": 12.0,
        "delay_hop_min": 10.0,
        "delay_hop_max": 20.0,
    },
    "search": {"limit": 15, "delay": 2.0, "enrich": 12, "sample": 25, "jobs_per_run": 5},
    "job_queue": {
        "enabled": True,
        "search_redo_days": 14,
        "seed_niches": ["گپ", "کانال", "گروه"],
        "seed_suffixes": ["لینک", "لینکدونی", "تبادل لینک", "عضویت"],
    },
    "snowball": {
        "hops": 2,
        "seed_limit": 8,
        "messages_per_seed": 30,
        "max_new_per_run": 20,
        "max_resolve_per_run": 25,
        "max_invite_peek_per_run": 10,
        "enrich_sample": 18,
        "min_seed_rank": 55,
        "prefer_seed_only": True,
    },
    "rerank": {
        "limit": 25,
        "sample": 25,
        "delay": 2.0,
        "include_review": True,
        "include_stale": True,
        "stale_limit": 8,
    },
    "catalog": {"stale_hours": 72, "promo_limit": 200},
    "pipeline": {
        "steps": ["search", "snowball", "rerank"],
        "connect_retries": 8,
        "retry_sleep": 20,
        "loop_hours": 12,
    },
}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, val in overlay.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def load_config(path: Path | None = None) -> dict[str, Any]:
    cfg_path = path or CONFIG_PATH
    if not cfg_path.exists():
        return deepcopy(_DEFAULTS)
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return deepcopy(_DEFAULTS)
    if not isinstance(raw, dict):
        return deepcopy(_DEFAULTS)
    return _deep_merge(_DEFAULTS, raw)
