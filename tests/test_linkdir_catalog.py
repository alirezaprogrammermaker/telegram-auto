from experiments.linkdir_finders.catalog import should_persist_row
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


def test_query_shards_are_non_empty() -> None:
    cfg = load_config()
    fa = queries_for_set(cfg, "fa")
    en = queries_for_set(cfg, "en")
    niche = queries_for_set(cfg, "niche")
    assert fa and en and niche
    assert "لینکدونی" in fa
    assert "link exchange" in en
    assert not set(fa) & set(en)
