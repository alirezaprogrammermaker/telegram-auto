"""Inspect / export the shared لینکدونی catalog without re-searching.

Usage:
  python -m experiments.linkdir_finders.catalog_cli list
  python -m experiments.linkdir_finders.catalog_cli list --promo-ready
  python -m experiments.linkdir_finders.catalog_cli export
  python -m experiments.linkdir_finders.catalog_cli counts
"""
from __future__ import annotations

import argparse
import json
import sys

from experiments.linkdir_finders.catalog import LinkDirCatalog


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Link-directory catalog tools")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List catalog rows")
    p_list.add_argument("--promo-ready", action="store_true")
    p_list.add_argument("--verdict", choices=("keep", "review", "junk"))
    p_list.add_argument("--status", choices=("active", "review", "junk", "stale"))
    p_list.add_argument("--limit", type=int, default=30)

    sub.add_parser("counts", help="Show catalog counters")
    p_export = sub.add_parser("export", help="Rewrite promo_ready export JSON")
    p_export.add_argument("--limit", type=int, default=200)

    p_stale = sub.add_parser("mark-stale", help="Mark old entries stale")
    p_stale.add_argument("--hours", type=float, default=72.0)

    args = parser.parse_args()
    catalog = LinkDirCatalog()

    if args.cmd == "counts":
        print(json.dumps(catalog.counts(), ensure_ascii=False, indent=2))
        return

    if args.cmd == "export":
        path = catalog.export_promo_ready(limit=args.limit)
        print(f"exported {path}")
        print(json.dumps(catalog.counts(), ensure_ascii=False, indent=2))
        return

    if args.cmd == "mark-stale":
        n = catalog.mark_stale(older_than_hours=args.hours)
        print(f"stale_marked={n}")
        print(json.dumps(catalog.counts(), ensure_ascii=False, indent=2))
        return

    if args.cmd == "list":
        rows = catalog.list_items(
            verdict=args.verdict,
            promo_ready=True if args.promo_ready else None,
            status=args.status,
            limit=args.limit,
        )
        print(
            f"{'ready':5} {'V':6} {'rank':>5} {'mem':>7} {'seen':>4}  ref | title"
        )
        for r in rows:
            ready = "yes" if r.get("promo_ready") else "-"
            print(
                f"{ready:5} {str(r.get('verdict') or '-'):6} "
                f"{float(r.get('rank_score') or 0):5.1f} "
                f"{str(r.get('participants') or '-'):>7} "
                f"{int(r.get('seen_count') or 0):4d}  "
                f"{r.get('ref')} | {r.get('title')}"
            )
        print(f"\nshown={len(rows)}  {catalog.counts()}")


if __name__ == "__main__":
    main()
