"""Tests for the reusable Cloudflare AI tool-calling agent runtime."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app.cloudflare_ai.agent import (
    REASON_BAD_JSON,
    REASON_NO_ACCOUNTS,
    REASON_QUOTA_EXHAUSTED,
    Agent,
    AgentTool,
    parse_json_object,
    salvage_tool_calls,
)
from app.cloudflare_ai.provider import (
    ChatResult,
    CloudflareAIProvider,
    JsonModeUnsupportedError,
)
from app.cloudflare_ai.store import CloudflareAIStore

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
    "required": ["queries"],
}


class FakeProvider:
    """Scripted provider: each entry is a ChatResult or an exception to raise."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> ChatResult:
        self.calls.append({"messages": list(messages), **kwargs})
        assert self.script, "provider called more times than scripted"
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _result(content: str = "", tool_calls: list[dict[str, Any]] | None = None) -> ChatResult:
    return ChatResult(
        content=content,
        model="@cf/openai/gpt-oss-120b",
        account_name="a1",
        neurons=1.0,
        tool_calls=tool_calls or [],
        finish_reason="stop",
    )


def _tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "call_1",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _counting_tool(calls: list[dict[str, Any]]) -> AgentTool:
    def handler(args: dict[str, Any]) -> Any:
        calls.append(args)
        return [{"query": "لینکدونی", "keeps": 4}]

    return AgentTool(
        name="get_top_queries",
        description="best queries",
        parameters={"type": "object", "properties": {}},
        handler=handler,
    )


def test_tool_round_then_json_answer() -> None:
    seen: list[dict[str, Any]] = []
    provider = FakeProvider(
        [
            _result(tool_calls=[_tool_call("get_top_queries", {"limit": 3})]),
            _result(content="ready"),
            _result(content='{"queries": ["لینکدونی مشهد"]}'),
        ]
    )
    agent = Agent(
        provider,
        system_prompt="sys",
        tools=[_counting_tool(seen)],
        response_schema=SCHEMA,
    )
    result = agent.run("go")

    assert result.ok
    assert result.data == {"queries": ["لینکدونی مشهد"]}
    assert seen == [{"limit": 3}]
    assert result.rounds == 1
    assert result.used_json_mode is True
    assert result.neurons == pytest.approx(3.0)
    assert provider.calls[-1]["response_format"]["type"] == "json_schema"
    assert provider.calls[-1]["response_format"]["json_schema"] == SCHEMA


def test_salvages_gpt_oss_tool_call_emitted_as_content() -> None:
    seen: list[dict[str, Any]] = []
    provider = FakeProvider(
        [
            _result(content='{"name": "get_top_queries", "arguments": {"limit": 5}}'),
            _result(content="done"),
            _result(content='{"queries": ["تبادل لینک"]}'),
        ]
    )
    agent = Agent(
        provider,
        system_prompt="sys",
        tools=[_counting_tool(seen)],
        response_schema=SCHEMA,
    )
    result = agent.run("go")

    assert result.ok
    assert seen == [{"limit": 5}]
    assert [inv.salvaged for inv in result.invocations] == [True]


def test_salvage_ignores_unoffered_tool_names() -> None:
    assert salvage_tool_calls('{"name": "drop_table", "arguments": {}}', {"get_top_queries"}) == []
    assert salvage_tool_calls("not json at all", {"get_top_queries"}) == []
    assert salvage_tool_calls('{"queries": ["x"]}', {"get_top_queries"}) == []


def test_salvage_accepts_openai_style_and_batches() -> None:
    calls = salvage_tool_calls(
        '[{"function": {"name": "a", "arguments": "{\\"k\\": 1}"}}, '
        '{"name": "b", "parameters": {"k": 2}}]',
        {"a", "b"},
    )
    assert calls == [
        {"name": "a", "arguments": {"k": 1}},
        {"name": "b", "arguments": {"k": 2}},
    ]


def test_unknown_tool_name_does_not_become_an_invocation() -> None:
    provider = FakeProvider(
        [
            _result(content='{"name": "drop_table", "arguments": {}}'),
            _result(content='{"queries": ["لینکدونی"]}'),
        ]
    )
    agent = Agent(
        provider,
        system_prompt="sys",
        tools=[_counting_tool([])],
        response_schema=SCHEMA,
    )
    result = agent.run("go")

    assert result.ok
    assert result.invocations == []
    assert result.rounds == 0


def test_falls_back_to_plain_prompt_when_json_mode_rejected() -> None:
    provider = FakeProvider(
        [
            JsonModeUnsupportedError("JSON Mode couldn't be met"),
            _result(content='```json\n{"queries": ["لینک رایگان"]}\n```'),
        ]
    )
    agent = Agent(provider, system_prompt="sys", response_schema=SCHEMA)
    result = agent.run("go")

    assert result.ok
    assert result.used_json_mode is False
    assert result.data == {"queries": ["لینک رایگان"]}
    assert "response_format" not in provider.calls[-1]


def test_tool_errors_are_fed_back_not_raised() -> None:
    def boom(_args: dict[str, Any]) -> Any:
        raise ValueError("tool exploded")

    provider = FakeProvider(
        [
            _result(tool_calls=[_tool_call("get_top_queries", {})]),
            _result(content='{"queries": ["لینکدونی"]}'),
        ]
    )
    agent = Agent(
        provider,
        system_prompt="sys",
        tools=[
            AgentTool(
                name="get_top_queries",
                description="d",
                parameters={"type": "object", "properties": {}},
                handler=boom,
            )
        ],
        max_tool_rounds=1,
        response_schema=SCHEMA,
    )
    result = agent.run("go")

    assert result.ok
    assert result.invocations[0].ok is False
    tool_messages = [m for m in provider.calls[-1]["messages"] if m.get("role") == "tool"]
    assert "tool exploded" in tool_messages[0]["content"]


def test_max_tool_rounds_is_bounded() -> None:
    script = [_result(tool_calls=[_tool_call("get_top_queries", {})]) for _ in range(2)]
    script.append(_result(content='{"queries": ["لینکدونی"]}'))
    provider = FakeProvider(script)
    agent = Agent(
        provider,
        system_prompt="sys",
        tools=[_counting_tool([])],
        max_tool_rounds=2,
        response_schema=SCHEMA,
    )
    result = agent.run("go")

    assert result.ok
    assert result.rounds == 2
    assert len(provider.calls) == 3


def test_invalid_json_final_answer_reports_bad_json() -> None:
    provider = FakeProvider([_result(content="here are some queries, enjoy")])
    agent = Agent(provider, system_prompt="sys", response_schema=SCHEMA)
    result = agent.run("go")

    assert result.ok is False
    assert result.reason == REASON_BAD_JSON


def test_plain_agent_without_schema_skips_extra_call() -> None:
    provider = FakeProvider([_result(content="hello")])
    agent = Agent(provider, system_prompt="sys", tools=[_counting_tool([])])
    result = agent.run("go")

    assert result.ok
    assert result.content == "hello"
    assert len(provider.calls) == 1


def test_quota_exhaustion_never_escapes_the_agent(tmp_path: Path) -> None:
    store = CloudflareAIStore(path=tmp_path / "cloudflare_ai.json")
    store.add_account(name="a1", account_id="1" * 32, api_token="t1")
    store.add_account(name="a2", account_id="2" * 32, api_token="t2")
    provider = CloudflareAIProvider(store)
    body = {"errors": [{"message": "Daily neuron limit reached"}]}

    agent = Agent(provider, system_prompt="sys", response_schema=SCHEMA)
    with patch.object(provider, "_post_json", return_value=(400, body, json.dumps(body))):
        result = agent.run("go")

    assert result.ok is False
    assert result.reason == REASON_QUOTA_EXHAUSTED
    assert result.data is None


def test_missing_accounts_reports_no_accounts(tmp_path: Path) -> None:
    store = CloudflareAIStore(path=tmp_path / "cloudflare_ai.json")
    agent = Agent(CloudflareAIProvider(store), system_prompt="sys")
    result = agent.run("go")

    assert result.ok is False
    assert result.reason == REASON_NO_ACCOUNTS


def test_diagnostics_shape() -> None:
    seen: list[dict[str, Any]] = []
    provider = FakeProvider(
        [
            _result(tool_calls=[_tool_call("get_top_queries", {})]),
            _result(content='{"queries": []}'),
        ]
    )
    agent = Agent(
        provider,
        system_prompt="sys",
        tools=[_counting_tool(seen)],
        max_tool_rounds=1,
        response_schema=SCHEMA,
    )
    diagnostics = agent.run("go").diagnostics()

    assert diagnostics["ok"] is True
    assert diagnostics["account"] == "a1"
    assert diagnostics["tools_called"] == [
        {"name": "get_top_queries", "ok": True, "salvaged": False}
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ("```\n[1, 2]\n```", [1, 2]),
        ('Sure! {"a": 1} hope that helps', {"a": 1}),
        ("no json here", None),
        ("", None),
    ],
)
def test_parse_json_object(text: str, expected: Any) -> None:
    assert parse_json_object(text) == expected
