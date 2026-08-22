"""Translate linkdir run summaries into admin-bot telemetry counters.

The pipeline steps already return rich dicts; this is the single place that
knows how those shapes map onto the shared metric catalog, so adding a step
never means sprinkling counters through the search/snowball code.
"""
from __future__ import annotations

from typing import Any

from app.metrics_catalog import Ai, Gauge, LinkDir


def _int(source: Any, *keys: str) -> int:
    node: Any = source
    for key in keys:
        if not isinstance(node, dict):
            return 0
        node = node.get(key)
    try:
        return int(node or 0)
    except (TypeError, ValueError):
        return 0


def pipeline_counters(summary: dict[str, Any]) -> dict[str, int]:
    """Counters for one `pipeline.run_once` summary."""
    results = summary.get("results") if isinstance(summary.get("results"), dict) else {}
    search = results.get("search") if isinstance(results.get("search"), dict) else {}
    snow = results.get("snowball") if isinstance(results.get("snowball"), dict) else {}

    counters = {
        LinkDir.RUNS: 1,
        LinkDir.QUERIES_RUN: _int(search, "job_queue", "claimed"),
        LinkDir.CHATS_FOUND: _int(search, "counts", "total"),
        LinkDir.ITEMS_UPSERTED: (
            _int(search, "catalog", "upserted") + _int(snow, "new_upserts")
        ),
        LinkDir.ITEMS_KEEP: _int(search, "counts", "keep") + _int(snow, "keep"),
        LinkDir.ITEMS_REVIEW: _int(search, "counts", "review") + _int(snow, "review"),
        LinkDir.ITEMS_JUNK: _int(search, "counts", "junk") + _int(snow, "junk"),
        LinkDir.SNOWBALL_RESOLVED: _int(snow, "resolved"),
        LinkDir.ERRORS: len(summary.get("errors") or []) + _int(snow, "errors"),
    }
    return {key: value for key, value in counters.items() if value}


def pipeline_gauges(summary: dict[str, Any]) -> dict[str, float]:
    counts = summary.get("catalog_counts")
    if not isinstance(counts, dict):
        return {}
    return {
        Gauge.LINKDIR_PROMO_READY: float(_int(counts, "promo_ready")),
        Gauge.LINKDIR_CATALOG_TOTAL: float(_int(counts, "total")),
    }


def seed_counters(summary: dict[str, Any]) -> dict[str, int]:
    """Counters for one `scripts/seed_linkdir_jobs.py` run summary."""
    ai = summary.get("ai") if isinstance(summary.get("ai"), dict) else {}
    shards = ai.get("shards") if isinstance(ai.get("shards"), list) else []
    accepted = sum(_int(shard, "accepted") for shard in shards)
    rejected = sum(_int(shard, "rejected") for shard in shards)
    failures = sum(1 for shard in shards if not shard.get("used"))

    counters = {
        Ai.RUNS: 1 if ai.get("enabled") else 0,
        Ai.QUERIES_GENERATED: accepted + rejected,
        Ai.QUERIES_ACCEPTED: accepted,
        Ai.QUERIES_REJECTED: rejected,
        Ai.FAILURES: failures,
        Ai.JOBS_ENQUEUED: _int(summary, "enqueued"),
        Ai.JOBS_SKIPPED: _int(summary, "skipped"),
    }
    return {key: value for key, value in counters.items() if value}


def record_pipeline(summary: dict[str, Any]) -> None:
    from app.telemetry import flush, gauge, incr_many

    incr_many(pipeline_counters(summary))
    for metric, value in pipeline_gauges(summary).items():
        gauge(metric, value)
    flush(force=True)


def record_seed(summary: dict[str, Any]) -> None:
    from app.telemetry import flush, incr_many

    incr_many(seed_counters(summary))
    flush(force=True)
