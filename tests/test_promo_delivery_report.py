from __future__ import annotations

from modules.promo_spread import report


def test_report_promo_delivery_posts_when_bridge_configured(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    monkeypatch.setattr(report, "_account_id", lambda: "promo2")
    monkeypatch.setattr(
        "app.bridge_client.bridge_configured",
        lambda: True,
    )

    def fake_request(method, path, payload=None, timeout=12.0):
        calls.append((path, dict(payload or {})))
        return {"ok": True}

    monkeypatch.setattr("app.bridge_client.bridge_request", fake_request)

    report.report_promo_delivery(
        job_id="abc123",
        post_key="1:10-10",
        group_ref="@g1",
        status="delivered",
        source_id=1,
        message_ids=[10],
        group_id=99,
        mode="forward",
    )
    assert len(calls) == 1
    path, payload = calls[0]
    assert path == "/internal/promo/delivery"
    assert payload["account_id"] == "promo2"
    assert payload["status"] == "delivered"
    assert payload["group_ref"] == "@g1"


def test_report_promo_seen_includes_jobs(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(report, "_account_id", lambda: "promo2")
    monkeypatch.setattr("app.bridge_client.bridge_configured", lambda: True)
    monkeypatch.setattr(
        "app.bridge_client.bridge_request",
        lambda method, path, payload=None, timeout=12.0: calls.append(
            (path, dict(payload or {}))
        )
        or {"ok": True},
    )

    report.report_promo_seen(
        post_key="1:10-10",
        source_ref="@aads_posts",
        source_id=1,
        message_ids=[10],
        jobs=[{"job_id": "j1", "group_ref": "@g1", "group_id": 11}],
        mode="forward",
    )
    assert calls[0][0] == "/internal/promo/seen"
    assert calls[0][1]["total_targets"] == 1
    assert calls[0][1]["jobs"][0]["job_id"] == "j1"


def test_report_skips_without_bridge(monkeypatch) -> None:
    monkeypatch.setattr(report, "_account_id", lambda: "promo2")
    monkeypatch.setattr("app.bridge_client.bridge_configured", lambda: False)

    def boom(*_a, **_k):
        raise AssertionError("should not call bridge")

    monkeypatch.setattr("app.bridge_client.bridge_request", boom)
    report.report_promo_delivery(
        job_id="x",
        post_key="1:1-1",
        group_ref="@g",
        status="failed",
        error="x",
    )
