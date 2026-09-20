"""Daily destination cap and ashapazi 22:00 Tehran schedule."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from app.stats import StatsStore
from modules.channel_forward.dedup import DedupStore
from modules.channel_forward.delivery import DeliveryEngine
from modules.channel_forward.filters import TextFilterConfig
from modules.channel_forward.media_filter import MediaFilterConfig
from modules.channel_forward.queue import PublishQueue
from modules.channel_forward.quota import DailyQuotaStore, dest_quota_key
from modules.channel_forward.route_config import (
    DedupConfig,
    DeliveryConfig,
    ResolvedRoute,
    migrate_routes,
)
from modules.channel_forward.schedule import ScheduleConfig, ScheduleWindow
from modules.channel_forward.state import ForwardStateStore

TZ = ZoneInfo("Asia/Tehran")
ROOT = Path(__file__).resolve().parent.parent
FORWARDER1 = ROOT / "config" / "accounts" / "forwarder1.json"


def _msg(msg_id: int, text: str = "recipe") -> SimpleNamespace:
    return SimpleNamespace(
        id=msg_id,
        message=text,
        media=None,
        grouped_id=None,
        entities=None,
        chat_id=10,
    )


def _route(
    *,
    source: str = "@ide_food",
    dest: str = "@ashapazi_roozaneh",
    max_posts_per_day: int = 1,
    schedule_enabled: bool = False,
    dest_id: int = 200,
    source_id: int = 100,
) -> ResolvedRoute:
    return ResolvedRoute(
        source_ref=source.lstrip("@"),
        dest_ref=dest.lstrip("@"),
        source_id=source_id,
        dest_id=dest_id,
        source_entity=SimpleNamespace(),
        dest_entity=SimpleNamespace(title=dest),
        mode="copy",
        text_filter=TextFilterConfig(),
        media_filter=MediaFilterConfig(),
        schedule=ScheduleConfig(
            enabled=schedule_enabled,
            timezone="Asia/Tehran",
            max_posts_per_day=max_posts_per_day,
            windows=[ScheduleWindow(start="22:00", end="22:10")],
        ),
        dedup=DedupConfig(),
        delivery=DeliveryConfig(),
        route_key=f"{source}->{dest}",
        paused=False,
    )


def _engine(tmp_path: Path) -> tuple[DeliveryEngine, AsyncMock]:
    client = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(id=900)),
        send_file=AsyncMock(),
        forward_messages=AsyncMock(),
        pin_message=AsyncMock(),
    )
    engine = DeliveryEngine(
        client,
        queue=PublishQueue(tmp_path / "queue.json"),
        stats=StatsStore(tmp_path / "stats.json"),
        state=ForwardStateStore(tmp_path / "state.json"),
        dedup=DedupStore(tmp_path / "dedup.json"),
        quota=DailyQuotaStore(tmp_path / "quota.json"),
        delay_seconds=0,
        delay_jitter=0,
    )
    return engine, client


def test_dest_quota_key_normalizes_username() -> None:
    assert dest_quota_key("@ashapazi_roozaneh") == dest_quota_key("ashapazi_roozaneh")
    assert dest_quota_key("Ashapazi_Roozaneh") == "ashapazi_roozaneh"


def test_quota_shared_by_destination_and_resets_next_day(tmp_path: Path) -> None:
    store = DailyQuotaStore(tmp_path / "quota.json")
    day = datetime(2026, 9, 20, 22, 1, tzinfo=TZ)
    next_day = datetime(2026, 9, 21, 22, 1, tzinfo=TZ)
    key = dest_quota_key("@ashapazi_roozaneh")

    assert store.try_consume(key, limit=1, timezone="Asia/Tehran", at=day) is True
    assert store.try_consume(key, limit=1, timezone="Asia/Tehran", at=day) is False
    assert store.at_limit(key, limit=1, timezone="Asia/Tehran", at=day) is True
    assert store.try_consume(key, limit=1, timezone="Asia/Tehran", at=next_day) is True


def test_quota_refund_allows_retry(tmp_path: Path) -> None:
    store = DailyQuotaStore(tmp_path / "quota.json")
    key = "ashapazi_roozaneh"
    at = datetime(2026, 9, 20, 22, 3, tzinfo=TZ)
    assert store.try_consume(key, limit=1, timezone="Asia/Tehran", at=at)
    store.refund(key, timezone="Asia/Tehran", at=at)
    assert store.try_consume(key, limit=1, timezone="Asia/Tehran", at=at)


def test_schedule_window_covers_2200_tehran_not_neighbors() -> None:
    sched = ScheduleConfig.from_dict(
        {
            "enabled": True,
            "timezone": "Asia/Tehran",
            "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
            "windows": [{"start": "22:00", "end": "22:10"}],
            "max_posts_per_day": 1,
        }
    )
    assert sched.max_posts_per_day == 1
    assert sched.is_open(datetime(2026, 9, 20, 22, 0, tzinfo=TZ))
    assert sched.is_open(datetime(2026, 9, 20, 22, 10, tzinfo=TZ))
    assert not sched.is_open(datetime(2026, 9, 20, 21, 59, tzinfo=TZ))
    assert not sched.is_open(datetime(2026, 9, 20, 22, 11, tzinfo=TZ))
    sunday = datetime(2026, 9, 20, 22, 5, tzinfo=TZ)  # Sunday
    assert sunday.strftime("%a") == "Sun"
    assert sched.is_open(sunday)


def test_migrate_routes_keeps_max_posts_per_day() -> None:
    routes = migrate_routes(
        {
            "routes": [
                {
                    "source": "@ide_food",
                    "destination": "@ashapazi_roozaneh",
                    "enabled": True,
                    "schedule": {
                        "enabled": True,
                        "timezone": "Asia/Tehran",
                        "days": ["mon"],
                        "windows": [{"start": "22:00", "end": "22:10"}],
                        "max_posts_per_day": 1,
                    },
                }
            ]
        }
    )
    assert routes[0]["schedule"]["max_posts_per_day"] == 1
    assert routes[0]["schedule"]["windows"] == [{"start": "22:00", "end": "22:10"}]


def test_forwarder1_ashapazi_is_one_post_at_2200() -> None:
    profile = json.loads(FORWARDER1.read_text(encoding="utf-8"))
    routes = profile["modules"]["channel_forward"]["routes"]
    ashapazi = [r for r in routes if r.get("destination") == "@ashapazi_roozaneh"]
    others = [r for r in routes if r.get("destination") != "@ashapazi_roozaneh"]
    assert len(ashapazi) == 3

    by_source = {r["source"]: r for r in ashapazi}
    assert by_source["@ide_food"]["enabled"] is True
    assert by_source["@ide_food"]["paused"] is False
    assert by_source["@FoOdDeCooR"]["enabled"] is False
    assert by_source["@noonesir"]["enabled"] is False

    for route in ashapazi:
        sched = route["schedule"]
        assert sched["enabled"] is True
        assert sched["timezone"] == "Asia/Tehran"
        assert set(sched["days"]) == {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
        assert sched["windows"] == [{"start": "22:00", "end": "22:10"}]
        assert sched["max_posts_per_day"] == 1
        flt = route["filter"]
        assert flt["remove_links"] is True
        assert flt["remove_ids"] is True
        assert flt["block_enabled"] is True
        assert flt["suffix"] == "@ashapazi_roozaneh"

    # Unrelated routes (factready, etc.) stay unscheduled / uncapped.
    for route in others:
        assert route["schedule"].get("max_posts_per_day") in (None, 0)
        assert route["schedule"]["enabled"] is False


@pytest.mark.asyncio
async def test_engine_caps_one_successful_publish_per_dest(tmp_path: Path) -> None:
    engine, client = _engine(tmp_path)
    a = _route(source="@ide_food", source_id=1)
    b = _route(source="@FoOdDeCooR", source_id=2)

    assert await engine.process_messages([_msg(1)], a) is True
    assert client.send_message.await_count == 1
    assert await engine.process_messages([_msg(2)], a) is False
    assert await engine.process_messages([_msg(3)], b) is False
    assert client.send_message.await_count == 1
    assert engine.daily_cap_reached(a)
    assert engine.daily_cap_reached(b)


@pytest.mark.asyncio
async def test_engine_failed_publish_does_not_burn_quota(tmp_path: Path) -> None:
    engine, client = _engine(tmp_path)
    client.send_message.side_effect = RuntimeError("boom")
    client.forward_messages.side_effect = RuntimeError("boom")
    route = _route()

    assert await engine.process_messages([_msg(11)], route) is False
    assert engine.daily_cap_reached(route) is False

    client.send_message.side_effect = None
    client.send_message.return_value = SimpleNamespace(id=901)
    client.forward_messages.side_effect = None
    assert await engine.process_messages([_msg(12)], route) is True
