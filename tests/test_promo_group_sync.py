"""Unit tests for attaching linkdir groups onto registered ad channels."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import app.promo_group_sync as sync_mod


def _write_promo_account(root: Path, account_id: str, *, sources: list[str]) -> None:
    accounts_dir = root / "config" / "accounts"
    accounts_dir.mkdir(parents=True, exist_ok=True)
    (root / "config" / "accounts.json").write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": account_id,
                        "profile": f"config/accounts/{account_id}.json",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    routes = [
        {
            "source": src,
            "groups": [],
            "enabled": True,
            "paused": False,
            "mode": "forward",
        }
        for src in sources
    ]
    (accounts_dir / f"{account_id}.json").write_text(
        json.dumps(
            {
                "id": account_id,
                "modules": {
                    "promo_spread": {
                        "enabled": True,
                        "dry_run": True,
                        "auto_join": False,
                        "routes": routes,
                    }
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_sync_requires_registered_ad_channel(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sync_mod, "ROOT", tmp_path)
    monkeypatch.setattr(sync_mod, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(sync_mod, "ACCOUNTS_DIR", tmp_path / "config" / "accounts")
    _write_promo_account(tmp_path, "promo1", sources=[])
    try:
        sync_mod.sync()
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert "ad channels" in str(exc).lower() or "Add one" in str(exc)


def test_sync_attaches_groups_to_registered_channel_not_parent_seed(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(sync_mod, "ROOT", tmp_path)
    monkeypatch.setattr(sync_mod, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(sync_mod, "ACCOUNTS_DIR", tmp_path / "config" / "accounts")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("PROMO_RANK_MIN", "0")
    monkeypatch.setenv("PROMO_NEED_POSTABLE", "false")
    _write_promo_account(tmp_path, "promo1", sources=["@MyAds"])

    payload = {
        "items": [
            {
                "ref": "@linkdir_group_a",
                "rank_score": 0.9,
                "members_can_send": True,
                "parent_seed": "@WrongSeedFromDiscovery",
            },
            {
                "ref": "@linkdir_group_b",
                "rank_score": 0.8,
                "members_can_send": True,
                "parent_seed": "@AnotherSeed",
            },
        ]
    }
    with patch.object(sync_mod, "export_promo_ready", return_value=payload):
        assert sync_mod.sync() == 0

    profile = json.loads(
        (tmp_path / "config" / "accounts" / "promo1.json").read_text(encoding="utf-8")
    )
    routes = profile["modules"]["promo_spread"]["routes"]
    assert len(routes) == 1
    assert routes[0]["source"] == "@MyAds"
    groups = set(routes[0]["groups"])
    assert groups == {"@linkdir_group_a", "@linkdir_group_b"}
    assert profile["modules"]["promo_spread"]["auto_join"] is True
    assert "@WrongSeedFromDiscovery" not in json.dumps(profile)
