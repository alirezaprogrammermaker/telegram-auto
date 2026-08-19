"""AgentCommandBus — thin abstraction layer for AI agent integration.

Usage (future agent):
    from app.agent_bus import AgentCommandBus

    bus = AgentCommandBus()
    result = bus.enqueue("promo1", "pause_route", {"source": "@channel"})
    # result: {"ok": True, "command": {...}} or None

The bus uses the same HTTP bridge that the userbot uses for heartbeats,
so no new infrastructure is needed.

The agent can also query live account status:
    status = bus.get_status("promo1")
    heartbeat = bus.get_heartbeat("promo1")
"""
from __future__ import annotations

import logging
from typing import Any

from app.bridge_client import bridge_configured, bridge_request

logger = logging.getLogger(__name__)

# Allowed command types (mirrors VALID_TYPES in cf-admin-bot)
VALID_TYPES = frozenset(
    {
        "ping",
        "config_patch",
        "module_on",
        "module_off",
        "module_reload",
        "pause_route",
        "resume_route",
        "flush_queue",
        "heartbeat_request",
    }
)


class AgentCommandBus:
    """Synchronous command bus for use by AI agents or automation scripts.

    All methods return dicts or None (never raise on network errors).
    """

    def __init__(self, *, issued_by: str = "agent", ttl_seconds: int = 300) -> None:
        self.issued_by = issued_by
        self.ttl_seconds = ttl_seconds

    def is_available(self) -> bool:
        """Return True if the bridge is configured and can be used."""
        return bridge_configured()

    def enqueue(
        self,
        account_id: str,
        command_type: str,
        payload: dict[str, Any] | None = None,
        *,
        ttl_seconds: int | None = None,
    ) -> dict[str, Any] | None:
        """Enqueue a command for a userbot account.

        Returns the created command dict on success, or None on failure.

        Example:
            bus.enqueue("promo1", "pause_route", {"source": "@channel"})
            bus.enqueue("forward1", "module_off", {"module": "promo_spread"})
            bus.enqueue("acc1", "config_patch", {
                "module": "channel_forward",
                "patch": {"routes": [...]},
                "reload": True,
            })
        """
        if not self.is_available():
            logger.warning("agent_bus.enqueue: bridge not configured")
            return None
        if command_type not in VALID_TYPES:
            logger.warning("agent_bus.enqueue: invalid type '%s'", command_type)
            return None

        resp = bridge_request(
            "POST",
            "/internal/commands/enqueue",
            payload={
                "account_id": account_id,
                "type": command_type,
                "payload": payload or {},
                "issued_by": self.issued_by,
                "ttl_seconds": ttl_seconds or self.ttl_seconds,
            },
        )
        if resp and resp.get("ok"):
            return resp.get("command")
        logger.warning("agent_bus.enqueue: bridge returned %s", resp)
        return None

    def get_status(
        self, account_id: str, *, limit: int = 10
    ) -> dict[str, Any] | None:
        """Get recent commands and heartbeat for an account.

        Returns:
            {
                "heartbeat": {...} | None,
                "commands": [...],
            }
        """
        if not self.is_available():
            return None
        resp = bridge_request(
            "GET",
            "/internal/commands/status",
            query={"account_id": account_id, "limit": str(limit)},
        )
        if resp and resp.get("ok"):
            return {
                "heartbeat": resp.get("heartbeat"),
                "commands": resp.get("commands") or [],
            }
        return None

    def get_heartbeat(self, account_id: str) -> dict[str, Any] | None:
        """Get the latest heartbeat for an account (fast single-record lookup)."""
        if not self.is_available():
            return None
        resp = bridge_request(
            "GET",
            "/internal/commands/heartbeat",
            query={"account_id": account_id},
        )
        if resp and resp.get("ok"):
            return resp.get("heartbeat")
        return None

    def ping(self, account_id: str) -> dict[str, Any] | None:
        """Send a ping command and return the enqueued command dict."""
        return self.enqueue(account_id, "ping")

    def pause_route(self, account_id: str, source: str) -> dict[str, Any] | None:
        return self.enqueue(account_id, "pause_route", {"source": source})

    def resume_route(self, account_id: str, source: str) -> dict[str, Any] | None:
        return self.enqueue(account_id, "resume_route", {"source": source})

    def module_on(self, account_id: str, module: str) -> dict[str, Any] | None:
        return self.enqueue(account_id, "module_on", {"module": module})

    def module_off(self, account_id: str, module: str) -> dict[str, Any] | None:
        return self.enqueue(account_id, "module_off", {"module": module})

    def flush_queue(
        self, account_id: str, queue: str = "forward"
    ) -> dict[str, Any] | None:
        return self.enqueue(account_id, "flush_queue", {"queue": queue})

    def config_patch(
        self,
        account_id: str,
        module: str,
        patch: dict[str, Any],
        *,
        reload: bool = True,
    ) -> dict[str, Any] | None:
        return self.enqueue(
            account_id,
            "config_patch",
            {"module": module, "patch": patch, "reload": reload},
        )
