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
    queries_for_set,
)
from experiments.linkdir_finders.settings import load_config  # noqa: E402

SHARDS = ("fa", "en", "niche")


def _enqueue_list(
    queries: list[str],
    *,
    query_set: str | None,
    priority: int,
    redo_days: int,
    dry_run: bool,
) -> dict[str, int]:
    enqueued = skipped = failed = 0
    for query in queries:
        if dry_run:
            print(json.dumps({"query": query, "query_set": query_set}, ensure_ascii=False))
            continue
        resp = enqueue_search_job(
            query,
            priority=priority,
            redo_after_days=redo_days,
            source="seed_script",
            query_set=query_set,
        )
        if not resp or not resp.get("ok"):
            failed += 1
            print(f"::warning::enqueue failed for {query!r}")
            continue
        if resp.get("skipped"):
            skipped += 1
        else:
            enqueued += 1
    return {
        "total": len(queries),
        "enqueued": enqueued,
        "skipped": skipped,
        "failed": failed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed linkdir search jobs to D1 queue")
    parser.add_argument(
        "--query-set",
        choices=["fa", "en", "niche", "all"],
        default="all",
        help="Which query shard to enqueue (default: all)",
    )
    parser.add_argument(
        "--expand-templates",
        action="store_true",
        help="Add niche×suffix templates (fa shard only)",
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
    redo_days = int(
        args.redo_after_days
        if args.redo_after_days is not None
        else jq.get("search_redo_days") or 14
    )
    shards = list(SHARDS) if args.query_set == "all" else [args.query_set]
    shard_summaries: list[dict[str, object]] = []
    failed_total = 0

    for shard in shards:
        queries = queries_for_set(cfg, shard)
        if args.expand_templates and shard == "fa":
            queries = expand_seed_queries(
                queries,
                niches=list(jq.get("seed_niches") or []),
                suffixes=list(jq.get("seed_suffixes") or []),
            )
        counts = _enqueue_list(
            queries,
            query_set=shard,
            priority=args.priority + (10 if shard == "niche" else 0),
            redo_days=redo_days,
            dry_run=bool(args.dry_run),
        )
        failed_total += int(counts["failed"])
        shard_summaries.append({"query_set": shard, **counts})

    summary = {
        "query_set": args.query_set,
        "expand_templates": bool(args.expand_templates),
        "redo_after_days": redo_days,
        "dry_run": bool(args.dry_run),
        "shards": shard_summaries,
        "enqueued": sum(int(s["enqueued"]) for s in shard_summaries),
        "skipped": sum(int(s["skipped"]) for s in shard_summaries),
        "failed": failed_total,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if failed_total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
