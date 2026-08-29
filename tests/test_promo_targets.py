"""Tests for promo source/group entity resolution."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.promo_spread import targets


def _channel(*, channel_id: int, broadcast: bool, username: str | None = None):
    return SimpleNamespace(
        id=channel_id,
        access_hash=1,
        title=username or "test",
        broadcast=broadcast,
        megagroup=not broadcast,
        username=username,
    )


@pytest.mark.asyncio
async def test_ensure_source_channel_refreshes_stale_megagroup_cache() -> None:
    stale = _channel(channel_id=100, broadcast=False, username="aads_posts")
    fresh = _channel(channel_id=200, broadcast=True, username="aads_posts")
    client = AsyncMock()
    client.get_entity = AsyncMock(side_effect=[stale, fresh])
    client.get_me = AsyncMock(return_value=MagicMock())
    client.return_value = SimpleNamespace(chats=[fresh], users=[])

    entity, label = await targets.ensure_source_channel(
        client, "@aads_posts", auto_join=False
    )
    assert entity is fresh
    assert label == "@aads_posts"


@pytest.mark.asyncio
async def test_ensure_source_channel_rejects_non_broadcast_without_username() -> None:
    stale = _channel(channel_id=100, broadcast=False, username=None)
    client = MagicMock()
    client.get_entity = AsyncMock(return_value=stale)

    with pytest.raises(ValueError, match="broadcast"):
        await targets.ensure_source_channel(client, stale, auto_join=False)
