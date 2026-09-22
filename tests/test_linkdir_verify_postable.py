"""Tests for experimental postable-verify candidate selection."""
from __future__ import annotations

from typing import Any

from experiments.linkdir_finders.method_verify_postable import (
    _load_verify_pool,
    select_verify_candidates,
)


class _FakeCatalog:
    def __init__(self, *, review: list[dict[str, Any]], top: list[dict[str, Any]]) -> None:
        self._review = review
        self._top = top

    def list_items(self, **kwargs: Any) -> list[dict[str, Any]]:
        if kwargs.get("status") == "review":
            return list(self._review)
        if kwargs.get("promo_ready") is True:
            return [r for r in self._top if r.get("promo_ready")]
        return list(self._top)

    def _local_list_items(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []


def test_load_verify_pool_prefers_review_unknowns_over_known_keeps() -> None:
    catalog = _FakeCatalog(
        review=[
            {
                "username": "review_unknown",
                "members_can_send": None,
                "rank_score": 70,
            }
        ],
        top=[
            {
                "username": "keep_known",
                "members_can_send": True,
                "rank_score": 99,
                "promo_ready": True,
            },
            {
                "username": "review_unknown",
                "members_can_send": None,
                "rank_score": 70,
            },
        ],
    )
    rows = _load_verify_pool(catalog, pool_limit=40)
    assert [r["username"] for r in rows] == ["review_unknown", "keep_known"]
    picked = select_verify_candidates(rows, limit=5, min_rank=50, min_identity=0)
    assert [r["username"] for r in picked] == ["review_unknown"]


def test_select_verify_candidates_prefers_unknown_postable_high_rank() -> None:
    rows = [
        {
            "username": "good_unknown",
            "kind": "megagroup",
            "verdict": "review",
            "status": "review",
            "members_can_send": None,
            "rank_score": 80,
            "identity_score": 60,
        },
        {
            "username": "already_true",
            "kind": "megagroup",
            "verdict": "keep",
            "status": "active",
            "members_can_send": True,
            "rank_score": 99,
            "identity_score": 90,
        },
        {
            "username": "broadcast",
            "kind": "broadcast_channel",
            "verdict": "review",
            "status": "review",
            "members_can_send": None,
            "rank_score": 90,
            "identity_score": 80,
        },
        {
            "username": "low_rank",
            "kind": "megagroup",
            "verdict": "review",
            "status": "review",
            "members_can_send": None,
            "rank_score": 20,
            "identity_score": 60,
        },
        {
            "ref": "https://t.me/+abc",
            "username": None,
            "kind": "megagroup",
            "verdict": "review",
            "members_can_send": None,
            "rank_score": 85,
            "identity_score": 70,
        },
    ]
    picked = select_verify_candidates(
        rows, limit=5, min_rank=50, min_identity=35
    )
    assert [r["username"] for r in picked] == ["good_unknown"]


def test_select_verify_candidates_respects_limit() -> None:
    rows = [
        {
            "username": f"g{i}",
            "kind": "megagroup",
            "verdict": "review",
            "members_can_send": None,
            "rank_score": 70 - i,
            "identity_score": 50,
        }
        for i in range(10)
    ]
    picked = select_verify_candidates(
        rows, limit=3, min_rank=50, min_identity=35
    )
    assert len(picked) == 3
    assert picked[0]["username"] == "g0"
