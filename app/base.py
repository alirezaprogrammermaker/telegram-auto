"""Base contract for optional feature modules."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from telethon import TelegramClient


class BaseModule(ABC):
    """Every feature module implements this interface.

    Modules are optional: loader isolates failures so one broken module
    never takes down the whole application.
    """

    name: str = "unnamed"

    def __init__(self, client: TelegramClient, config: dict[str, Any]) -> None:
        self.client = client
        self.config = config

    @abstractmethod
    async def start(self) -> None:
        """Register handlers / begin background work."""

    async def stop(self) -> None:
        """Optional cleanup when the app shuts down."""
        return None
