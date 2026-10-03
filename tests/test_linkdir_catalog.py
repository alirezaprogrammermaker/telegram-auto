from experiments.linkdir_finders.catalog import LinkDirCatalog, should_persist_row
from experiments.linkdir_finders.job_queue import queries_for_set
from experiments.linkdir_finders.settings import load_config


def test_keep_and_review_always_persist() -> None:
    assert should_persist_row({"verdict": "keep", "rank_score": 10, "identity_score": 10})
    assert should_persist_row({"verdict": "review", "rank_score": 10, "identity_score": 10})


def test_low_signal_junk_is_skipped() -> None:
    assert not should_persist_row(
        {"verdict": "junk", "rank_score": 20, "identity_score": 10, "username": "x"}
    )
    assert not should_persist_row(
        {
            "verdict": "junk",
            "rank_score": 50,
            "identity_score": 40,
            "username": "",
        }
    )


def test_borderline_junk_with_username_persists() -> None:
    assert should_persist_row(
        {
            "verdict": "junk",
            "rank_score": 45,
            "identity_score": 36,
            "username": "SomeLinkDir",
        }
    )


def test_review_with_members_can_send_becomes_promo_ready(tmp_path) -> None:
    cat = LinkDirCatalog(path=tmp_path / "catalog.json", collector_id="test")
    out = cat.upsert_from_search(
        {
            "username": "PostableReviewGrp",
            "title": "لینکدونی تست",
            "verdict": "review",
            "rank_score": 62,
            "identity_score": 55,
            "quality_score": 40,
            "members_can_send": True,
            "postable": True,
            "promo_eligible": True,
            "is_group": True,
        },
        method="test",
    )
    assert out.get("promo_ready") is True
    assert out.get("status") == "active"
    assert out.get("members_can_send") is True


def test_query_shards_are_non_empty() -> None:
    cfg = load_config()
    fa = queries_for_set(cfg, "fa")
    en = queries_for_set(cfg, "en")
    niche = queries_for_set(cfg, "niche")
    assert fa and en and niche
    assert "لینکدونی" in fa
    assert "link exchange" in en
    assert not set(fa) & set(en)


def _backdate(cat: LinkDirCatalog, username: str, age_hours: float) -> None:
    """Rewrite last_ranked_at/last_seen_at on a persisted row to N hours ago."""
    from datetime import datetime, timedelta, timezone

    last = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
    with cat._lock:
        for item in cat._data.get("items", {}).values():
            if isinstance(item, dict) and item.get("username") == username:
                item["last_ranked_at"] = last
                item["last_seen_at"] = last


def test_mark_stale_grace_protects_high_rank_active(tmp_path) -> None:
    cat = LinkDirCatalog(path=tmp_path / "catalog.json")
    cat.upsert_from_search(
        {"username": "StrongDir", "verdict": "keep", "rank_score": 92.0,
         "identity_score": 60, "members_can_send": True},
        method="test",
    )
    cat.upsert_from_search(
        {"username": "WeakDir", "verdict": "keep", "rank_score": 55.0,
         "identity_score": 60, "members_can_send": True},
        method="test",
    )
    _backdate(cat, "StrongDir", 100)
    _backdate(cat, "WeakDir", 100)

    # Without grace: both 100h-old active items go stale
    n = cat.mark_stale(older_than_hours=72, stale_rank_grace=0)
    assert n == 2
    assert cat.list_items(status="stale", limit=10)

    # With grace: rank>=80 active items survive; weaker ones still demote
    cat2 = LinkDirCatalog(path=tmp_path / "catalog2.json")
    cat2.upsert_from_search(
        {"username": "StrongDir", "verdict": "keep", "rank_score": 92.0,
         "identity_score": 60, "members_can_send": True},
        method="test",
    )
    cat2.upsert_from_search(
        {"username": "WeakDir", "verdict": "keep", "rank_score": 55.0,
         "identity_score": 60, "members_can_send": True},
        method="test",
    )
    _backdate(cat2, "StrongDir", 100)
    _backdate(cat2, "WeakDir", 100)
    n2 = cat2.mark_stale(older_than_hours=72, stale_rank_grace=80)
    assert n2 == 1
    active = [
        r for r in cat2.list_items(status="active", limit=50)
        if r.get("username") == "StrongDir"
    ]
    assert active and active[0].get("promo_ready") is True


def test_mark_stale_review_items_are_not_graced(tmp_path) -> None:
    # Grace only protects status=active; demoted review rows still go stale.
    cat = LinkDirCatalog(path=tmp_path / "catalog.json")
    cat.upsert_from_search(
        {
            "username": "LockedDir",
            "verdict": "keep",
            "rank_score": 90.0,
            "identity_score": 60,
            "members_can_send": False,  # keep but not postable -> review
        },
        method="test",
    )
    item = cat.list_items(status="review", limit=10)
    assert item and item[0].get("username") == "LockedDir"
    _backdate(cat, "LockedDir", 100)
    n = cat.mark_stale(older_than_hours=72, stale_rank_grace=80)
    assert n == 1
    stale = cat.list_items(status="stale", limit=10)
    assert stale and stale[0].get("username") == "LockedDir"
