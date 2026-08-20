"""Integration tests for scripts/seed_linkdir_jobs.py against a mocked bridge."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from experiments.linkdir_finders import ai_queries
from experiments.linkdir_finders.ai_queries import QueryGenResult
from experiments.linkdir_finders.settings import load_config

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def seed_module():
    spec = importlib.util.spec_from_file_location(
        "seed_linkdir_jobs_under_test", ROOT / "scripts" / "seed_linkdir_jobs.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bridge(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Wire the real enqueue path to an in-memory bridge and record payloads."""
    import app.agent_memory as agent_memory
    import app.linkdir_bridge as linkdir_bridge

    monkeypatch.setenv("ADMIN_BOT_BRIDGE_URL", "https://bridge.test")
    monkeypatch.setenv("ADMIN_BOT_BRIDGE_TOKEN", "token")
    recorded: list[dict[str, Any]] = []

    def fake_request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        recorded.append({"method": method, "path": path, **kwargs})
        rows = (kwargs.get("payload") or {}).get("episodes") or []
        return {"ok": True, "id": len(recorded), "inserted": len(rows)}

    monkeypatch.setattr(linkdir_bridge, "bridge_request", fake_request)
    monkeypatch.setattr(agent_memory, "bridge_request", fake_request)
    return recorded


def _episodes(recorded: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        episode
        for row in recorded
        if row["path"].endswith("/agentmem/episodes")
        for episode in row["payload"]["episodes"]
    ]


def _run(module: Any, argv: list[str], monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(sys, "argv", ["seed_linkdir_jobs.py", *argv])
    return module.main()


def _summary(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    return json.loads(lines[-1])


def _enqueued(recorded: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row["payload"]["payload"]
        for row in recorded
        if row["path"].endswith("/jobs/enqueue")
    ]


def test_no_ai_flag_overrides_enabled_config(
    seed_module: Any,
    bridge: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def explode(*_args: Any, **_kwargs: Any) -> QueryGenResult:
        raise AssertionError("--no-ai must suppress generation")

    monkeypatch.setattr(ai_queries, "generate_queries", explode)

    code = _run(seed_module, ["--query-set", "fa", "--no-ai"], monkeypatch)
    summary = _summary(capsys)
    jobs = _enqueued(bridge)
    expected = load_config()["queries_fa"]

    assert code == 0
    assert "ai" not in summary
    assert summary["enqueued"] == len(expected)
    assert [job["query"] for job in jobs] == expected
    assert {job["source"] for job in jobs} == {"seed_script"}


def test_disabled_config_without_flag_skips_ai(
    seed_module: Any,
    bridge: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def explode(*_args: Any, **_kwargs: Any) -> QueryGenResult:
        raise AssertionError("AI must stay off when config disables it")

    monkeypatch.setattr(ai_queries, "generate_queries", explode)

    cfg = load_config()
    cfg["ai_queries"] = {**(cfg.get("ai_queries") or {}), "enabled": False}
    monkeypatch.setattr(seed_module, "load_config", lambda: cfg)

    code = _run(seed_module, ["--query-set", "fa"], monkeypatch)
    summary = _summary(capsys)

    assert code == 0
    assert "ai" not in summary
    assert summary["enqueued"] == len(cfg["queries_fa"])


def test_ai_flag_enqueues_generated_queries_with_traceable_source(
    seed_module: Any,
    bridge: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_generate(**kwargs: Any) -> QueryGenResult:
        calls.append(kwargs)
        return QueryGenResult(
            ok=True,
            queries=["لینکدونی یزد", "لینکدونی کرمان"],
            used_ai=True,
            reason="ok",
            diagnostics={"model": "@cf/openai/gpt-oss-120b", "neurons": 12.5},
        )

    monkeypatch.setattr(ai_queries, "generate_queries", fake_generate)

    code = _run(seed_module, ["--query-set", "fa", "--ai", "--ai-count", "2"], monkeypatch)
    summary = _summary(capsys)
    jobs = _enqueued(bridge)

    assert code == 0
    assert calls[0]["count"] == 2
    assert calls[0]["query_set"] == "fa"
    assert calls[0]["static_queries"] == load_config()["queries_fa"]

    ai_jobs = [job for job in jobs if job["source"] == "ai_agent"]
    assert [job["query"] for job in ai_jobs] == ["لینکدونی یزد", "لینکدونی کرمان"]
    assert summary["ai"]["used"] is True
    assert summary["ai"]["shards"][0]["accepted"] == 2
    assert summary["enqueued"] == len(load_config()["queries_fa"]) + 2


def test_generated_queries_are_recorded_as_episodes(
    seed_module: Any,
    bridge: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from experiments.linkdir_finders.job_queue import query_key

    monkeypatch.setattr(
        ai_queries,
        "generate_queries",
        lambda **_kwargs: QueryGenResult(
            ok=True,
            queries=["لینکدونی یزد", "لینکدونی کرمان"],
            used_ai=True,
            reason="ok",
            diagnostics={"model": "@cf/openai/gpt-oss-120b"},
        ),
    )

    code = _run(seed_module, ["--query-set", "fa", "--ai"], monkeypatch)
    summary = _summary(capsys)
    episodes = _episodes(bridge)

    assert code == 0
    assert [row["subject"] for row in episodes] == ["لینکدونی یزد", "لینکدونی کرمان"]
    assert episodes[0]["subject_key"] == query_key("لینکدونی یزد")
    assert {row["source"] for row in episodes} == {"ai_agent"}
    assert {row["query_set"] for row in episodes} == {"fa"}
    assert episodes[0]["meta"]["model"] == "@cf/openai/gpt-oss-120b"
    assert summary["ai"]["shards"][0]["episodes"] == 2


def test_episode_write_failure_does_not_change_the_outcome(
    seed_module: Any,
    bridge: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import app.agent_memory as agent_memory

    monkeypatch.setattr(
        ai_queries,
        "generate_queries",
        lambda **_kwargs: QueryGenResult(
            ok=True, queries=["لینکدونی یزد"], used_ai=True, reason="ok"
        ),
    )
    monkeypatch.setattr(
        agent_memory.AgentMemory,
        "record_episodes",
        lambda self, rows: (_ for _ in ()).throw(RuntimeError("d1 unreachable")),
    )

    code = _run(seed_module, ["--query-set", "fa", "--ai"], monkeypatch)
    summary = _summary(capsys)

    assert code == 0
    assert summary["ai"]["shards"][0]["episodes"] == 0
    assert summary["enqueued"] == len(load_config()["queries_fa"]) + 1


def test_dry_run_records_no_episodes(
    seed_module: Any,
    bridge: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        ai_queries,
        "generate_queries",
        lambda **_kwargs: QueryGenResult(
            ok=True, queries=["لینکدونی البرز"], used_ai=True, reason="ok"
        ),
    )

    code = _run(seed_module, ["--query-set", "fa", "--ai", "--dry-run"], monkeypatch)
    capsys.readouterr()

    assert code == 0
    assert _episodes(bridge) == []


def test_ai_failure_keeps_static_queries_and_exit_code(
    seed_module: Any,
    bridge: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        ai_queries,
        "generate_queries",
        lambda **_kwargs: QueryGenResult(ok=False, reason="quota_exhausted"),
    )

    code = _run(seed_module, ["--query-set", "fa", "--ai"], monkeypatch)
    summary = _summary(capsys)
    jobs = _enqueued(bridge)

    assert code == 0
    assert {job["source"] for job in jobs} == {"seed_script"}
    assert summary["enqueued"] == len(load_config()["queries_fa"])
    assert summary["ai"]["used"] is False
    assert summary["ai"]["shards"][0]["reason"] == "quota_exhausted"


def test_ai_crash_is_contained(
    seed_module: Any,
    bridge: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def boom(**_kwargs: Any) -> QueryGenResult:
        raise RuntimeError("cloudflare unreachable")

    monkeypatch.setattr(ai_queries, "generate_queries", boom)

    code = _run(seed_module, ["--query-set", "fa", "--ai"], monkeypatch)
    summary = _summary(capsys)

    assert code == 0
    assert summary["enqueued"] == len(load_config()["queries_fa"])
    assert summary["ai"]["shards"][0]["reason"] == "exception"


def test_dry_run_with_ai_prints_without_enqueueing(
    seed_module: Any,
    bridge: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        ai_queries,
        "generate_queries",
        lambda **_kwargs: QueryGenResult(
            ok=True, queries=["لینکدونی البرز"], used_ai=True, reason="ok"
        ),
    )

    code = _run(seed_module, ["--query-set", "en", "--ai", "--dry-run"], monkeypatch)
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    printed = [json.loads(line) for line in lines]

    assert code == 0
    assert bridge == []
    assert {"query": "لینکدونی البرز", "query_set": "en", "source": "ai_agent"} in printed
    assert printed[-1]["dry_run"] is True
