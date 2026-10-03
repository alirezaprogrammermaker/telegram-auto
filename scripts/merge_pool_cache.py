#!/usr/bin/env python3
"""Merge a runner-produced data/pool snapshot into the canonical pool cache.

Usage:
    python scripts/merge_pool_cache.py <snapshot_dir> <pool_dir>

The shared pool cache is written by many concurrent collectors. Without this
merge step, the last writer silently discards other collectors' catalog
updates. The merge is commutative:

- ``linkdir_catalog.json`` items are unioned by item key; on collision the
  entry with the newest ``last_ranked_at``/``last_seen_at``/``created_at``
  wins. Pipeline-run history is unioned (newest 30 kept).
- ``group_pool.json`` items are unioned by key; on collision the entry with
  the newest ``updated_at`` wins.
- Any other JSON file (safety counters, verify snapshots, ...) takes the
  snapshot (newer) copy when present.
"""
from __future__ import annotations

import json
import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("merge_pool_cache")


def _load(path: Path, default: Any):
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return default


def _dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _ts(raw: Any) -> datetime:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.fromtimestamp(0, tz=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _catalog_item_ts(item: dict) -> datetime:
    return max(
        _ts(item.get("last_ranked_at")),
        _ts(item.get("last_seen_at")),
        _ts(item.get("created_at")),
    )


def _group_item_ts(item: dict) -> datetime:
    return _ts(item.get("updated_at") or item.get("created_at"))


def _union_items(
    dst: dict, src: dict, ts_fn: Callable[[dict], datetime]
) -> int:
    added = 0
    for key, item in src.items():
        if not isinstance(item, dict):
            continue
        prev = dst.get(key)
        if not isinstance(prev, dict):
            dst[key] = item
            added += 1
        elif ts_fn(item) > ts_fn(prev):
            dst[key] = item
            added += 1
    return added


def merge_catalog(dst: dict, src: dict) -> int:
    """Union catalog items + merge pipeline-run history. Returns items touched."""
    items = dst.setdefault("items", {})
    added = _union_items(items, dict(src.get("items") or {}), _catalog_item_ts)

    meta_dst = dst.setdefault("meta", {})
    meta_src = src.get("meta") or {}
    if isinstance(meta_src, dict):
        runs = {str(r.get("at") or ""): r for r in meta_dst.get("pipeline_runs") or []}
        for r in meta_src.get("pipeline_runs") or []:
            if isinstance(r, dict):
                runs[str(r.get("at") or "")] = r
        ordered = sorted(runs.values(), key=lambda r: str(r.get("at") or ""), reverse=True)
        meta_dst["pipeline_runs"] = ordered[-30:]

        lp_dst = meta_dst.get("last_pipeline") or {}
        lp_src = meta_src.get("last_pipeline") or {}
        if str(lp_src.get("at") or "") > str(lp_dst.get("at") or ""):
            meta_dst["last_pipeline"] = lp_src
        for scalar in (
            "last_refresh_at",
            "last_refresh_method",
            "last_promo_export_at",
            "updated_at",
        ):
            if str(meta_src.get(scalar) or "") > str(meta_dst.get(scalar) or ""):
                meta_dst[scalar] = meta_src[scalar]
        if int(meta_src.get("last_promo_export_count") or 0) > int(
            meta_dst.get("last_promo_export_count") or 0
        ):
            meta_dst["last_promo_export_count"] = meta_src["last_promo_export_count"]
    dst.setdefault("version", 1)
    return added


def merge_group_pool(dst: dict, src: dict) -> int:
    items = dst.setdefault("items", {})
    added = _union_items(items, dict(src.get("items") or {}), _group_item_ts)
    dst.setdefault("version", 1)
    return added


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(argv) != 3:
        print(__doc__)
        return 2
    snapshot_dir = Path(argv[1])
    pool_dir = Path(argv[2])
    pool_dir.mkdir(parents=True, exist_ok=True)
    if not snapshot_dir.is_dir():
        logger.warning("snapshot dir %s missing — no-op", snapshot_dir)
        print(f"pool merge: snapshot missing, no-op ({pool_dir})")
        return 0

    total = 0
    catalog = _load(
        pool_dir / "linkdir_catalog.json",
        {"version": 1, "items": {}, "meta": {}},
    )
    src_catalog = _load(snapshot_dir / "linkdir_catalog.json", None)
    if src_catalog and isinstance(src_catalog, dict):
        total += merge_catalog(catalog, src_catalog)
    _dump(pool_dir / "linkdir_catalog.json", catalog)

    group_pool = _load(pool_dir / "group_pool.json", {"version": 1, "items": {}})
    src_group = _load(snapshot_dir / "group_pool.json", None)
    if src_group and isinstance(src_group, dict):
        total += merge_group_pool(group_pool, src_group)
    _dump(pool_dir / "group_pool.json", group_pool)

    handled = {"linkdir_catalog.json", "group_pool.json"}
    for f in sorted(snapshot_dir.glob("*.json")):
        if f.name in handled:
            continue
        shutil.copy2(f, pool_dir / f.name)

    print(f"pool merge: {total} catalog/group items added-or-updated in {pool_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
