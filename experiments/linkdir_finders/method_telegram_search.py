"""Method 1 — find لینکدونی via Telegram contacts.Search (+ enrich/rank/catalog).

Standalone experiment. Not wired into production promo modules.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from experiments.linkdir_finders.catalog import LinkDirCatalog
from experiments.linkdir_finders.enrich import apply_rank, chat_kind, enrich_profile, sample_activity
from experiments.linkdir_finders.job_queue import (
    bridge_ready,
    claim_search_jobs,
    complete_job,
)
from experiments.linkdir_finders.settings import load_config
from experiments.linkdir_finders.tg import (
    connect_client,
    safe_disconnect,
    setup_logging,
    setup_stdio,
)

logger = logging.getLogger("linkdir_finders.search")

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent / "results"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


async def search_once(client: Any, query: str, *, limit: int) -> list[dict[str, Any]]:
    from telethon.tl.functions.contacts import SearchRequest

    result = await client(SearchRequest(q=query, limit=limit))
    chats = list(getattr(result, "chats", None) or [])
    rows: list[dict[str, Any]] = []
    for chat in chats:
        title = getattr(chat, "title", None)
        username = getattr(chat, "username", None)
        is_channel, is_group = chat_kind(chat)
        participants = getattr(chat, "participants_count", None)
        row: dict[str, Any] = {
            "query": query,
            "id": getattr(chat, "id", None),
            "title": title,
            "username": username,
            "ref": f"@{username}" if username else f"id:{getattr(chat, 'id', None)}",
            "is_channel": is_channel,
            "is_group": is_group,
            "participants": participants,
            "about": None,
            "activity": None,
            "tl_type": type(chat).__name__,
        }
        apply_rank(row)
        rows.append(row)
    return rows


async def run_search(
    *,
    session: str | None = None,
    cfg: dict[str, Any] | None = None,
    client: Any | None = None,
    own_client: bool = True,
    write_catalog: bool = True,
    write_snapshot: bool = True,
    collector_id: str | None = None,
) -> dict[str, Any]:
    config = cfg or load_config()
    sc = config.get("search") or {}
    jq = config.get("job_queue") or {}
    cat_cfg = config.get("catalog") or {}
    pipe = config.get("pipeline") or {}
    limit = int(sc.get("limit") or 20)
    delay = float(sc.get("delay") or 1.2)
    enrich_n = int(sc.get("enrich") or 20)
    sample = int(sc.get("sample") or 35)
    jobs_per_run = int(sc.get("jobs_per_run") or jq.get("jobs_per_run") or 5)

    use_job_queue = bool(jq.get("enabled", True)) and bool(collector_id) and bridge_ready()
    job_entries: list[tuple[int | None, str]] = []
    queue_meta: dict[str, Any] = {"mode": "config", "claimed": 0}

    if use_job_queue:
        claimed = claim_search_jobs(collector_id or "", limit=jobs_per_run)
        for job in claimed:
            payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
            query = str(payload.get("query") or "").strip()
            job_id = job.get("id")
            if query and job_id is not None:
                job_entries.append((int(job_id), query))
        queue_meta = {
            "mode": "d1_queue",
            "claimed": len(job_entries),
            "owner": collector_id,
        }
        if not job_entries:
            logger.info("no pending search jobs for collector=%s", collector_id)
            return {
                "method": "telegram_contacts_search",
                "counts": {
                    "keep": 0,
                    "review": 0,
                    "junk": 0,
                    "enriched": 0,
                    "total": 0,
                },
                "catalog": {},
                "snapshot": None,
                "job_queue": queue_meta,
            }
        queries = [q for _, q in job_entries]
    else:
        queries = list(config.get("queries") or [])
        job_entries = [(None, q) for q in queries]
        if collector_id and not bridge_ready():
            queue_meta["fallback"] = "bridge_unavailable"
        elif not collector_id:
            queue_meta["fallback"] = "no_collector_id"

    created_client = False
    if client is None:
        client, app_cfg = await connect_client(
            session=session or config.get("session_name"),
            retries=int(pipe.get("connect_retries") or 8),
            retry_sleep=float(pipe.get("retry_sleep") or 15),
        )
        created_client = True
        session_name = app_cfg.session_name
    else:
        session_name = session or config.get("session_name") or "unknown"

    me = await client.get_me()
    all_rows: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    try:
        for i, (job_id, query) in enumerate(job_entries, 1):
            logger.info("[%s/%s] search %r job=%s", i, len(job_entries), query, job_id)
            job_new = 0
            try:
                rows = await search_once(client, query, limit=limit)
            except Exception as exc:  # noqa: BLE001
                logger.error("search error %s: %s", type(exc).__name__, exc)
                if job_id is not None:
                    complete_job(job_id, status="failed", error=str(exc))
                await asyncio.sleep(delay)
                continue

            for row in rows:
                cid = row.get("id")
                if isinstance(cid, int):
                    if cid in seen_ids:
                        continue
                    seen_ids.add(cid)
                all_rows.append(row)
                job_new += 1
            logger.info("  chats=%s new_unique=%s", len(rows), job_new)
            if job_id is not None:
                complete_job(job_id, status="done", result_count=job_new)
            await asyncio.sleep(delay)

        if enrich_n > 0 and all_rows:
            ranked = sorted(
                all_rows,
                key=lambda r: (
                    float(r.get("identity_score") or 0),
                    int(r.get("participants") or 0),
                ),
                reverse=True,
            )
            targets = ranked[:enrich_n]
            logger.info("enriching top %s …", len(targets))
            for idx, row in enumerate(targets, 1):
                try:
                    if row.get("username"):
                        entity = await client.get_entity(row["username"])
                    elif row.get("id") is not None:
                        entity = await client.get_entity(row["id"])
                    else:
                        continue
                except Exception as exc:  # noqa: BLE001
                    row["about"] = f"<resolve_failed:{type(exc).__name__}>"
                    row["activity"] = {"readable": False, "error": type(exc).__name__}
                    apply_rank(row)
                    continue

                profile = await enrich_profile(client, entity)
                row["about"] = profile.get("about")
                if profile.get("participants") is not None:
                    row["participants"] = profile.get("participants")
                row["kind"] = profile.get("kind")
                row["is_channel"] = profile.get("is_channel")
                row["is_group"] = profile.get("is_group")
                row["broadcast"] = profile.get("broadcast")
                row["megagroup"] = profile.get("megagroup")
                row["gigagroup"] = profile.get("gigagroup")
                row["members_can_send"] = profile.get("members_can_send")
                row["postable"] = profile.get("postable")
                row["linked_chat_id"] = profile.get("linked_chat_id")
                row["activity"] = await sample_activity(client, entity, sample=sample)
                apply_rank(row)
                logger.info(
                    "  [%s] %s kind=%s postable=%s rank=%s verdict=%s mem=%s",
                    idx,
                    row.get("ref"),
                    row.get("kind"),
                    row.get("postable"),
                    row.get("rank_score"),
                    row.get("verdict"),
                    row.get("participants"),
                )
                await asyncio.sleep(max(0.5, delay / 2))
    finally:
        if created_client and own_client:
            await safe_disconnect(client)

    all_rows.sort(
        key=lambda r: (
            {"keep": 2, "review": 1, "junk": 0}.get(str(r.get("verdict")), 0),
            float(r.get("rank_score") or 0),
        ),
        reverse=True,
    )

    counts = {
        "keep": sum(1 for r in all_rows if r.get("verdict") == "keep"),
        "review": sum(1 for r in all_rows if r.get("verdict") == "review"),
        "junk": sum(1 for r in all_rows if r.get("verdict") == "junk"),
        "enriched": sum(1 for r in all_rows if r.get("activity") is not None),
        "total": len(all_rows),
    }

    catalog_info: dict[str, Any] = {}
    if write_catalog:
        catalog = LinkDirCatalog(collector_id=collector_id)
        upserted = 0
        for row in all_rows:
            try:
                catalog.upsert_from_search(row, method="telegram_contacts_search", save=False)
                upserted += 1
            except ValueError:
                continue
        catalog.save()
        stale_n = catalog.mark_stale(
            older_than_hours=float(cat_cfg.get("stale_hours") or 72)
        )
        export_path = catalog.export_promo_ready(
            limit=int(cat_cfg.get("promo_limit") or 200)
        )
        catalog_info = {
            "upserted": upserted,
            "stale_marked": stale_n,
            "promo_export": str(export_path),
            "catalog_counts": catalog.counts(),
        }

    snapshot_path = None
    if write_snapshot:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        snapshot_path = OUT_DIR / f"telegram_search_{stamp}.json"
        payload = {
            "method": "telegram_contacts_search",
            "at": _utc_now(),
            "account": {
                "id": me.id,
                "username": getattr(me, "username", None),
                "session": session_name,
            },
            "queries": queries,
            "counts": counts,
            "catalog": catalog_info,
            "results": all_rows,
        }
        snapshot_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return {
        "method": "telegram_contacts_search",
        "counts": counts,
        "catalog": catalog_info,
        "snapshot": str(snapshot_path) if snapshot_path else None,
        "job_queue": queue_meta,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Telegram search لینکدونی finder (experiment)")
    p.add_argument("--session", default=None)
    p.add_argument("--no-catalog", action="store_true")
    p.add_argument("--verbose", action="store_true")
    return p


def main() -> None:
    setup_stdio()
    args = build_parser().parse_args()
    setup_logging(verbose=args.verbose)
    stats = asyncio.run(
        run_search(session=args.session, write_catalog=not args.no_catalog)
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
