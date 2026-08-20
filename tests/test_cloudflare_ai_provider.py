"""Tests for Cloudflare AI provider rotation logic."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.cloudflare_ai.provider import CloudflareAIProvider
from app.cloudflare_ai.store import CloudflareAIStore


@pytest.fixture
def store(tmp_path: Path) -> CloudflareAIStore:
    path = tmp_path / "cloudflare_ai.json"
    store = CloudflareAIStore(path=path)
    store.add_account(name="a1", account_id="1" * 32, api_token="token_a")
    store.add_account(name="a2", account_id="2" * 32, api_token="token_b")
    return store


def _ok_response(content: str = "OK", neurons: float = 1.0) -> tuple[int, dict, str]:
    body = {
        "choices": [{"message": {"content": content}}],
        "usage": {"neurons": neurons, "prompt_tokens": 5, "completion_tokens": 2},
    }
    return 200, body, json.dumps(body)


def _quota_response() -> tuple[int, dict, str]:
    body = {"errors": [{"message": "Daily neuron limit reached"}]}
    return 400, body, json.dumps(body)


def test_chat_success(store: CloudflareAIStore) -> None:
    provider = CloudflareAIProvider(store)
    with patch.object(provider, "_post_json", return_value=_ok_response("Hello")):
        result = provider.chat([{"role": "user", "content": "hi"}])
    assert result.content == "Hello"
    assert result.account_name == "a1"


def test_chat_rotates_on_quota(store: CloudflareAIStore) -> None:
    provider = CloudflareAIProvider(store)
    side_effect = [_quota_response(), _ok_response("from second")]
    with patch.object(provider, "_post_json", side_effect=side_effect):
        result = provider.chat([{"role": "user", "content": "hi"}])
    assert result.account_name == "a2"
    assert result.content == "from second"
    assert store.get_account("a1")["quota_exhausted_at"]


def test_all_accounts_exhausted(store: CloudflareAIStore) -> None:
    provider = CloudflareAIProvider(store)
    with patch.object(provider, "_post_json", return_value=_quota_response()):
        with pytest.raises(RuntimeError, match="All Cloudflare AI accounts"):
            provider.chat([{"role": "user", "content": "hi"}])


def _transport_error() -> tuple[int, None, str]:
    return 0, None, "<urlopen error timed out>"


def test_chat_rotates_on_transport_error(store: CloudflareAIStore) -> None:
    provider = CloudflareAIProvider(store)
    side_effect = [_transport_error(), _ok_response("from second")]
    with patch.object(provider, "_post_json", side_effect=side_effect):
        result = provider.chat([{"role": "user", "content": "hi"}])
    assert result.account_name == "a2"
    assert result.content == "from second"
    # A network blip must not burn the account's daily quota.
    assert not store.get_account("a1")["quota_exhausted_at"]


def test_transport_errors_everywhere_are_not_reported_as_quota(
    store: CloudflareAIStore,
) -> None:
    provider = CloudflareAIProvider(store)
    with patch.object(provider, "_post_json", return_value=_transport_error()):
        with pytest.raises(RuntimeError, match="failed to respond") as excinfo:
            provider.chat([{"role": "user", "content": "hi"}])
    assert "daily limit" not in str(excinfo.value)
    assert not store.get_account("a1")["quota_exhausted_at"]


def test_test_account(store: CloudflareAIStore) -> None:
    provider = CloudflareAIProvider(store)
    with patch.object(provider, "_post_json", return_value=_ok_response("OK")):
        result = provider.test_account("a2")
    assert result.account_name == "a2"
    assert result.content == "OK"


def test_extract_content_from_reasoning_model(store: CloudflareAIStore) -> None:
    provider = CloudflareAIProvider(store)
    body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "Hello",
                }
            }
        ],
        "usage": {"neurons": 1.0, "prompt_tokens": 5, "completion_tokens": 2},
    }
    with patch.object(provider, "_post_json", return_value=(200, body, json.dumps(body))):
        result = provider.chat([{"role": "user", "content": "hi"}])
    assert result.content == "Hello"
