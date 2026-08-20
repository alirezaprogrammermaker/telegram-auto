"""Tests for the optional web search tool used by the query agent."""

from __future__ import annotations

import json
import urllib.error
from typing import Any

import pytest

from experiments.linkdir_finders import web_search as ws

_LITE_HTML = """
<table>
  <tr><td><a rel="nofollow" href="https://t.me/x" class='result-link'>لینکدونی &amp; گپ</a></td></tr>
  <tr><td class='result-snippet'>بزرگترین <b>لینکدونی</b> تلگرام</td></tr>
  <tr><td><a href="https://t.me/y" class='result-link'>Link Exchange</a></td></tr>
  <tr><td class='result-snippet'>share your group</td></tr>
</table>
"""

_HTML_ENDPOINT = """
<div><a class="result__a" href="#">Second Layout</a>
<a class="result__snippet">snippet text</a></div>
"""


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    ws.reset_rate_limit()
    monkeypatch.setattr(ws, "MIN_INTERVAL_SECONDS", 0.0)
    for name in ("BRAVE_SEARCH_API_KEY", "SEARCH_API_KEY", "SERPER_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_parses_duckduckgo_lite_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws, "_http", lambda *_a, **_k: _LITE_HTML)
    results = ws.web_search("لینکدونی")

    assert results == [
        {"title": "لینکدونی & گپ", "snippet": "بزرگترین لینکدونی تلگرام"},
        {"title": "Link Exchange", "snippet": "share your group"},
    ]


def test_parses_alternate_duckduckgo_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws, "_http", lambda *_a, **_k: _HTML_ENDPOINT)
    assert ws.web_search("x") == [{"title": "Second Layout", "snippet": "snippet text"}]


def test_network_failure_returns_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> str:
        raise urllib.error.URLError("dns failure")

    monkeypatch.setattr(ws, "_http", boom)
    assert ws.web_search("لینکدونی") == []


def test_unexpected_error_returns_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> str:
        raise RuntimeError("something odd")

    monkeypatch.setattr(ws, "_http", boom)
    assert ws.web_search("x") == []


def test_garbage_html_returns_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws, "_http", lambda *_a, **_k: "<html>nope</html>")
    assert ws.web_search("x") == []


def test_empty_query_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws, "_http", lambda *_a, **_k: pytest.fail("must not fetch"))
    assert ws.web_search("   ") == []


def test_brave_backend_used_when_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_http(url: str, *, headers: dict[str, str] | None = None, **_k: Any) -> str:
        seen["url"] = url
        seen["headers"] = headers or {}
        return json.dumps(
            {"web": {"results": [{"title": "T", "description": "<b>D</b>"}]}}
        )

    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "secret")
    monkeypatch.setattr(ws, "_http", fake_http)

    assert ws.backend_name() == "brave"
    assert ws.web_search("لینکدونی") == [{"title": "T", "snippet": "D"}]
    assert seen["headers"]["X-Subscription-Token"] == "secret"
    assert "api.search.brave.com" in seen["url"]


def test_serper_backend_used_when_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERPER_API_KEY", "secret")
    monkeypatch.setattr(
        ws, "_http", lambda *_a, **_k: json.dumps({"organic": [{"title": "S", "snippet": "n"}]})
    )

    assert ws.backend_name() == "serper"
    assert ws.web_search("x") == [{"title": "S", "snippet": "n"}]


def test_results_are_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = "".join(
        f"<a class='result-link'>t{i}</a><td class='result-snippet'>s{i}</td>" for i in range(20)
    )
    monkeypatch.setattr(ws, "_http", lambda *_a, **_k: rows)
    assert len(ws.web_search("x", limit=99)) == ws.MAX_RESULTS


def test_per_process_call_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws, "_http", lambda *_a, **_k: _LITE_HTML)
    for _ in range(ws.MAX_CALLS_PER_PROCESS):
        assert ws.web_search("x")
    assert ws.web_search("x") == []


def test_default_backend_is_keyless() -> None:
    assert ws.backend_name() == "duckduckgo_lite"
