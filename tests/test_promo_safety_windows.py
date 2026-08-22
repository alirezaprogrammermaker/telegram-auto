from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from modules.promo_spread.safety import SafetyConfig, SafetyGuard

TZ = ZoneInfo("Asia/Tehran")
ROOT = Path("data") / "_test_promo_safety"


def _guard(name: str, windows: list[dict[str, str]] | None = None) -> SafetyGuard:
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / f"{name}.json"
    if path.exists():
        path.unlink()
    cfg = SafetyConfig.from_dict(
        {"timezone": "Asia/Tehran", "active_windows": windows}
        if windows is not None
        else {"timezone": "Asia/Tehran"}
    )
    return SafetyGuard(cfg, path=path)


def test_default_window_covers_late_evening(monkeypatch) -> None:
    guard = _guard("late")
    monkeypatch.setattr(
        guard, "now", lambda: datetime(2026, 8, 22, 23, 29, tzinfo=TZ)
    )
    active, why = guard.is_active_now()
    assert active is True, why


def test_old_2200_cutoff_would_block_tonight(monkeypatch) -> None:
    guard = _guard(
        "old",
        [{"start": "09:30", "end": "13:00"}, {"start": "16:00", "end": "22:00"}],
    )
    monkeypatch.setattr(
        guard, "now", lambda: datetime(2026, 8, 22, 23, 29, tzinfo=TZ)
    )
    active, why = guard.is_active_now()
    assert active is False
    assert "بازه" in why


def test_after_midnight_is_quiet(monkeypatch) -> None:
    guard = _guard("midnight")
    monkeypatch.setattr(
        guard, "now", lambda: datetime(2026, 8, 23, 0, 15, tzinfo=TZ)
    )
    active, _ = guard.is_active_now()
    assert active is False


def test_six_am_is_active(monkeypatch) -> None:
    guard = _guard("dawn")
    monkeypatch.setattr(
        guard, "now", lambda: datetime(2026, 8, 23, 6, 0, tzinfo=TZ)
    )
    active, why = guard.is_active_now()
    assert active is True, why


def test_quiet_hours_to_windows_midnight_to_six() -> None:
    from modules.promo_spread.safety import quiet_hours_to_windows

    assert quiet_hours_to_windows("00:00", "06:00") == [
        {"start": "06:00", "end": "23:59"}
    ]
    assert quiet_hours_to_windows("22:00", "08:00") == [
        {"start": "08:00", "end": "22:00"}
    ]


def test_quiet_hours_after_grace(monkeypatch) -> None:
    guard = _guard("after")
    monkeypatch.setattr(
        guard, "now", lambda: datetime(2026, 8, 23, 0, 45, tzinfo=TZ)
    )
    active, _ = guard.is_active_now()
    assert active is False


def test_afternoon_is_active(monkeypatch) -> None:
    guard = _guard("gap")
    monkeypatch.setattr(
        guard, "now", lambda: datetime(2026, 8, 22, 14, 30, tzinfo=TZ)
    )
    active, why = guard.is_active_now()
    assert active is True, why
