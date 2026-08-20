"""Reward attribution for the linkdir query agent.

Catalog rows carry a human-meaningful verdict (``keep``/``review``/``junk``)
and the query that surfaced them. That is the reward signal: it says whether a
generated query was worth issuing. This module turns a pile of catalog rows
into one scalar per query.

The formula
-----------
For a query that produced ``keep`` (k), ``review`` (r) and ``junk`` (j) rows,
with ``total = k + r + j``::

    useful   = k + 0.35 * r
    quality  = clamp(useful / total - 0.25 * (j / total), 0, 1)
    volume   = min(1, log1p(useful) / log1p(12))
    strength = mean(rank_score of non-junk rows) / 100      (0.5 when unknown)
    reward   = clamp(0.65 * quality + 0.35 * volume
                     + 0.10 * (strength - 0.5), 0, 1)

Why this shape:

* ``quality`` is precision-like and volume-independent: a query that returns
  three rows, all keeps, is a good query even though it is a small one. A
  ``review`` is a real but unconfirmed hit, so it earns partial credit; junk is
  subtracted rather than merely ignored, because a query that floods the
  catalog with noise costs collector budget.
* ``volume`` is logarithmic and saturates at 12 useful hits. This is the term
  that stops one high-volume query from dominating: going from 1 to 5 useful
  hits moves the score a lot, going from 40 to 200 moves it not at all. Without
  it the agent would learn to emit maximally generic queries.
* ``strength`` is a small, bounded nudge from the ranker's own opinion of the
  rows. It defaults to neutral (0.5, contributing exactly zero) so a catalog
  without rank scores produces the same reward as before the term existed.

Edge cases: a query with no catalog rows at all scores 0.0, as does an
all-junk query. An all-keep query with enough volume scores 1.0.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Iterable

logger = logging.getLogger("linkdir_finders.reward")

REVIEW_CREDIT = 0.35
JUNK_PENALTY = 0.25
VOLUME_SATURATION = 12.0
QUALITY_WEIGHT = 0.65
VOLUME_WEIGHT = 0.35
STRENGTH_WEIGHT = 0.10
NEUTRAL_STRENGTH = 0.5
RANK_SCALE = 100.0

VERDICTS = ("keep", "review", "junk")


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def row_queries(row: dict[str, Any]) -> list[str]:
    """Every query a catalog row can be attributed to."""
    out: list[str] = []
    single = row.get("query")
    if isinstance(single, str) and single.strip():
        out.append(single.strip())
    many = row.get("queries")
    if isinstance(many, str):
        try:
            many = json.loads(many)
        except (json.JSONDecodeError, ValueError):
            many = []
    if isinstance(many, list):
        out.extend(str(q).strip() for q in many if str(q).strip())
    return out


def compute_reward(
    *,
    keep: int,
    review: int,
    junk: int,
    rank_scores: Iterable[float] | None = None,
) -> float:
    """Scalar reward in ``[0, 1]`` for one query's catalog outcome."""
    keep = max(0, int(keep))
    review = max(0, int(review))
    junk = max(0, int(junk))
    total = keep + review + junk
    if total <= 0:
        return 0.0

    useful = keep + REVIEW_CREDIT * review
    quality = _clamp(useful / total - JUNK_PENALTY * (junk / total))
    volume = _clamp(math.log1p(useful) / math.log1p(VOLUME_SATURATION))

    scores = [float(s) for s in (rank_scores or []) if isinstance(s, (int, float))]
    strength = (
        _clamp(sum(scores) / len(scores) / RANK_SCALE) if scores else NEUTRAL_STRENGTH
    )

    return round(
        _clamp(
            QUALITY_WEIGHT * quality
            + VOLUME_WEIGHT * volume
            + STRENGTH_WEIGHT * (strength - NEUTRAL_STRENGTH)
        ),
        4,
    )


@dataclass
class QueryOutcome:
    """Aggregated catalog verdicts for a single originating query."""

    query: str
    keep_count: int = 0
    review_count: int = 0
    junk_count: int = 0
    rank_scores: list[float] = field(default_factory=list)

    @property
    def results_total(self) -> int:
        return self.keep_count + self.review_count + self.junk_count

    def add(self, verdict: str, rank_score: Any = None) -> None:
        if verdict == "keep":
            self.keep_count += 1
        elif verdict == "review":
            self.review_count += 1
        else:
            self.junk_count += 1
        if verdict != "junk" and isinstance(rank_score, (int, float)):
            self.rank_scores.append(float(rank_score))

    def reward(self) -> float:
        return compute_reward(
            keep=self.keep_count,
            review=self.review_count,
            junk=self.junk_count,
            rank_scores=self.rank_scores,
        )

    def as_outcome(self, subject_key: str) -> dict[str, Any]:
        """Payload row for ``POST /internal/agentmem/score``."""
        return {
            "subject_key": subject_key,
            "results_total": self.results_total,
            "keep_count": self.keep_count,
            "review_count": self.review_count,
            "junk_count": self.junk_count,
            "reward": self.reward(),
        }


def group_catalog_rows(rows: Iterable[Any]) -> dict[str, QueryOutcome]:
    """Bucket catalog rows by the query that surfaced them.

    Keys are the raw stripped query strings, matching what the seeder hashed
    into ``subject_key`` — normalizing here would break that correspondence.
    A row listing several queries credits (or debits) all of them.
    """
    grouped: dict[str, QueryOutcome] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        verdict = str(row.get("verdict") or "junk").strip().lower()
        if verdict not in VERDICTS:
            verdict = "junk"
        rank_score = row.get("rank_score")
        if rank_score is None:
            rank_score = row.get("identity_score")
        for query in row_queries(row):
            outcome = grouped.get(query)
            if outcome is None:
                outcome = QueryOutcome(query=query)
                grouped[query] = outcome
            outcome.add(verdict, rank_score)
    return grouped
