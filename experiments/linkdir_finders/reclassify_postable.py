"""One-off: reclassify catalog usernames with kind + members_can_send."""
from __future__ import annotations

import asyncio
import logging

from experiments.linkdir_finders.catalog import LinkDirCatalog
from experiments.linkdir_finders.enrich import resolve_and_profile
from experiments.linkdir_finders.tg import connect_client, safe_disconnect, setup_logging, setup_stdio


async def main() -> None:
    setup_stdio()
    setup_logging()
    cat = LinkDirCatalog()
    rows = [r for r in cat.list_items(limit=10000) if r.get("username")]
    force = {
        "linkdoni_sib",
        "link_linkdo",
        "linkdoniimm",
        "gp_cb",
        "linkdoni_1s",
        "links_international",
    }
    forced = [r for r in rows if str(r.get("username") or "").lower() in force]
    rest = [r for r in rows if str(r.get("username") or "").lower() not in force]
    rest.sort(key=lambda r: float(r.get("identity_score") or r.get("rank_score") or 0), reverse=True)
    targets = forced + rest[:45]

    client, _ = await connect_client(session="easy_seen", retries=5, retry_sleep=10)
    try:
        for i, item in enumerate(targets, 1):
            ref = "@" + str(item["username"])
            row = await resolve_and_profile(client, ref, sample=20, query="reclassify")
            if not row:
                continue
            cat.upsert_from_search(row, method="reclassify_postable", save=False)
            print(
                f"[{i}/{len(targets)}] {row.get('ref')} kind={row.get('kind')} "
                f"post={row.get('members_can_send')} v={row.get('verdict')} "
                f"rank={row.get('rank_score')} idn={row.get('identity_score')}"
            )
            await asyncio.sleep(0.6)
        cat.save()
        path = cat.export_promo_ready()
        print("export", path)
        print("counts", cat.counts())
    finally:
        await safe_disconnect(client)


if __name__ == "__main__":
    asyncio.run(main())
