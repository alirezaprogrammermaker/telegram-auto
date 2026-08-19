"""Re-rank existing catalog entries (activity + members) without full search.

Keeps promo_ready honest: dead groups drop to junk/stale; revived stale can
come back to keep. Experiment-only — not wired into production promo.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any

from experiments.linkdir_finders.catalog import LinkDirCatalog
from experiments.linkdir_finders.enrich import resolve_and_profile
from experiments.linkdir_finders.settings import load_config
from experiments.linkdir_finders.tg import (
    connect_client,
    safe_disconnect,
    setup_logging,
    setup_stdio,
)

logger = logging.getLogger("linkdir_finders.rerank")


async def run_rerank(
    *,
    session: str | None = None,
    cfg: dict[str, Any] | None = None,
    client: Any | None = None,
    own_client: bool = True,
    collector_id: str | None = None,
) -> dict[str, Any]:
    config = cfg or load_config()
    rr = config.get("rerank") or {}
    cat_cfg = config.get("catalog") or {}
    pipe = config.get("pipeline") or {}
    catalog = LinkDirCatalog(collector_id=collector_id)

    targets = catalog.items_for_rerank(
        limit=int(rr.get("limit") or 40),
        include_review=bool(rr.get("include_review", True)),
        include_stale=bool(rr.get("include_stale", True)),
        stale_limit=int(rr.get("stale_limit") or 15),
    )
    sample = int(rr.get("sample") or 35)
    delay = float(rr.get("delay") or 0.8)

    stats = {
        "method": "rerank",
        "targets": len(targets),
        "updated": 0,
        "keep": 0,
        "review": 0,
        "junk": 0,
        "errors": 0,
        "skipped_no_ref": 0,
    }

    if not targets:
        logger.warning("nothing to rerank")
        return stats

    created_client = False
    if client is None:
        client, _ = await connect_client(
            session=session or config.get("session_name"),
            retries=int(pipe.get("connect_retries") or 8),
            retry_sleep=float(pipe.get("retry_sleep") or 15),
        )
        created_client = True

    try:
        for i, item in enumerate(targets, 1):
            ref = None
            if item.get("username"):
                ref = f"@{item['username']}"
            elif item.get("ref") and str(item["ref"]).startswith("@"):
                ref = str(item["ref"])
            if not ref:
                stats["skipped_no_ref"] += 1
                continue

            logger.info(
                "[%s/%s] rerank %s prev=%s status=%s",
                i,
                len(targets),
                ref,
                item.get("rank_score"),
                item.get("status"),
            )
            row = await resolve_and_profile(client, ref, sample=sample, query="rerank")
            if not row or row.get("resolve_error"):
                stats["errors"] += 1
                # If unreadable now, push toward junk via empty activity
                if row:
                    try:
                        catalog.upsert_from_search(row, method="rerank", save=False)
                        stats["updated"] += 1
                        v = row.get("verdict")
                        if v in stats:
                            stats[v] += 1
                    except ValueError:
                        pass
                await asyncio.sleep(delay)
                continue

            try:
                catalog.upsert_from_search(row, method="rerank", save=False)
                stats["updated"] += 1
                v = row.get("verdict")
                if v in stats:
                    stats[v] += 1
                logger.info(
                    "  → verdict=%s rank=%s mem=%s age_h=%s",
                    row.get("verdict"),
                    row.get("rank_score"),
                    row.get("participants"),
                    (row.get("activity") or {}).get("last_message_age_hours"),
                )
            except ValueError:
                stats["errors"] += 1
            await asyncio.sleep(delay)

        catalog.save()
        stale_n = catalog.mark_stale(
            older_than_hours=float(cat_cfg.get("stale_hours") or 72)
        )
        export_path = catalog.export_promo_ready(
            limit=int(cat_cfg.get("promo_limit") or 200)
        )
        stats["stale_marked"] = stale_n
        stats["promo_export"] = str(export_path)
        stats["catalog_counts"] = catalog.counts()
        return stats
    finally:
        if created_client and own_client:
            await safe_disconnect(client)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Re-rank linkdir catalog (experiment)")
    p.add_argument("--session", default=None)
    p.add_argument("--verbose", action="store_true")
    return p


def main() -> None:
    setup_stdio()
    args = build_parser().parse_args()
    setup_logging(verbose=args.verbose)
    stats = asyncio.run(run_rerank(session=args.session))
    print(stats)


if __name__ == "__main__":
    main()
