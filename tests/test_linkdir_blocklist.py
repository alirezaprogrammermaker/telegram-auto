"""Tests for linkdir ref blocklist."""
from __future__ import annotations

from experiments.linkdir_finders.blocklist import (
    blocklist_from_config,
    filter_blocked_rows,
    is_blocked,
    normalize_username,
)


def test_normalize_username():
    assert normalize_username("@Telegram") == "telegram"
    assert normalize_username("Durov") == "durov"
    assert normalize_username("id:123") is None


def test_default_blocklist():
    cfg = {"blocklist": {"use_defaults": True, "usernames": []}}
    blocked = blocklist_from_config(cfg)
    assert "telegram" in blocked
    assert "linkdir_py_smoke" in blocked


def test_custom_blocklist():
    cfg = {"blocklist": {"use_defaults": False, "usernames": ["@MyBadRef"]}}
    blocked = blocklist_from_config(cfg)
    assert "mybadref" in blocked
    assert "telegram" not in blocked


def test_is_blocked():
    cfg = {"blocklist": {"use_defaults": True, "usernames": []}}
    assert is_blocked("@Telegram", cfg=cfg)
    assert not is_blocked("@Links_international", cfg=cfg)


def test_filter_blocked_rows():
    cfg = {"blocklist": {"use_defaults": True, "usernames": []}}
    rows = [
        {"ref": "@Telegram", "username": "Telegram"},
        {"ref": "@Links_international", "username": "Links_international"},
    ]
    out = filter_blocked_rows(rows, cfg=cfg)
    assert len(out) == 1
    assert out[0]["ref"] == "@Links_international"
