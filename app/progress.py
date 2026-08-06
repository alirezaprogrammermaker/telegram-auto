"""Editable progress messages for long admin operations.

Usage:
    progress = ProgressMessenger(event)
    await progress.start("⏳ صبر کنید…")
    await progress.step("بررسی کانال مبدأ")
    await progress.step("باید جوین بشوم")
    await progress.success("مسیر ذخیره شد")
    # or: await progress.fail("خطا …")
"""
from __future__ import annotations

import logging
from typing import Any

from telethon.errors import MessageNotModifiedError

logger = logging.getLogger(__name__)


class ProgressMessenger:
    """Send one chat message and edit it as steps complete."""

    def __init__(self, event: Any) -> None:
        self.event = event
        self.message: Any | None = None
        self.title = "⏳ صبر کنید…"
        self.steps: list[str] = []
        self._finished = False

    async def start(self, title: str = "⏳ صبر کنید…") -> None:
        self.title = title
        self.steps = []
        self._finished = False
        self.message = await self.event.respond(title)

    async def step(self, text: str) -> None:
        """Append a progress line and edit the message."""
        self.steps.append(text)
        await self._render()

    async def replace_last(self, text: str) -> None:
        if self.steps:
            self.steps[-1] = text
        else:
            self.steps.append(text)
        await self._render()

    async def success(self, text: str) -> None:
        self.steps.append(f"✅ {text}")
        self._finished = True
        await self._render()

    async def fail(self, text: str) -> None:
        self.steps.append(f"❌ {text}")
        self._finished = True
        await self._render()

    async def set_title(self, title: str) -> None:
        self.title = title
        await self._render()

    def _body(self) -> str:
        lines = [self.title, ""]
        for index, step in enumerate(self.steps, start=1):
            lines.append(f"{index}. {step}")
        return "\n".join(lines).strip()

    async def _render(self) -> None:
        if self.message is None:
            return
        text = self._body()
        # Telegram limit safety
        if len(text) > 3900:
            text = text[-3900:]
        try:
            await self.message.edit(text)
        except MessageNotModifiedError:
            return
        except Exception:
            logger.debug("progress edit failed", exc_info=True)
