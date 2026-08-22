"""Telemetry buffer semantics: durability, settle-after-flush, validation."""
from __future__ import annotations

import json

import pytest

from app.metrics_catalog import Forward, Promo
from app.telemetry import Telemetry


@pytest.fixture()
def store(tmp_path):
    return Telemetry(path=tmp_path / "telemetry.json", account_id="promo9")


def test_counters_accumulate_per_day(store) -> None:
    store.incr(Promo.DELIVERED)
    store.incr(Promo.DELIVERED, 4)
    store.incr(Promo.FAILED)

    today = store.today_counters()
    assert today[Promo.DELIVERED] == 5
    assert today[Promo.FAILED] == 1


def test_counters_survive_a_restart(store, tmp_path) -> None:
    store.incr(Forward.FORWARDED, 3)

    reopened = Telemetry(path=tmp_path / "telemetry.json", account_id="promo9")
    assert reopened.today_counters()[Forward.FORWARDED] == 3


def test_malformed_metrics_are_ignored(store) -> None:
    store.incr("NotAMetric")
    store.incr("missing_category")
    store.incr("promo.delivered", 0)

    assert store.today_counters() == {}


def test_flush_clears_only_what_was_delivered(store, monkeypatch) -> None:
    store.incr(Promo.DELIVERED, 2)
    sent: list[dict] = []

    def fake_send(payload, *, timeout):
        sent.append(payload)
        # A concurrent event lands between snapshot and settle.
        store.incr(Promo.DELIVERED, 3)
        return True

    monkeypatch.setattr(store, "_send", fake_send)
    assert store.flush(force=True) is True

    assert sent[0]["account_id"] == "promo9"
    assert sent[0]["days"][store.today()][Promo.DELIVERED] == 2
    assert store.today_counters()[Promo.DELIVERED] == 3


def test_failed_flush_keeps_the_buffer(store, monkeypatch) -> None:
    store.incr(Promo.DELIVERED, 7)
    monkeypatch.setattr(store, "_send", lambda payload, *, timeout: False)

    assert store.flush(force=True) is False
    assert store.today_counters()[Promo.DELIVERED] == 7


def test_flush_is_throttled_unless_forced(store, monkeypatch) -> None:
    store.incr(Promo.DELIVERED)
    monkeypatch.setattr(store, "_send", lambda payload, *, timeout: True)

    assert store.flush(force=True) is True
    store.incr(Promo.DELIVERED)
    assert store.flush() is False


def test_gauges_keep_only_the_latest_value(store, tmp_path) -> None:
    store.gauge("promo.queue_pending", 12)
    store.gauge("promo.queue_pending", 4)

    saved = json.loads((tmp_path / "telemetry.json").read_text(encoding="utf-8"))
    assert saved["gauges"]["promo.queue_pending"] == 4


def test_old_days_are_pruned(store) -> None:
    for day in range(1, 25):
        store.incr(Promo.DELIVERED, day=f"2026-01-{day:02d}")

    days = store.snapshot()["days"]
    assert len(days) == 14
    assert "2026-01-01" not in days
    assert "2026-01-24" in days
