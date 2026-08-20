"""Tests for /cfai admin command handlers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.cloudflare_ai.admin_commands import handle_cfai_command
from app.cloudflare_ai.store import CloudflareAIStore


class FakeProgress:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.failed: str | None = None

    async def set_title(self, text: str) -> None:
        self.messages.append(text)

    async def step(self, text: str) -> None:
        self.messages.append(text)

    async def success(self, text: str) -> None:
        self.messages.append(text)

    async def fail(self, text: str) -> None:
        self.failed = text


@pytest.fixture(autouse=True)
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CloudflareAIStore:
    path = tmp_path / "cloudflare_ai.json"
    store = CloudflareAIStore(path=path)
    monkeypatch.setattr("app.cloudflare_ai.admin_commands.CloudflareAIStore", lambda: store)
    monkeypatch.setattr("app.cloudflare_ai.provider.CloudflareAIStore", lambda: store)
    return store


@pytest.mark.asyncio
async def test_cfai_help() -> None:
    progress = FakeProgress()
    await handle_cfai_command(["/cfai", "help"], progress=progress)
    assert progress.failed is None
    assert any("Cloudflare AI admin" in msg for msg in progress.messages)


@pytest.mark.asyncio
async def test_cfai_add_and_status(isolated_store: CloudflareAIStore) -> None:
    progress = FakeProgress()
    await handle_cfai_command(
        [
            "/cfai",
            "add",
            "demo",
            "a" * 32,
            "cfut_demo_token_value_here",
        ],
        progress=progress,
    )
    assert progress.failed is None
    assert isolated_store.get_account("demo")

    progress = FakeProgress()
    await handle_cfai_command(["/cfai", "status"], progress=progress)
    assert progress.failed is None
    assert any("demo" in msg for msg in progress.messages)
