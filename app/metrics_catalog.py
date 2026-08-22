"""Canonical telemetry metric keys shared by every userbot module.

The admin bot keeps a mirror of this catalog (with Persian labels) in
``cf-admin-bot/src/app/Support/Metrics.py``. ``tests/test_metrics_catalog.py``
fails the build when the two sides drift apart, so a metric can never be
emitted without the panel knowing how to render it.

Naming contract: ``<category>.<event>`` — lowercase snake case on both sides.
Counters accumulate per day; gauges keep only their latest value.
"""
from __future__ import annotations

import re

METRIC_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


class Promo:
    POSTS_SEEN = "promo.posts_seen"
    TARGETS_QUEUED = "promo.targets_queued"
    DELIVERED = "promo.delivered"
    FAILED = "promo.failed"
    DEFERRED = "promo.deferred"
    DRY_RUN = "promo.dry_run"
    SKIPPED_QUIET = "promo.skipped_quiet"
    SKIPPED_BUDGET = "promo.skipped_budget"
    SKIPPED_PAUSED = "promo.skipped_paused"
    SKIPPED_COOLDOWN = "promo.skipped_cooldown"
    REACTION_SEEN = "promo.reaction_seen"
    REACTION_ACK = "promo.reaction_ack"
    JOIN_OK = "promo.join_ok"
    JOIN_FAILED = "promo.join_failed"
    FLOOD_WAIT = "promo.flood_wait"
    PEER_FLOOD = "promo.peer_flood"
    CIRCUIT_OPEN = "promo.circuit_open"


class Forward:
    """Mirrors ``app.stats.StatsStore`` metric names under a ``forward.`` prefix."""

    FORWARDED = "forward.forwarded"
    PUBLISHED_SCHEDULED = "forward.published_scheduled"
    QUEUED = "forward.queued"
    BLOCKED = "forward.blocked"
    FILTERED_SKIP = "forward.filtered_skip"
    FILTERED_COPY = "forward.filtered_copy"
    MEDIA_SKIPPED = "forward.media_skipped"
    DEDUP_SKIPPED = "forward.dedup_skipped"
    DRY_RUN = "forward.dry_run"
    FAILED = "forward.failed"


class Discovery:
    JOINED = "discovery.joined"
    JOIN_FAILED = "discovery.join_failed"
    LINKS_HARVESTED = "discovery.links_harvested"
    INSPECTED = "discovery.inspected"


class LinkDir:
    QUERIES_RUN = "linkdir.queries_run"
    CHATS_FOUND = "linkdir.chats_found"
    ITEMS_UPSERTED = "linkdir.items_upserted"
    ITEMS_KEEP = "linkdir.items_keep"
    ITEMS_REVIEW = "linkdir.items_review"
    ITEMS_JUNK = "linkdir.items_junk"
    SNOWBALL_RESOLVED = "linkdir.snowball_resolved"
    JOBS_COMPLETED = "linkdir.jobs_completed"
    JOBS_FAILED = "linkdir.jobs_failed"
    ERRORS = "linkdir.errors"
    RUNS = "linkdir.runs"


class Ai:
    RUNS = "ai.runs"
    QUERIES_GENERATED = "ai.queries_generated"
    QUERIES_ACCEPTED = "ai.queries_accepted"
    QUERIES_REJECTED = "ai.queries_rejected"
    JOBS_ENQUEUED = "ai.jobs_enqueued"
    JOBS_SKIPPED = "ai.jobs_skipped"
    FAILURES = "ai.failures"


class Gauge:
    """Latest-value metrics — overwritten instead of summed."""

    LINKDIR_PROMO_READY = "linkdir.promo_ready"
    LINKDIR_CATALOG_TOTAL = "linkdir.catalog_total"
    PROMO_QUEUE_PENDING = "promo.queue_pending"
    FORWARD_QUEUE_PENDING = "forward.queue_pending"


def _keys_of(namespace: type) -> set[str]:
    return {
        value
        for name, value in vars(namespace).items()
        if not name.startswith("_") and isinstance(value, str)
    }


KNOWN_COUNTERS = frozenset(
    _keys_of(Promo)
    | _keys_of(Forward)
    | _keys_of(Discovery)
    | _keys_of(LinkDir)
    | _keys_of(Ai)
)

KNOWN_GAUGES = frozenset(_keys_of(Gauge))

KNOWN_METRICS = frozenset(KNOWN_COUNTERS | KNOWN_GAUGES)

FORWARD_STAT_METRICS = {
    name.rsplit(".", 1)[1]: name for name in _keys_of(Forward)
}
