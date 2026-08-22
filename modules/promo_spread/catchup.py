"""Pick recent source posts that were missed while no promo run was alive."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

DEFAULT_PRIME_ENQUEUE_HOURS = 2.0


def select_catchup_posts(
    messages: list[Any],
    *,
    cutoff: datetime,
    limit: int,
) -> list[list[Any]]:
    """Group recent posts (albums stay together), oldest first, last ``limit``.

    ``messages`` may be Telethon ``Message`` objects or any duck-typed stand-in
    with ``id``, ``date``, optional ``grouped_id``, and optional ``action``.
    """
    if limit <= 0 or not messages:
        return []

    posts: dict[tuple[str, int], list[Any]] = {}
    for msg in messages:
        if getattr(msg, "action", None) is not None:
            continue
        msg_id = getattr(msg, "id", None)
        if not msg_id:
            continue
        when = getattr(msg, "date", None)
        if when is None:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when < cutoff:
            continue
        grouped = getattr(msg, "grouped_id", None)
        key = ("album", int(grouped)) if grouped else ("single", int(msg_id))
        posts.setdefault(key, []).append(msg)

    ordered = sorted(posts.values(), key=lambda ms: min(int(m.id) for m in ms))
    picked = ordered[-limit:]
    for group in picked:
        group.sort(key=lambda m: int(m.id))
    return picked


def is_fresh_enough_to_enqueue(
    messages: list[Any],
    *,
    now: datetime | None = None,
    max_age_hours: float = DEFAULT_PRIME_ENQUEUE_HOURS,
) -> bool:
    """True when the newest item is recent enough to send on a blank state file."""
    if max_age_hours <= 0:
        return False
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    newest: datetime | None = None
    for msg in messages:
        when = getattr(msg, "date", None)
        if when is None:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if newest is None or when > newest:
            newest = when
    if newest is None:
        return False
    return (moment - newest) <= timedelta(hours=max_age_hours)
