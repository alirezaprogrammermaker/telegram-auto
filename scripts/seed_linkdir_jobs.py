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
    source: str = "seed_script",
) -> dict[str, int]:
    enqueued = skipped = failed = 0
    for query in queries:
        if dry_run:
            print(
                json.dumps(
                    {"query": query, "query_set": query_set, "source": source},
                    ensure_ascii=False,
                )
            )
            continue
        resp = enqueue_search_job(
            query,
            priority=priority,
            redo_after_days=redo_days,
            source=source,
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


def _generate_ai_queries(
    cfg: dict,
    *,
    shard: str,
    count: int,
    known: list[str],
) -> tuple[list[str], dict]:
    """Best-effort AI query generation. Returns (queries, summary) — never raises."""
    try:
        from experiments.linkdir_finders.ai_queries import generate_queries

        result = generate_queries(
            count=count,
            query_set=shard,
            cfg=cfg,
            static_queries=known,
        )
    except Exception as exc:  # noqa: BLE001 - AI is strictly additive
        print(f"::warning::AI query generation crashed for {shard}: {exc}", file=sys.stderr)
        return [], {"used": False, "reason": "exception", "error": str(exc)[:200]}

    if not result.ok:
        print(
            f"::warning::AI queries unavailable for {shard} ({result.reason}); "
            "using static queries only",
            file=sys.stderr,
        )
    return list(result.queries), result.summary()


def _record_ai_episodes(
    queries: list[str], *, query_set: str, meta: dict
) -> int:
    """Write one episode per generated query. Never raises, never fails the run.

    This is the storage half of the agent's experience loop: the outcome is
    unknown now and gets attached later by scripts/score_agent_memory.py.
    """
    if not queries:
        return 0
    try:
        from app.agent_memory import AgentMemory
        from experiments.linkdir_finders.ai_queries import MEMORY_AGENT
        from experiments.linkdir_finders.job_queue import query_key

        memory = AgentMemory(MEMORY_AGENT)
        if not memory.available():
            return 0
        written = memory.record_episodes(
            {
                "subject": query,
                "subject_key": query_key(query),
                "kind": "query",
                "query_set": query_set,
                "source": "ai_agent",
                "meta": meta,
            }
            for query in queries
        )
        return int(written.get("inserted") or 0)
    except Exception as exc:  # noqa: BLE001 - memory is strictly additive
        print(
            f"::warning::agent memory write failed for {query_set}: {exc}",
            file=sys.stderr,
        )
        return 0


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
    parser.add_argument(
        "--ai",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Also generate queries with the Cloudflare AI agent (falls back silently). "
            "Use --no-ai to override config ai_queries.enabled"
        ),
    )
    parser.add_argument(
        "--ai-count",
        type=int,
        default=None,
        help="AI queries per shard (default: config ai_queries.count)",
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
    ai_cfg = cfg.get("ai_queries") or {}
    ai_enabled = bool(ai_cfg.get("enabled")) if args.ai is None else bool(args.ai)
    ai_count = int(args.ai_count if args.ai_count is not None else ai_cfg.get("count") or 15)

    shards = list(SHARDS) if args.query_set == "all" else [args.query_set]
    shard_summaries: list[dict[str, object]] = []
    ai_summaries: list[dict[str, object]] = []
    failed_total = 0

    for shard in shards:
        queries = queries_for_set(cfg, shard)
        if args.expand_templates and shard == "fa":
            queries = expand_seed_queries(
                queries,
                niches=list(jq.get("seed_niches") or []),
                suffixes=list(jq.get("seed_suffixes") or []),
            )
        priority = args.priority + (10 if shard == "niche" else 0)
        counts = _enqueue_list(
            queries,
            query_set=shard,
            priority=priority,
            redo_days=redo_days,
            dry_run=bool(args.dry_run),
        )
        failed_total += int(counts["failed"])
        shard_summaries.append({"query_set": shard, **counts})

        if not ai_enabled:
            continue
        ai_queries, ai_summary = _generate_ai_queries(
            cfg, shard=shard, count=ai_count, known=queries
        )
        ai_entry = {"query_set": shard, **ai_summary}
        ai_summaries.append(ai_entry)
        if not ai_queries:
            continue
        ai_counts = _enqueue_list(
            ai_queries,
            query_set=shard,
            priority=priority,
            redo_days=redo_days,
            dry_run=bool(args.dry_run),
            source="ai_agent",
        )
        shard_summaries.append({"query_set": shard, "source": "ai_agent", **ai_counts})
        if not args.dry_run:
            ai_entry["episodes"] = _record_ai_episodes(
                ai_queries,
                query_set=shard,
                meta={
                    "model": ai_summary.get("model"),
                    "account": ai_summary.get("account"),
                    "priority": priority,
                },
            )

    summary = {
        "query_set": args.query_set,
        "expand_templates": bool(args.expand_templates),
        "redo_after_days": redo_days,
        "dry_run": bool(args.dry_run),
        "shards": shard_summaries,
        "enqueued": sum(int(s["enqueued"]) for s in shard_summaries),
        "skipped": sum(int(s["skipped"]) for s in shard_summaries),
        "failed": sum(int(s["failed"]) for s in shard_summaries),
    }
    if ai_enabled:
        summary["ai"] = {
            "enabled": True,
            "count": ai_count,
            "used": any(bool(s.get("used")) for s in ai_summaries),
            "shards": ai_summaries,
        }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if failed_total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
