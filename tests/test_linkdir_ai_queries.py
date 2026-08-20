"""Tests for AI query generation, store hydration and graceful degradation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app.cloudflare_ai import hydrate
from app.cloudflare_ai.provider import ChatResult, CloudflareAIProvider
from app.cloudflare_ai.store import CloudflareAIStore
from experiments.linkdir_finders import ai_queries
from experiments.linkdir_finders.ai_queries import QueryGenResult, generate_queries

CFG: dict[str, Any] = {
    "queries_fa": ["تبادل لینک", "لینکدونی"],
    "ai_queries": {"enabled": True, "count": 5, "web_search": False, "max_tool_rounds": 2},
}


class FakeCatalog:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    def list_items(self, *, verdict: str | None = None, limit: int = 100, **_: Any) -> list[dict]:
        rows = [r for r in self.rows if verdict is None or r.get("verdict") == verdict]
        return rows[:limit]


class ScriptedProvider:
    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> ChatResult:
        self.calls.append({"messages": messages, **kwargs})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return ChatResult(
            content=item,
            model="@cf/openai/gpt-oss-120b",
            account_name="a1",
            neurons=2.0,
        )


def _catalog_rows() -> list[dict[str, Any]]:
    return [
        {"verdict": "keep", "title": "لینکدونی مشهد", "queries": ["لینکدونی مشهد"]},
        {"verdict": "keep", "title": "تبادل لینک آزاد", "query": "تبادل لینک"},
        {"verdict": "junk", "title": "spam", "query": "لینک رایگان"},
    ]


def test_generates_and_validates_queries() -> None:
    payload = json.dumps(
        {
            "queries": [
                "لینکدونی تبریز",
                "链接目录",
                "تبادل لینک",
                "گروه تبادل لینک شیراز",
                "لینکدونی 🔥",
                "لینک دونی کرج",
            ]
        },
        ensure_ascii=False,
    )
    provider = ScriptedProvider([payload])
    result = generate_queries(
        count=5,
        query_set="fa",
        cfg=CFG,
        provider=provider,
        catalog=FakeCatalog(_catalog_rows()),
        static_queries=["تبادل لینک", "لینکدونی"],
    )

    assert result.ok is True
    assert result.used_ai is True
    assert result.queries == ["لینکدونی تبریز", "گروه تبادل لینک شیراز", "لینک دونی کرج"]
    reasons = {row["reason"] for row in result.rejected}
    assert "duplicate" in reasons
    assert any(r.startswith("disallowed_chars") for r in reasons)
    assert result.diagnostics["candidates"] == 6


def test_tools_are_offered_and_kept_small() -> None:
    rows = [
        {"verdict": "keep", "query": f"کوئری {i}", "title": f"t{i}"} for i in range(30)
    ]
    provider = ScriptedProvider(
        [
            json.dumps({"name": "get_top_queries", "arguments": {}}),
            json.dumps({"queries": ["لینکدونی رشت"]}, ensure_ascii=False),
            json.dumps({"queries": ["لینکدونی رشت"]}, ensure_ascii=False),
        ]
    )
    result = generate_queries(
        count=3,
        query_set="fa",
        cfg=CFG,
        provider=provider,
        catalog=FakeCatalog(rows),
        static_queries=[],
    )

    assert result.ok is True
    tool_names = {t["function"]["name"] for t in provider.calls[0]["tools"]}
    assert tool_names == {"get_top_queries", "get_weak_queries", "get_existing_queries"}
    tool_output = json.loads(
        [m for m in provider.calls[1]["messages"] if m.get("role") == "tool"][0]["content"]
    )
    assert len(tool_output) == ai_queries.TOOL_ITEM_CAP


def test_web_search_tool_only_when_enabled() -> None:
    provider = ScriptedProvider([json.dumps({"queries": ["لینکدونی قم"]}, ensure_ascii=False)])
    result = generate_queries(
        count=2,
        query_set="fa",
        cfg=CFG,
        provider=provider,
        catalog=FakeCatalog(),
        static_queries=[],
        enable_web_search=True,
    )

    assert result.ok is True
    assert result.diagnostics["web_search_backend"] == "duckduckgo_lite"


def test_quota_exhaustion_falls_back_without_raising(tmp_path: Path) -> None:
    store = CloudflareAIStore(path=tmp_path / "cloudflare_ai.json")
    store.add_account(name="a1", account_id="1" * 32, api_token="t1")
    provider = CloudflareAIProvider(store)
    body = {"errors": [{"message": "Daily neuron limit reached"}]}

    with patch.object(provider, "_post_json", return_value=(400, body, json.dumps(body))):
        result = generate_queries(
            count=5,
            query_set="fa",
            cfg=CFG,
            provider=provider,
            catalog=FakeCatalog(_catalog_rows()),
            static_queries=["تبادل لینک"],
        )

    assert result.ok is False
    assert result.used_ai is False
    assert result.queries == []
    assert result.reason == "quota_exhausted"
    assert result.summary()["used"] is False


def test_model_returning_only_garbage_is_rejected() -> None:
    provider = ScriptedProvider([json.dumps({"queries": ["链接目录", "обмен ссылками"]})])
    result = generate_queries(
        count=5,
        query_set="fa",
        cfg=CFG,
        provider=provider,
        catalog=FakeCatalog(),
        static_queries=[],
    )

    assert result.ok is False
    assert result.reason == "all_rejected"
    assert len(result.rejected) == 2


def test_broken_catalog_does_not_break_generation() -> None:
    class BrokenCatalog:
        def list_items(self, **_: Any) -> list[dict[str, Any]]:
            raise RuntimeError("bridge down")

    provider = ScriptedProvider([json.dumps({"queries": ["لینکدونی اهواز"]}, ensure_ascii=False)])
    result = generate_queries(
        count=3,
        query_set="fa",
        cfg=CFG,
        provider=provider,
        catalog=BrokenCatalog(),
        static_queries=["لینکدونی"],
    )

    assert result.ok is True
    assert result.queries == ["لینکدونی اهواز"]


def test_no_accounts_reports_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = CloudflareAIStore(path=tmp_path / "cloudflare_ai.json")
    monkeypatch.setattr(hydrate, "ensure_store", lambda store=None: empty)

    result = generate_queries(count=5, query_set="fa", cfg=CFG, catalog=FakeCatalog())

    assert result.ok is False
    assert result.reason == "no_accounts"


def test_result_summary_is_json_serializable() -> None:
    result = QueryGenResult(ok=False, reason="quota_exhausted", diagnostics={"rounds": 1})
    assert json.loads(json.dumps(result.summary()))["reason"] == "quota_exhausted"


def test_hydrate_imports_accounts_from_bridge(tmp_path: Path) -> None:
    store = CloudflareAIStore(path=tmp_path / "cloudflare_ai.json")
    payload = {
        "ok": True,
        "store": {
            "config": {"default_model": "@cf/openai/gpt-oss-20b"},
            "accounts": [
                {"name": "gha1", "account_id": "a" * 32, "api_token": "tok1"},
                {"name": "bad", "account_id": "nope", "api_token": "tok2"},
                {"name": "gha2", "account_id": "b" * 32, "api_token": "tok3"},
            ],
        },
    }
    with patch("app.bridge_client.bridge_configured", return_value=True), patch(
        "app.bridge_client.bridge_request", return_value=payload
    ):
        added = hydrate.hydrate_from_bridge(store)

    assert added == 2
    assert {row["name"] for row in store.list_accounts()} == {"gha1", "gha2"}
    assert store.default_model() == "@cf/openai/gpt-oss-20b"


def test_hydrate_accepts_flat_payload(tmp_path: Path) -> None:
    store = CloudflareAIStore(path=tmp_path / "cloudflare_ai.json")
    payload = {"ok": True, "accounts": [{"name": "flat", "account_id": "c" * 32, "api_token": "t"}]}
    with patch("app.bridge_client.bridge_configured", return_value=True), patch(
        "app.bridge_client.bridge_request", return_value=payload
    ):
        assert hydrate.hydrate_from_bridge(store) == 1


def test_hydrate_is_silent_when_bridge_unavailable(tmp_path: Path) -> None:
    store = CloudflareAIStore(path=tmp_path / "cloudflare_ai.json")
    with patch("app.bridge_client.bridge_configured", return_value=False):
        assert hydrate.hydrate_from_bridge(store) == 0

    with patch("app.bridge_client.bridge_configured", return_value=True), patch(
        "app.bridge_client.bridge_request", side_effect=OSError("connection refused")
    ):
        assert hydrate.hydrate_from_bridge(store) == 0
    assert store.list_accounts() == []


def test_ensure_store_skips_bridge_when_accounts_exist(tmp_path: Path) -> None:
    store = CloudflareAIStore(path=tmp_path / "cloudflare_ai.json")
    store.add_account(name="local", account_id="d" * 32, api_token="t")
    with patch("app.bridge_client.bridge_request", side_effect=AssertionError("must not call")):
        assert hydrate.ensure_store(store) is store
