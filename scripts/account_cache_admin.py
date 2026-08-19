"""Admin ops on per-account Actions cache (queues / safety dumps). No Telethon."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.paths import account_id as current_account_id  # noqa: E402
from app.paths import data_path  # noqa: E402
from app.storage import load_json  # noqa: E402


def _promo_queue_status() -> dict:
    from app.metrics_snapshot import collect_runtime_metrics

    pending = collect_runtime_metrics().get("promo_queue_pending", 0)
    return {"queue": "promo", "pending": pending}


def _promo_queue_clear() -> dict:
    from modules.promo_spread.queue import PromoQueue

    n = PromoQueue().clear_pending()
    return {"queue": "promo", "cleared": n}


def _forward_queue_status() -> dict:
    from app.metrics_snapshot import collect_runtime_metrics

    path = data_path("publish_queue.json")
    pending = collect_runtime_metrics().get("forward_queue_pending", 0)
    return {"queue": "forward", "pending": pending, "path": str(path)}


def _forward_queue_clear() -> dict:
    path = data_path("publish_queue.json")
    data = load_json(path, {"items": []})
    items = data.get("items") if isinstance(data, dict) else []
    kept = [
        i
        for i in (items or [])
        if isinstance(i, dict) and i.get("status") not in {"pending", "ready", None}
    ]
    cleared = len(items or []) - len(kept)
    from app.storage import save_json

    save_json(path, {"items": kept})
    return {"queue": "forward", "cleared": cleared}


def _dump_json(name: str) -> dict:
    path = data_path(name)
    data = load_json(path, {})
    return {"file": name, "exists": path.is_file(), "data": data}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--action",
        required=True,
        choices=[
            "promo_queue_status",
            "promo_queue_clear",
            "forward_queue_status",
            "forward_queue_clear",
            "promo_safety_dump",
            "inspect_state_dump",
            "stats_dump",
        ],
    )
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    aid = os.environ.get("ACCOUNT_ID") or current_account_id()
    result: dict = {"ok": True, "action": args.action, "account_id": aid}

    try:
        if args.action == "promo_queue_status":
            result.update(_promo_queue_status())
        elif args.action == "promo_queue_clear":
            result.update(_promo_queue_clear())
        elif args.action == "forward_queue_status":
            result.update(_forward_queue_status())
        elif args.action == "forward_queue_clear":
            result.update(_forward_queue_clear())
        elif args.action == "promo_safety_dump":
            result.update(_dump_json("promo_safety.json"))
        elif args.action == "inspect_state_dump":
            result.update(_dump_json("inspect_safety.json"))
        elif args.action == "stats_dump":
            result.update(_dump_json("stats.json"))
    except Exception as exc:
        result = {
            "ok": False,
            "action": args.action,
            "account_id": aid,
            "error": str(exc)[:300],
        }

    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.json_out:
        Path(args.json_out).write_text(text + "\n", encoding="utf-8")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
