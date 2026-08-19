"""Remote command poller — polls the admin-bot bridge every N seconds.

Connects userbot instances to cf-admin-bot for real-time bidirectional control.

Lifecycle:
  poller = CommandPoller(runtime, account_id)
  poller_task = asyncio.create_task(poller.run(stop_event))
  # ... app runs ...
  stop_event.set()  # poller exits cleanly
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any

from app.bridge_client import bridge_configured, bridge_request
from app.command_handlers import dispatch_command
from app.paths import account_id as resolve_account_id

if TYPE_CHECKING:
    from app.runtime import ModuleRuntime

logger = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL = 30  # seconds


class CommandPoller:
    """Polls /internal/commands/poll and dispatches received commands."""

    def __init__(
        self,
        runtime: "ModuleRuntime",
        account_id: str,
        *,
        poll_interval: float | None = None,
        heartbeat_interval: float | None = None,
    ) -> None:
        self.runtime = runtime
        self.account_id = account_id
        self.poll_interval = float(
            poll_interval
            or os.environ.get("COMMAND_POLL_INTERVAL", _DEFAULT_POLL_INTERVAL)
        )
        # Heartbeat every ~2× poll interval if not explicitly set
        self.heartbeat_interval = float(
            heartbeat_interval or max(self.poll_interval * 2, 60)
        )
        self._last_heartbeat: float = 0.0

    async def run(self, stop_event: asyncio.Event) -> None:
        if not bridge_configured():
            logger.info(
                "command_poller: bridge not configured"
                " (ADMIN_BOT_BRIDGE_URL/TOKEN missing) — poller disabled"
            )
            return

        logger.info(
            "command_poller: starting for account_id=%s, poll_interval=%ss",
            self.account_id,
            self.poll_interval,
        )
        # Push initial heartbeat immediately
        await self._push_heartbeat()

        while not stop_event.is_set():
            try:
                await self._poll_and_execute()
            except Exception:
                logger.exception("command_poller: unexpected error during poll")

            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self.poll_interval
                )
            except asyncio.TimeoutError:
                pass

        logger.info("command_poller: stopped for account_id=%s", self.account_id)

    async def _poll_and_execute(self) -> None:
        import time

        now = time.monotonic()
        if now - self._last_heartbeat >= self.heartbeat_interval:
            await self._push_heartbeat()
            self._last_heartbeat = now

        resp = bridge_request(
            "GET",
            "/internal/commands/poll",
            query={"account_id": self.account_id, "limit": "10"},
        )
        if resp is None:
            logger.debug("command_poller: bridge unreachable or no response")
            return

        commands = resp.get("commands")
        if not isinstance(commands, list) or not commands:
            return

        logger.info(
            "command_poller: received %d command(s) for %s",
            len(commands),
            self.account_id,
        )

        for cmd in commands:
            if not isinstance(cmd, dict):
                continue
            cmd_id = str(cmd.get("id") or "")
            if not cmd_id:
                continue

            # Ack immediately so bridge knows we're handling it
            bridge_request(
                "POST",
                "/internal/commands/ack",
                payload={
                    "id": cmd_id,
                    "account_id": self.account_id,
                    "status": "acked",
                },
            )

            result = await dispatch_command(cmd, self.runtime)

            # Report final result
            bridge_request(
                "POST",
                "/internal/commands/ack",
                payload={
                    "id": cmd_id,
                    "account_id": self.account_id,
                    "status": "done" if result.get("ok") else "failed",
                    "result": result,
                },
            )

    async def _push_heartbeat(self) -> None:
        statuses = self.runtime.list_status()
        modules_map = {s["name"]: ("running" if s["running"] else "stopped") for s in statuses}

        import time

        meta: dict[str, Any] = {
            "uptime_hint": "running",
            "poll_interval": self.poll_interval,
        }
        try:
            meta["pid"] = os.getpid()
        except Exception:
            pass

        bridge_request(
            "POST",
            "/internal/commands/heartbeat",
            payload={
                "account_id": self.account_id,
                "status": "running",
                "modules": modules_map,
                "meta": meta,
            },
        )
        logger.debug("command_poller: heartbeat pushed for %s", self.account_id)


def build_poller(runtime: "ModuleRuntime") -> "CommandPoller | None":
    """Construct a CommandPoller if the bridge is configured."""
    if not bridge_configured():
        return None
    acc_id = resolve_account_id()
    return CommandPoller(runtime, acc_id)
