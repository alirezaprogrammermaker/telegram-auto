"""Turn linkdir catalog verdicts into reward on the query agent's episodes.

Reads unscored episodes from the agent-memory bridge, groups the shared
catalog by the query that surfaced each row, and posts one reward per episode.
The reward formula and its rationale live in
:mod:`experiments.linkdir_finders.reward`.

Episodes with no catalog rows yet are held back until ``--min-age-hours`` has
passed: collectors claim search jobs asynchronously, so scoring a fresh
episode at 0.0 would teach the agent that every new query is bad.

Always exits 0 — this runs unattended and must never fail a scheduled job.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agent_memory import AgentMemory  # noqa: E402
from experiments.linkdir_finders.ai_queries import MEMORY_AGENT  # noqa: E402
from experiments.linkdir_finders.job_queue import query_key  # noqa: E402
from experiments.linkdir_finders.reward import (  # noqa: E402
    VERDICTS,
    QueryOutcome,
    group_catalog_rows,
)

DEFAULT_EPISODE_LIMIT = 200
DEFAULT_CATALOG_LIMIT = 500
DEFAULT_MIN_AGE_HOURS = 24.0


def load_catalog_outcomes(catalog: Any, *, limit: int) -> dict[str, QueryOutcome]:
    """Group every catalog verdict bucket by originating query."""
    rows: list[dict[str, Any]] = []
    for verdict in VERDICTS:
        try:
            chunk = catalog.list_items(verdict=verdict, limit=limit) or []
        except Exception as exc:  # noqa: BLE001 - a missing bucket is not fatal
            print(f"::warning::catalog list_items({verdict}) failed: {exc}", file=sys.stderr)
            continue
        rows.extend(row for row in chunk if isinstance(row, dict))
    return group_catalog_rows(rows)


def _too_fresh(episode: dict[str, Any], *, min_age_hours: float) -> bool:
    """True when an empty-result episode is too young to judge."""
    raw = str(episode.get("created_at") or "").strip()
    if not raw:
        return False
    try:
        created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created > datetime.now(timezone.utc) - timedelta(hours=min_age_hours)


def build_outcomes(
    episodes: list[dict[str, Any]],
    grouped: dict[str, QueryOutcome],
    *,
    min_age_hours: float,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Match episodes to catalog outcomes; hold back the ones still in flight."""
    by_key = {query_key(query): outcome for query, outcome in grouped.items()}
    outcomes: list[dict[str, Any]] = []
    stats = {"matched": 0, "empty": 0, "held": 0, "unusable": 0}

    for episode in episodes:
        subject = str(episode.get("subject") or "").strip()
        key = str(episode.get("subject_key") or "").strip() or (
            query_key(subject) if subject else ""
        )
        if not key:
            stats["unusable"] += 1
            continue

        outcome = by_key.get(key)
        if outcome is None:
            if _too_fresh(episode, min_age_hours=min_age_hours):
                stats["held"] += 1
                continue
            stats["empty"] += 1
            outcomes.append(QueryOutcome(query=subject).as_outcome(key))
            continue

        stats["matched"] += 1
        outcomes.append(outcome.as_outcome(key))

    return outcomes, stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Score agent-memory episodes from linkdir catalog verdicts"
    )
    parser.add_argument("--agent", default=MEMORY_AGENT, help="Agent name in D1")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_EPISODE_LIMIT,
        help="Max unscored episodes to pull per run",
    )
    parser.add_argument(
        "--catalog-limit",
        type=int,
        default=DEFAULT_CATALOG_LIMIT,
        help="Max catalog rows to read per verdict",
    )
    parser.add_argument(
        "--min-age-hours",
        type=float,
        default=DEFAULT_MIN_AGE_HOURS,
        help="Hold back result-less episodes younger than this",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute rewards and print them; do not write back",
    )
    args = parser.parse_args()

    summary: dict[str, Any] = {
        "agent": args.agent,
        "dry_run": bool(args.dry_run),
        "episodes": 0,
        "scored": 0,
    }

    memory = AgentMemory(args.agent)
    if not memory.available():
        summary["ok"] = False
        summary["reason"] = "bridge_unavailable"
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    episodes = memory.episodes(scored=False, limit=args.limit, order="recent")
    summary["episodes"] = len(episodes)
    if not episodes:
        summary["ok"] = True
        summary["reason"] = "nothing_to_score"
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    try:
        from experiments.linkdir_finders.catalog import LinkDirCatalog

        grouped = load_catalog_outcomes(LinkDirCatalog(), limit=args.catalog_limit)
    except Exception as exc:  # noqa: BLE001 - never fail a scheduled run
        summary["ok"] = False
        summary["reason"] = "catalog_unavailable"
        summary["error"] = str(exc)[:200]
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    outcomes, stats = build_outcomes(
        episodes, grouped, min_age_hours=args.min_age_hours
    )
    summary.update(stats)
    summary["catalog_queries"] = len(grouped)

    if outcomes:
        rewards = sorted(float(row["reward"]) for row in outcomes)
        summary["avg_reward"] = round(sum(rewards) / len(rewards), 4)
        summary["max_reward"] = rewards[-1]
        summary["min_reward"] = rewards[0]

    if args.dry_run:
        summary["ok"] = True
        summary["reason"] = "dry_run"
        summary["preview"] = outcomes[:10]
    else:
        summary["scored"] = memory.score_episodes(outcomes)
        summary["ok"] = True
        summary["reason"] = "ok" if summary["scored"] else "nothing_written"

    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
