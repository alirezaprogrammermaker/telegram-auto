from datetime import datetime, timedelta, timezone

from app.login_errors import (
    format_flood_wait_error,
    parse_flood_wait,
    remaining_flood_wait,
    wait_label,
)


def test_format_and_parse_roundtrip() -> None:
    now = datetime(2026, 8, 20, 10, 12, tzinfo=timezone.utc)
    error = format_flood_wait_error(7096, now=now)
    parsed = parse_flood_wait(error)
    assert parsed is not None
    assert parsed["wait_seconds"] == 7096
    remaining = remaining_flood_wait(error, now=now + timedelta(seconds=96))
    assert remaining == 7000


def test_remaining_zero_after_until() -> None:
    now = datetime(2026, 8, 20, 10, 12, tzinfo=timezone.utc)
    error = format_flood_wait_error(60, now=now)
    assert remaining_flood_wait(error, now=now + timedelta(seconds=120)) == 0


def test_non_flood_error_is_ignored() -> None:
    assert parse_flood_wait("workflow_failure") is None
    assert remaining_flood_wait("PhoneCodeInvalidError") is None


def test_wait_label() -> None:
    assert "ساعت" in wait_label(7096)
    assert wait_label(30).endswith("ثانیه")
