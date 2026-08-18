"""CLI for pool admin on GitHub Actions (no Telethon).

Usage:
  python scripts/pool_admin.py --action status
  python scripts/pool_admin.py --action list --status raw --limit 20
  python scripts/pool_admin.py --action approve --ref @somegroup
  python scripts/pool_admin.py --action reject --ref https://t.me/+xxx
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules.group_pool.pool import GroupPool  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Admin ops on shared group pool")
    parser.add_argument(
        "--action",
        required=True,
        choices=["status", "list", "approve", "reject"],
    )
    parser.add_argument("--status", default="", help="Filter for list (raw/ok/…)")
    parser.add_argument("--ref", default="", help="Group ref for approve/reject")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--note", default="")
    parser.add_argument(
        "--json-out",
        default="",
        help="Write full JSON result to this path",
    )
    args = parser.parse_args()

    pool = GroupPool()
    result: dict = {"ok": True, "action": args.action}

    if args.action == "status":
        result["counts"] = pool.counts()
    elif args.action == "list":
        status = (args.status or "").strip() or None
        rows = pool.list_by_status(status, limit=max(1, min(args.limit, 50)))
        result["status_filter"] = status
        result["items"] = [
            {
                "ref": r.get("ref"),
                "status": r.get("status"),
                "title": r.get("title"),
                "updated_at": r.get("updated_at"),
            }
            for r in rows
        ]
        result["counts"] = pool.counts()
    elif args.action in {"approve", "reject"}:
        ref = (args.ref or "").strip()
        if not ref:
            result = {"ok": False, "error": "missing_ref", "action": args.action}
            _emit(result, args.json_out)
            return 1
        new_status = "approved" if args.action == "approve" else "rejected"
        item = pool.set_status(
            ref,
            new_status,
            note=(args.note or None),
        )
        result["item"] = {
            "ref": item.get("ref"),
            "status": item.get("status"),
            "title": item.get("title"),
        }
        result["counts"] = pool.counts()
    else:
        result = {"ok": False, "error": "bad_action"}
        _emit(result, args.json_out)
        return 1

    _emit(result, args.json_out)
    return 0


def _emit(result: dict, json_out: str) -> None:
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if json_out:
        Path(json_out).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
