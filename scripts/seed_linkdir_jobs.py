"""Seed linkdir search jobs into D1 via admin-bot bridge."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.linkdir_finders.job_queue import (  # noqa: E402
    bridge_ready,
    enqueue_search_job,
    expand_seed_queries,
)
from experiments.linkdir_finders.settings import load_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed linkdir search jobs to D1 queue")
    parser.add_argument(
        "--expand-templates",
        action="store_true",
        help="Add niche×suffix template queries on top of config base list",
    )
    parser.add_argument(
        "--redo-after-days",
        type=int,
        default=None,
        help="Skip queries done within N days (default: config job_queue.search_redo_days)",
    )
    parser.add_argument(
        "--priority",
        type=int,
        default=100,
        help="Job priority (lower = sooner)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print queries only; do not enqueue",
    )
    args = parser.parse_args()

    if not args.dry_run and not bridge_ready():
        print(
            "::error::Admin-bot bridge not configured "
            "(set ADMIN_BOT_BRIDGE_URL + ADMIN_BOT_BRIDGE_TOKEN)",
            file=sys.stderr,
        )
        return 1

    cfg = load_config()
    jq = cfg.get("job_queue") or {}
    base = list(cfg.get("queries") or [])
    redo_days = int(
        args.redo_after_days
        if args.redo_after_days is not None
        else jq.get("search_redo_days") or 14
    )

    queries = list(base)
    if args.expand_templates:
        queries = expand_seed_queries(
            base,
            niches=list(jq.get("seed_niches") or []),
            suffixes=list(jq.get("seed_suffixes") or []),
        )

    enqueued = 0
    skipped = 0
    failed = 0
    for i, query in enumerate(queries):
        if args.dry_run:
            continue
        resp = enqueue_search_job(
            query,
            priority=args.priority,
            redo_after_days=redo_days,
            source="seed_script",
        )
        if not resp or not resp.get("ok"):
            failed += 1
            print(f"::warning::enqueue failed for {query!r}")
            continue
        if resp.get("skipped"):
            skipped += 1
        else:
            enqueued += 1

    summary = {
        "total": len(queries),
        "enqueued": enqueued,
        "skipped": skipped,
        "failed": failed,
        "expand_templates": bool(args.expand_templates),
        "redo_after_days": redo_days,
        "dry_run": bool(args.dry_run),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
