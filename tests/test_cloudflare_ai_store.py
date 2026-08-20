"""Tests for Cloudflare AI account store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.cloudflare_ai.models import DEFAULT_MODEL, resolve_model_id
from app.cloudflare_ai.store import CloudflareAIStore, mask_token


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "cloudflare_ai.json"


@pytest.fixture
def store(store_path: Path) -> CloudflareAIStore:
    return CloudflareAIStore(path=store_path)


def test_default_store_created(store_path: Path) -> None:
    store = CloudflareAIStore(path=store_path)
    assert store.default_model() == DEFAULT_MODEL
    store.add_account(name="init", account_id="f" * 32, api_token="token")
    assert store_path.exists()
    data = json.loads(store_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1


def test_add_and_list_accounts(store: CloudflareAIStore) -> None:
    row = store.add_account(
        name="acct_a",
        account_id="a" * 32,
        api_token="cfut_testtoken1234567890",
        priority=1,
    )
    assert row["name"] == "acct_a"
    assert len(store.list_accounts()) == 1

    with pytest.raises(ValueError, match="already exists"):
        store.add_account(
            name="acct_a",
            account_id="b" * 32,
            api_token="other",
        )


def test_remove_and_disable(store: CloudflareAIStore) -> None:
    store.add_account(name="x", account_id="c" * 32, api_token="token1")
    assert store.remove_account("x") is True
    assert store.remove_account("x") is False

    store.add_account(name="y", account_id="d" * 32, api_token="token2")
    assert store.set_active("y", False) is True
    assert store.account_available(store.get_account("y") or {}) is False


def test_priority_order(store: CloudflareAIStore) -> None:
    store.add_account(name="low", account_id="1" * 32, api_token="t1", priority=5)
    store.add_account(name="high", account_id="2" * 32, api_token="t2", priority=0)
    names = [row["name"] for row in store.list_accounts()]
    assert names == ["high", "low"]


def test_mark_used_and_exhausted(store: CloudflareAIStore) -> None:
    store.add_account(name="z", account_id="e" * 32, api_token="token3")
    store.mark_used("z", neurons=1.5)
    row = store.get_account("z") or {}
    assert row["usage_count"] == 1
    assert row["neurons_used_today"] == 1.5

    store.mark_used("z", error="quota", exhausted=True)
    row = store.get_account("z") or {}
    assert row["quota_exhausted_at"]
    assert store.account_available(row) is False


def test_set_default_model(store: CloudflareAIStore) -> None:
    resolved = store.set_default_model("quality")
    assert resolved == resolve_model_id("quality")
    assert store.default_model() == "@cf/openai/gpt-oss-120b"


def test_mask_token() -> None:
    assert mask_token("short") == "***"
    assert mask_token("cfut_abcdefghijklmnop") == "cfut…mnop"
