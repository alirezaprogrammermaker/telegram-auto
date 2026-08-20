"""Backfill agent episodes from already-queued AI search jobs.

Useful once after enabling experience memory so queries that were seeded
before episode recording existed still enter the learning loop. Safe to
re-run: the bridge upserts ignore duplicate (agent, kind, subject_key).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agent_memory import AgentMemory  # noqa: E402
from app.bridge_client import bridge_configured, bridge_request  # noqa: E402
from experiments.linkdir_finders.ai_queries import MEMORY_AGENT  # noqa: E402


def _jobs_from_bridge(*, limit: int) -> list[dict[str, Any]]:
    """Best-effort pull of search jobs; shape varies by bridge version."""
    # Prefer a dedicated list endpoint when present; fall back gracefully.
    for path in (
        "/internal/linkdir/jobs",
        "/internal/jobs/list",
    ):
        resp = bridge_request(
            "GET",
            path,
            query={"job_type": "search", "limit": limit, "source": "ai_agent"},
        )
        if not isinstance(resp, dict):
            continue
        rows = resp.get("jobs") or resp.get("items") or resp.get("rows")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def episodes_from_job_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        payload = row.get("payload") or row.get("payload_json") or row
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("source") or "").strip() not in {"", "ai_agent"}:
            # Only backfill AI-originated queries unless source is absent on
            # older rows that already look like AI subjects.
            if str(row.get("source") or "").strip() != "ai_agent":
                continue
        query = str(payload.get("query") or "").strip()
        if not query:
            continue
        episode: dict[str, Any] = {
            "subject": query,
            "kind": "query",
            "source": "ai_agent",
        }
        key = str(payload.get("query_key") or "").strip()
        if key:
            episode["subject_key"] = key
        qset = str(payload.get("query_set") or "").strip()
        if qset:
            episode["query_set"] = qset
        out.append(episode)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill linkdir_query episodes from AI search jobs"
    )
    parser.add_argument("--agent", default=MEMORY_AGENT)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument(
        "--from-json",
        type=Path,
        default=None,
        help="Optional file of job rows (or {jobs:[...]}) instead of the bridge",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.from_json is not None:
        raw = json.loads(args.from_json.read_text(encoding="utf-8"))
        rows = raw.get("jobs") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            print(json.dumps({"ok": False, "error": "bad_json"}))
            return 1
    else:
        if not bridge_configured():
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "bridge_unavailable",
                        "hint": "set ADMIN_BOT_BRIDGE_URL + ADMIN_BOT_BRIDGE_TOKEN "
                        "or pass --from-json",
                    }
                )
            )
            return 0
        rows = _jobs_from_bridge(limit=args.limit)

    episodes = episodes_from_job_rows(rows)
    summary: dict[str, Any] = {
        "agent": args.agent,
        "jobs_seen": len(rows),
        "episodes": len(episodes),
        "dry_run": bool(args.dry_run),
    }
    if args.dry_run or not episodes:
        summary["inserted"] = 0
        summary["skipped"] = 0
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    result = AgentMemory(args.agent).record_episodes(episodes)
    summary.update(result)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
