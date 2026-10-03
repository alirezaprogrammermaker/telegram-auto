"""Tests for the commutative data/pool snapshot merge used by Actions."""
from __future__ import annotations

import json

from scripts.merge_pool_cache import main, merge_catalog, merge_group_pool


def test_merge_catalog_unions_items_by_key(tmp_path) -> None:
    dst = {"version": 1, "items": {}, "meta": {}}
    src = {
        "version": 1,
        "items": {
            "a": {
                "key": "a",
                "ref": "@a",
                "rank_score": 70.0,
                "last_ranked_at": "2026-01-01T00:00:00+00:00",
            },
            "b": {
                "key": "b",
                "ref": "@b",
                "rank_score": 60.0,
                "last_ranked_at": "2026-01-02T00:00:00+00:00",
            },
        },
        "meta": {"pipeline_runs": [{"at": "2026-01-02", "ok": True}]},
    }
    dst["items"]["a"] = {
        "key": "a",
        "ref": "@a",
        "rank_score": 80.0,
        "last_ranked_at": "2026-01-05T00:00:00+00:00",
    }
    touched = merge_catalog(dst, src)
    # 'a' collision: dst is newer -> untouched; 'b' is new -> added
    assert touched == 1
    # dst wins the 'a' collision (newer last_ranked_at)
    assert dst["items"]["a"]["rank_score"] == 80.0
    assert dst["items"]["b"]["rank_score"] == 60.0
    # pipeline history merged
    assert len(dst["meta"]["pipeline_runs"]) == 1
    assert dst["meta"]["pipeline_runs"][0]["at"] == "2026-01-02"


def test_merge_group_pool_unions_by_updated_at(tmp_path) -> None:
    dst = {"version": 1, "items": {}}
    src = {
        "version": 1,
        "items": {
            "k": {
                "key": "k",
                "ref": "@k",
                "status": "approved",
                "updated_at": "2026-02-01T00:00:00+00:00",
            }
        },
    }
    dst["items"]["k"] = {
        "key": "k",
        "ref": "@k",
        "status": "raw",
        "updated_at": "2026-03-01T00:00:00+00:00",
    }
    merge_group_pool(dst, src)
    # dst is newer — keep raw (approval not clobbered)
    assert dst["items"]["k"]["status"] == "raw"


def test_main_noop_when_snapshot_missing(tmp_path, capsys) -> None:
    pool = tmp_path / "pool"
    pool.mkdir()
    code = main([__file__, str(tmp_path / "missing"), str(pool)])
    assert code == 0
    out = capsys.readouterr().out
    assert "no-op" in out


def test_main_merges_snapshot_files(tmp_path, capsys) -> None:
    snap = tmp_path / "snap"
    pool = tmp_path / "pool"
    snap.mkdir()
    pool.mkdir()

    (snap / "linkdir_catalog.json").write_text(
        json.dumps(
            {
                "version": 1,
                "items": {
                    "x": {
                        "key": "x",
                        "ref": "@x",
                        "rank_score": 55.0,
                        "last_ranked_at": "2026-04-01T00:00:00+00:00",
                    }
                },
                "meta": {},
            }
        ),
        encoding="utf-8",
    )
    (snap / "linkdir_verify_last.json").write_text(
        json.dumps({"at": "2026-04-01T00:00:00+00:00", "ok": True}),
        encoding="utf-8",
    )

    code = main([__file__, str(snap), str(pool)])
    assert code == 0
    merged = json.loads((pool / "linkdir_catalog.json").read_text(encoding="utf-8"))
    assert "x" in merged["items"]
    # snapshot copy of verify file propagated
    verify = json.loads((pool / "linkdir_verify_last.json").read_text(encoding="utf-8"))
    assert verify["ok"] is True
