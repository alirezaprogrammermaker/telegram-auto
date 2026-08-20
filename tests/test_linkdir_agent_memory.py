"""Tests for the agent-memory client, the reward formula and the scoring pass."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app import agent_memory
from app.agent_memory import AgentMemory, subject_key
from experiments.linkdir_finders.job_queue import query_key
from experiments.linkdir_finders.reward import (
    QueryOutcome,
    compute_reward,
    group_catalog_rows,
    row_queries,
)

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# reward formula
# --------------------------------------------------------------------------


def test_zero_results_scores_zero() -> None:
    assert compute_reward(keep=0, review=0, junk=0) == 0.0


def test_all_junk_scores_zero() -> None:
    assert compute_reward(keep=0, review=0, junk=25) == 0.0
    assert compute_reward(keep=0, review=0, junk=1) == 0.0


def test_all_keep_with_enough_volume_scores_one() -> None:
    assert compute_reward(keep=12, review=0, junk=0) == 1.0
    assert compute_reward(keep=40, review=0, junk=0) == 1.0


def test_small_clean_query_still_scores_well() -> None:
    small = compute_reward(keep=3, review=0, junk=0)
    assert 0.6 < small < 1.0


def test_volume_saturates_so_one_query_cannot_dominate() -> None:
    at_saturation = compute_reward(keep=12, review=0, junk=0)
    far_beyond = compute_reward(keep=400, review=0, junk=0)
    assert far_beyond == at_saturation

    noisy_giant = compute_reward(keep=40, review=0, junk=160)
    clean_small = compute_reward(keep=6, review=0, junk=0)
    assert noisy_giant < clean_small


def test_reviews_earn_partial_credit() -> None:
    keeps = compute_reward(keep=10, review=0, junk=0)
    reviews = compute_reward(keep=0, review=10, junk=0)
    junk = compute_reward(keep=0, review=0, junk=10)
    assert junk < reviews < keeps


def test_junk_ratio_is_penalised_monotonically() -> None:
    rewards = [compute_reward(keep=10, review=0, junk=j) for j in (0, 5, 20, 100)]
    assert rewards == sorted(rewards, reverse=True)
    assert len(set(rewards)) == len(rewards)


def test_rank_strength_is_a_bounded_nudge() -> None:
    neutral = compute_reward(keep=4, review=0, junk=2)
    strong = compute_reward(keep=4, review=0, junk=2, rank_scores=[95.0, 90.0])
    weak = compute_reward(keep=4, review=0, junk=2, rank_scores=[5.0, 10.0])
    assert weak < neutral < strong
    assert abs(strong - neutral) <= 0.05 + 1e-9
    assert abs(neutral - weak) <= 0.05 + 1e-9


def test_reward_always_within_unit_interval() -> None:
    for keep, review, junk in [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 500), (500, 1, 1)]:
        value = compute_reward(keep=keep, review=review, junk=junk, rank_scores=[100.0])
        assert 0.0 <= value <= 1.0


def test_negative_counts_are_clamped() -> None:
    assert compute_reward(keep=-5, review=-1, junk=-2) == 0.0


# --------------------------------------------------------------------------
# catalog grouping
# --------------------------------------------------------------------------


def test_row_queries_reads_both_shapes() -> None:
    assert row_queries({"query": " لینکدونی "}) == ["لینکدونی"]
    assert row_queries({"queries": ["a", " b "]}) == ["a", "b"]
    assert row_queries({"queries": json.dumps(["a"])}) == ["a"]
    assert row_queries({"queries": "not json"}) == []


def test_group_catalog_rows_credits_every_originating_query() -> None:
    rows = [
        {"verdict": "keep", "queries": ["لینکدونی مشهد", "تبادل لینک"], "rank_score": 80},
        {"verdict": "junk", "query": "تبادل لینک", "rank_score": 10},
        {"verdict": "review", "query": "لینکدونی مشهد"},
    ]
    grouped = group_catalog_rows(rows)

    assert set(grouped) == {"لینکدونی مشهد", "تبادل لینک"}
    mashhad = grouped["لینکدونی مشهد"]
    assert (mashhad.keep_count, mashhad.review_count, mashhad.junk_count) == (1, 1, 0)
    exchange = grouped["تبادل لینک"]
    assert (exchange.keep_count, exchange.junk_count) == (1, 1)
    # Junk rows never contribute their rank score to the strength term.
    assert exchange.rank_scores == [80.0]


def test_group_catalog_rows_ignores_junk_shaped_input() -> None:
    assert group_catalog_rows([None, "x", {}, {"verdict": "keep"}]) == {}


def test_outcome_payload_matches_score_contract() -> None:
    outcome = QueryOutcome(query="q", keep_count=2, review_count=1, junk_count=1)
    payload = outcome.as_outcome("abc123")
    assert payload == {
        "subject_key": "abc123",
        "results_total": 4,
        "keep_count": 2,
        "review_count": 1,
        "junk_count": 1,
        "reward": outcome.reward(),
    }


def test_subject_key_matches_the_job_queue_key() -> None:
    for query in ("لینکدونی مشهد", " link exchange ", "تبادل لینک"):
        assert subject_key(query) == query_key(query)


# --------------------------------------------------------------------------
# memory client
# --------------------------------------------------------------------------


@pytest.fixture
def bridge(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    recorded: list[dict[str, Any]] = []

    def fake_request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        recorded.append({"method": method, "path": path, **kwargs})
        return {"ok": True}

    monkeypatch.setattr(agent_memory, "bridge_configured", lambda: True)
    monkeypatch.setattr(agent_memory, "bridge_request", fake_request)
    return recorded


def test_every_method_degrades_when_bridge_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_memory, "bridge_configured", lambda: False)
    monkeypatch.setattr(
        agent_memory,
        "bridge_request",
        lambda *a, **k: pytest.fail("must not touch the network"),
    )
    memory = AgentMemory("linkdir_query")

    assert memory.available() is False
    assert memory.record_episodes([{"subject": "q"}]) == {"inserted": 0, "skipped": 0}
    assert memory.score_episodes([{"subject_key": "k"}]) == 0
    assert memory.episodes() == []
    assert memory.add_lessons([{"kind": "do", "lesson": "x"}]) == {
        "created": 0,
        "reinforced": 0,
    }
    assert memory.lessons() == []
    assert memory.mark_consolidated([1, 2]) == 0
    assert memory.stats() == {}


@pytest.mark.parametrize(
    "outcome",
    [None, {"ok": False, "error": "boom"}, "not a dict", OSError("connection reset")],
)
def test_every_method_degrades_when_bridge_fails(
    monkeypatch: pytest.MonkeyPatch, outcome: Any
) -> None:
    def fake_request(*_a: Any, **_k: Any) -> Any:
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(agent_memory, "bridge_configured", lambda: True)
    monkeypatch.setattr(agent_memory, "bridge_request", fake_request)
    memory = AgentMemory("linkdir_query")

    assert memory.record_episodes([{"subject": "q"}]) == {"inserted": 0, "skipped": 0}
    assert memory.score_episodes([{"subject_key": "k"}]) == 0
    assert memory.episodes(order="best") == []
    assert memory.add_lessons([{"kind": "do", "lesson": "x"}])["created"] == 0
    assert memory.lessons() == []
    assert memory.mark_consolidated([3]) == 0
    assert memory.stats() == {}


def test_record_episodes_fills_missing_keys_and_drops_empty(
    bridge: list[dict[str, Any]],
) -> None:
    memory = AgentMemory("linkdir_query")
    memory.record_episodes(
        [
            {"subject": "لینکدونی یزد", "query_set": "fa", "source": "ai_agent"},
            {"subject": "  ", "query_set": "fa"},
            "junk",
            {"subject": "x", "subject_key": "given", "meta": {"model": "m"}},
        ]
    )

    payload = bridge[0]["payload"]
    assert payload["agent"] == "linkdir_query"
    assert len(payload["episodes"]) == 2
    assert payload["episodes"][0]["subject_key"] == query_key("لینکدونی یزد")
    assert payload["episodes"][1]["subject_key"] == "given"
    assert payload["episodes"][1]["meta"] == {"model": "m"}


def test_record_episodes_chunks_large_batches(bridge: list[dict[str, Any]]) -> None:
    memory = AgentMemory("linkdir_query")
    memory.record_episodes([{"subject": f"q{i}"} for i in range(120)])

    sizes = [len(row["payload"]["episodes"]) for row in bridge]
    assert sizes == [agent_memory.BATCH_SIZE, agent_memory.BATCH_SIZE, 20]


def test_score_episodes_coerces_counts(bridge: list[dict[str, Any]]) -> None:
    memory = AgentMemory("linkdir_query")
    memory.score_episodes(
        [
            {"subject_key": "k1", "keep_count": "3", "reward": "0.5"},
            {"keep_count": 1},
        ]
    )

    outcomes = bridge[0]["payload"]["outcomes"]
    assert len(outcomes) == 1
    assert outcomes[0] == {
        "subject_key": "k1",
        "results_total": 0,
        "keep_count": 3,
        "review_count": 0,
        "junk_count": 0,
        "reward": 0.5,
    }


def test_episode_query_encodes_filters(bridge: list[dict[str, Any]]) -> None:
    memory = AgentMemory("linkdir_query")
    memory.episodes(scored=True, order="best", limit=5, consolidated=False)

    assert bridge[0]["query"] == {
        "agent": "linkdir_query",
        "limit": 5,
        "scored": 1,
        "consolidated": 0,
        "order": "best",
    }


def test_unknown_order_is_dropped_rather_than_sent(bridge: list[dict[str, Any]]) -> None:
    AgentMemory("linkdir_query").episodes(order="sideways")
    assert "order" not in bridge[0]["query"]


def test_add_lessons_rejects_bad_kinds_and_clamps_confidence(
    bridge: list[dict[str, Any]],
) -> None:
    memory = AgentMemory("linkdir_query")
    memory.add_lessons(
        [
            {"kind": "maybe", "lesson": "x"},
            {"kind": "avoid", "lesson": "y", "confidence": 9.5, "evidence": [1, "2"]},
        ]
    )

    lessons = bridge[0]["payload"]["lessons"]
    assert len(lessons) == 1
    assert lessons[0]["confidence"] == 1.0
    assert lessons[0]["evidence"] == [1, 2]
    assert lessons[0]["lesson_key"]


def test_mark_consolidated_dedupes_and_sorts(bridge: list[dict[str, Any]]) -> None:
    AgentMemory("linkdir_query").mark_consolidated([5, 3, 5, "7", None, "x"])
    assert bridge[0]["payload"]["episode_ids"] == [3, 5, 7]


def test_mark_consolidated_skips_the_call_when_empty(
    bridge: list[dict[str, Any]],
) -> None:
    assert AgentMemory("linkdir_query").mark_consolidated([]) == 0
    assert bridge == []


# --------------------------------------------------------------------------
# scoring script
# --------------------------------------------------------------------------


class FakeCatalog:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def list_items(
        self, *, verdict: str | None = None, limit: int = 100, **_: Any
    ) -> list[dict[str, Any]]:
        rows = [r for r in self.rows if verdict is None or r.get("verdict") == verdict]
        return rows[:limit]


class FakeMemory:
    def __init__(self, episodes: list[dict[str, Any]], *, available: bool = True) -> None:
        self._episodes = episodes
        self._available = available
        self.scored: list[dict[str, Any]] = []

    def available(self) -> bool:
        return self._available

    def episodes(self, **_: Any) -> list[dict[str, Any]]:
        return list(self._episodes)

    def score_episodes(self, outcomes: list[dict[str, Any]]) -> int:
        self.scored.extend(outcomes)
        return len(outcomes)


@pytest.fixture
def score_module():
    spec = importlib.util.spec_from_file_location(
        "score_agent_memory_under_test", ROOT / "scripts" / "score_agent_memory.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(module: Any, argv: list[str], monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(sys, "argv", ["score_agent_memory.py", *argv])
    return module.main()


def _summary(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    return json.loads(lines[-1])


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _install_catalog(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]]) -> None:
    import experiments.linkdir_finders.catalog as catalog_mod

    monkeypatch.setattr(catalog_mod, "LinkDirCatalog", lambda *a, **k: FakeCatalog(rows))


def test_score_script_exits_zero_when_bridge_is_down(
    score_module: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        score_module, "AgentMemory", lambda agent: FakeMemory([], available=False)
    )
    code = _run(score_module, [], monkeypatch)
    summary = _summary(capsys)

    assert code == 0
    assert summary["ok"] is False
    assert summary["reason"] == "bridge_unavailable"


def test_score_script_exits_zero_with_nothing_to_score(
    score_module: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(score_module, "AgentMemory", lambda agent: FakeMemory([]))
    code = _run(score_module, [], monkeypatch)
    summary = _summary(capsys)

    assert code == 0
    assert summary["reason"] == "nothing_to_score"
    assert summary["scored"] == 0


def test_score_script_posts_rewards_for_matched_episodes(
    score_module: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    good = "لینکدونی مشهد"
    bad = "لینک رایگان"
    memory = FakeMemory(
        [
            {"id": 1, "subject": good, "subject_key": query_key(good), "created_at": _iso(50)},
            {"id": 2, "subject": bad, "subject_key": query_key(bad), "created_at": _iso(50)},
        ]
    )
    monkeypatch.setattr(score_module, "AgentMemory", lambda agent: memory)
    _install_catalog(
        monkeypatch,
        [{"verdict": "keep", "query": good, "rank_score": 82}] * 6
        + [{"verdict": "junk", "query": bad, "rank_score": 5}] * 4,
    )

    code = _run(score_module, [], monkeypatch)
    summary = _summary(capsys)
    by_key = {row["subject_key"]: row for row in memory.scored}

    assert code == 0
    assert summary["scored"] == 2
    assert summary["matched"] == 2
    assert by_key[query_key(good)]["keep_count"] == 6
    assert by_key[query_key(bad)]["reward"] == 0.0
    assert by_key[query_key(good)]["reward"] > by_key[query_key(bad)]["reward"]


def test_score_script_holds_back_episodes_still_in_flight(
    score_module: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    memory = FakeMemory(
        [
            {"id": 1, "subject": "تازه", "subject_key": query_key("تازه"), "created_at": _iso(2)},
            {"id": 2, "subject": "کهنه", "subject_key": query_key("کهنه"), "created_at": _iso(72)},
        ]
    )
    monkeypatch.setattr(score_module, "AgentMemory", lambda agent: memory)
    _install_catalog(monkeypatch, [])

    code = _run(score_module, [], monkeypatch)
    summary = _summary(capsys)

    assert code == 0
    assert summary["held"] == 1
    assert summary["empty"] == 1
    assert [row["subject_key"] for row in memory.scored] == [query_key("کهنه")]


def test_score_script_dry_run_writes_nothing(
    score_module: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    query = "تبادل لینک"
    memory = FakeMemory(
        [{"id": 1, "subject": query, "subject_key": query_key(query), "created_at": _iso(50)}]
    )
    monkeypatch.setattr(score_module, "AgentMemory", lambda agent: memory)
    _install_catalog(monkeypatch, [{"verdict": "keep", "query": query}])

    code = _run(score_module, ["--dry-run"], monkeypatch)
    summary = _summary(capsys)

    assert code == 0
    assert memory.scored == []
    assert summary["reason"] == "dry_run"
    assert summary["preview"][0]["subject_key"] == query_key(query)


def test_score_script_survives_a_broken_catalog(
    score_module: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    memory = FakeMemory([{"id": 1, "subject": "q", "subject_key": "k", "created_at": _iso(50)}])
    monkeypatch.setattr(score_module, "AgentMemory", lambda agent: memory)

    import experiments.linkdir_finders.catalog as catalog_mod

    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("pool directory missing")

    monkeypatch.setattr(catalog_mod, "LinkDirCatalog", boom)

    code = _run(score_module, [], monkeypatch)
    summary = _summary(capsys)

    assert code == 0
    assert summary["reason"] == "catalog_unavailable"
    assert memory.scored == []
