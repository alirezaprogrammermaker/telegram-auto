"""Exclusive promo destination ownership."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import app.promo_exclusivity as ex
import app.promo_group_sync as sync_mod


def _profile(sources_groups: dict[str, list[str]]) -> dict:
    routes = [
        {
            "source": src,
            "groups": list(groups),
            "enabled": True,
            "paused": False,
            "mode": "forward",
        }
        for src, groups in sources_groups.items()
    ]
    return {
        "modules": {
            "promo_spread": {
                "enabled": True,
                "routes": routes,
                "auto_join": True,
            }
        }
    }


def test_reconcile_removes_overlap_keeps_uncontested() -> None:
    profiles = [
        ("promo1", _profile({"@ads": ["@A", "@Shared"]})),
        ("promo2", _profile({"@ads": ["@B", "@Shared"]})),
        ("promo3", _profile({"@ads": ["@Shared"]})),
    ]
    overlaps = ex.find_overlaps(profiles)
    assert "shared" in overlaps or any("shared" in k.lower() for k in overlaps)
    # normalize_ref lowercases? ShareTelegram -> shared via @Shared -> Shared?
    # normalize_ref strips @ so key is "Shared" as stored... group_norm_key("@Shared") -> "Shared"
    assert "Shared" in overlaps

    result = ex.reconcile_exclusive_profiles(profiles)
    assert result["overlaps_before"] >= 1
    assert result["overlaps_after"] == 0
    assert not ex.find_overlaps(profiles)

    # Uncontested groups stay on original accounts
    p1_groups = {
        g
        for _s, g, _n in ex._iter_route_groups(profiles[0][1])
    }
    p2_groups = {
        g
        for _s, g, _n in ex._iter_route_groups(profiles[1][1])
    }
    assert "@A" in p1_groups
    assert "@B" in p2_groups


def test_claim_group_strips_others() -> None:
    profiles = [
        ("promo1", _profile({"@ads": ["@G1"]})),
        ("promo2", _profile({"@ads": ["@G1", "@G2"]})),
    ]
    ex.claim_group(profiles, owner_id="promo1", group_ref="@G1", source="@ads")
    p1 = {n for _s, _r, n in ex._iter_route_groups(profiles[0][1])}
    p2 = {n for _s, _r, n in ex._iter_route_groups(profiles[1][1])}
    assert "G1" in p1
    assert "G1" not in p2
    assert "G2" in p2


def test_rightful_owner_stable_sorted() -> None:
    a = ex.rightful_owner("@GroupX", ["promo3", "promo1", "promo2"])
    b = ex.rightful_owner("@GroupX", ["promo2", "promo3", "promo1"])
    assert a == b


def test_foreign_group_norms_blocks_contested_loser() -> None:
    profiles = [
        ("promo1", _profile({"@ads": ["@Shared"]})),
        ("promo2", _profile({"@ads": ["@Shared"]})),
    ]
    winner = ex.rightful_owner("@Shared", ["promo1", "promo2"])
    loser = "promo2" if winner == "promo1" else "promo1"
    blocked = ex.foreign_group_norms_for_account(loser, profiles)
    assert "Shared" in blocked
    blocked_winner = ex.foreign_group_norms_for_account(winner, profiles)
    assert "Shared" not in blocked_winner


def test_sync_multi_account_no_overlap(monkeypatch) -> None:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="promo-ex-") as raw:
        tmp_path = Path(raw)
        monkeypatch.setattr(sync_mod, "ROOT", tmp_path)
        monkeypatch.setattr(sync_mod, "CONFIG_DIR", tmp_path / "config")
        monkeypatch.setattr(sync_mod, "ACCOUNTS_DIR", tmp_path / "config" / "accounts")
        monkeypatch.setenv("DRY_RUN", "false")
        monkeypatch.setenv("PROMO_RANK_MIN", "0")
        monkeypatch.setenv("PROMO_NEED_POSTABLE", "false")

        accounts_dir = tmp_path / "config" / "accounts"
        accounts_dir.mkdir(parents=True)
        (tmp_path / "config" / "accounts.json").write_text(
            json.dumps(
                {
                    "accounts": [
                        {"id": "promo1", "profile": "config/accounts/promo1.json"},
                        {"id": "promo2", "profile": "config/accounts/promo2.json"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        for aid in ("promo1", "promo2"):
            (accounts_dir / f"{aid}.json").write_text(
                json.dumps(
                    {
                        "id": aid,
                        "modules": {
                            "promo_spread": {
                                "enabled": True,
                                "auto_join": True,
                                "routes": [
                                    {
                                        "source": "@MyAds",
                                        "groups": ["@AlreadyShared"],
                                        "enabled": True,
                                        "paused": False,
                                        "mode": "forward",
                                    }
                                ],
                            }
                        },
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

        payload = {
            "items": [
                {"ref": "@new_a", "rank_score": 0.9, "members_can_send": True},
                {"ref": "@new_b", "rank_score": 0.8, "members_can_send": True},
                {"ref": "@AlreadyShared", "rank_score": 0.7, "members_can_send": True},
            ]
        }
        with patch.object(sync_mod, "export_promo_ready", return_value=payload):
            assert sync_mod.sync() == 0

        loaded = []
        for aid in ("promo1", "promo2"):
            profile = json.loads(
                (accounts_dir / f"{aid}.json").read_text(encoding="utf-8")
            )
            loaded.append((aid, profile))
        assert ex.find_overlaps(loaded) == {}
