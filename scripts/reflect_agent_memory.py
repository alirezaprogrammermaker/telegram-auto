"""Run one contrastive reflection pass over the query agent's episodes.

Pulls the best and worst scored, not-yet-consolidated episodes, asks the
Cloudflare AI agent what to repeat and what to avoid, validates every lesson
against the script allowlist and the supplied episode ids, then writes the
survivors back and flags the evidence as consolidated.

See :mod:`experiments.linkdir_finders.reflection` for the grounding rules.
Always exits 0 — this runs unattended.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.linkdir_finders.ai_queries import MEMORY_AGENT  # noqa: E402
from experiments.linkdir_finders.reflection import (  # noqa: E402
    DEFAULT_BEST,
    DEFAULT_WORST,
    MIN_SCORED_EPISODES,
    reflect,
)
from experiments.linkdir_finders.settings import load_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Distill scored agent episodes into Persian lessons"
    )
    parser.add_argument("--agent", default=MEMORY_AGENT, help="Agent name in D1")
    parser.add_argument(
        "--best", type=int, default=DEFAULT_BEST, help="Top episodes to reflect on"
    )
    parser.add_argument(
        "--worst", type=int, default=DEFAULT_WORST, help="Bottom episodes to reflect on"
    )
    parser.add_argument(
        "--min-episodes",
        type=int,
        default=MIN_SCORED_EPISODES,
        help="Skip the run below this much scored evidence",
    )
    parser.add_argument("--model", default=None, help="Override the Workers AI model")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the distilled lessons; do not write them back",
    )
    args = parser.parse_args()

    memory: Any = None
    if args.agent != MEMORY_AGENT:
        from app.agent_memory import AgentMemory

        memory = AgentMemory(args.agent)

    result = reflect(
        memory=memory,
        cfg=load_config(),
        best=args.best,
        worst=args.worst,
        min_episodes=args.min_episodes,
        model=args.model,
        dry_run=bool(args.dry_run),
    )

    summary = {"agent": args.agent, **result.summary()}
    if result.lessons:
        summary["distilled"] = [
            {
                "kind": row["kind"],
                "lesson": row["lesson"],
                "evidence": row["evidence"],
                "confidence": row["confidence"],
            }
            for row in result.lessons
        ]
    if result.rejected:
        summary["rejections"] = result.rejected[:10]

    if not result.ok:
        print(f"::notice::reflection produced nothing ({result.reason})", file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
