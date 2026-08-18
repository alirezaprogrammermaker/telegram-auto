"""Merge per-account raw_links.jsonl files into shared data/pool/group_pool.json."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules.group_pool.pool import GroupPool  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge raw_links.jsonl into group pool")
    parser.add_argument(
        "--data-root",
        default=str(ROOT / "data"),
        help="Root containing <account>/raw_links.jsonl",
    )
    args = parser.parse_args()
    root = Path(args.data_root)
    pool = GroupPool()
    files = sorted(root.glob("*/raw_links.jsonl"))
    added = 0
    scanned = 0
    for path in files:
        account = path.parent.name
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            scanned += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ref = row.get("ref")
            if not ref:
                continue
            _, is_new = pool.upsert_raw(
                str(ref),
                source_channel=str(row.get("source") or "merge"),
                message_id=row.get("message_id"),
                collector_account=str(row.get("account") or account),
            )
            if is_new:
                added += 1
    print(
        json.dumps(
            {
                "status": "ok",
                "files": len(files),
                "scanned": scanned,
                "new": added,
                "counts": pool.counts(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
