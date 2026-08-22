"""Run summaries → telemetry counters."""
from __future__ import annotations

from app.metrics_catalog import Ai, Gauge, LinkDir
from experiments.linkdir_finders.telemetry_map import (
    pipeline_counters,
    pipeline_gauges,
    seed_counters,
)


def test_pipeline_counters_merge_search_and_snowball() -> None:
    summary = {
        "errors": ["rerank:Timeout"],
        "catalog_counts": {"total": 900, "promo_ready": 120},
        "results": {
            "search": {
                "counts": {"keep": 5, "review": 2, "junk": 3, "total": 10},
                "catalog": {"upserted": 7},
                "job_queue": {"claimed": 4},
            },
            "snowball": {
                "resolved": 11,
                "new_upserts": 6,
                "keep": 1,
                "review": 0,
                "junk": 2,
                "errors": 3,
            },
        },
    }

    counters = pipeline_counters(summary)
    assert counters[LinkDir.RUNS] == 1
    assert counters[LinkDir.QUERIES_RUN] == 4
    assert counters[LinkDir.CHATS_FOUND] == 10
    assert counters[LinkDir.ITEMS_UPSERTED] == 13
    assert counters[LinkDir.ITEMS_KEEP] == 6
    assert counters[LinkDir.ITEMS_JUNK] == 5
    assert counters[LinkDir.SNOWBALL_RESOLVED] == 11
    assert counters[LinkDir.ERRORS] == 4
    assert LinkDir.ITEMS_REVIEW in counters


def test_pipeline_counters_drop_zero_values() -> None:
    counters = pipeline_counters({"results": {}})
    assert counters == {LinkDir.RUNS: 1}


def test_pipeline_gauges_read_catalog_counts() -> None:
    gauges = pipeline_gauges({"catalog_counts": {"total": 42, "promo_ready": 7}})
    assert gauges[Gauge.LINKDIR_CATALOG_TOTAL] == 42.0
    assert gauges[Gauge.LINKDIR_PROMO_READY] == 7.0


def test_pipeline_gauges_ignore_missing_counts() -> None:
    assert pipeline_gauges({}) == {}


def test_seed_counters_sum_ai_shards() -> None:
    summary = {
        "enqueued": 18,
        "skipped": 4,
        "ai": {
            "enabled": True,
            "shards": [
                {"accepted": 6, "rejected": 2, "used": True},
                {"accepted": 3, "rejected": 5, "used": False},
            ],
        },
    }

    counters = seed_counters(summary)
    assert counters[Ai.RUNS] == 1
    assert counters[Ai.QUERIES_ACCEPTED] == 9
    assert counters[Ai.QUERIES_REJECTED] == 7
    assert counters[Ai.QUERIES_GENERATED] == 16
    assert counters[Ai.FAILURES] == 1
    assert counters[Ai.JOBS_ENQUEUED] == 18
    assert counters[Ai.JOBS_SKIPPED] == 4


def test_seed_counters_without_ai_only_track_jobs() -> None:
    counters = seed_counters({"enqueued": 3, "skipped": 0})
    assert counters == {Ai.JOBS_ENQUEUED: 3}
