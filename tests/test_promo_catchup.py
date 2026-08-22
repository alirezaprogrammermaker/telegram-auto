from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from pathlib import Path

from modules.promo_spread.catchup import (
    is_fresh_enough_to_enqueue,
    select_catchup_posts,
)
from modules.promo_spread.queue import PromoQueue

ROOT = Path("data") / "_test_promo_catchup"


def _msg(
    msg_id: int,
    *,
    hours_ago: float = 1.0,
    grouped_id: int | None = None,
    action: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=msg_id,
        date=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        grouped_id=grouped_id,
        action=action,
    )


def test_select_catchup_keeps_albums_and_drops_old() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
    messages = [
        _msg(10, hours_ago=20),
        _msg(21, hours_ago=2, grouped_id=7),
        _msg(20, hours_ago=2, grouped_id=7),
        _msg(30, hours_ago=1),
        _msg(31, hours_ago=0.5, action="pin"),
    ]
    posts = select_catchup_posts(messages, cutoff=cutoff, limit=3)
    assert [[m.id for m in group] for group in posts] == [[20, 21], [30]]


def test_fresh_post_enqueues_even_when_state_is_blank() -> None:
    assert is_fresh_enough_to_enqueue([_msg(40, hours_ago=0.5)]) is True
    assert is_fresh_enough_to_enqueue([_msg(41, hours_ago=5)]) is False


def test_select_catchup_limit_keeps_newest() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
    messages = [_msg(i, hours_ago=3 - (i * 0.1)) for i in range(1, 6)]
    posts = select_catchup_posts(messages, cutoff=cutoff, limit=2)
    assert [[m.id for m in group] for group in posts] == [[4], [5]]


def _queue(name: str) -> PromoQueue:
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / f"{name}.json"
    if path.exists():
        path.unlink()
    return PromoQueue(path=path)


def test_catchup_primes_empty_history() -> None:
    q = _queue("prime")
    assert q.has_seen_history() is False
    assert q.try_claim_post_seen("1:30-30") is True
    assert q.post_seen("1:30-30") is True
    assert q.has_seen_history() is True
    assert q.try_claim_post_seen("1:30-30") is False


def test_enqueue_duplicate_pending_returns_none() -> None:
    q = _queue("dup")
    first = q.enqueue(
        source_id=1,
        group_ref="@g1",
        group_id=11,
        message_ids=[30],
        mode="forward",
        post_key="1:30-30",
    )
    again = q.enqueue(
        source_id=1,
        group_ref="@g1",
        group_id=11,
        message_ids=[30],
        mode="forward",
        post_key="1:30-30",
    )
    assert first
    assert again is None
    assert q.pending_count() == 1
