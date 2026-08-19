"""Bidirectional command bridge: admin/agent enqueues, userbot polls and acks.

Endpoints (all require Bridge Bearer token):
  GET  /internal/commands/poll?account_id=X[&limit=N]   — userbot polls
  POST /internal/commands/ack                            — userbot acks result
  POST /internal/commands/enqueue                        — admin/agent issues command
  GET  /internal/commands/status?account_id=X            — admin views recent commands
  POST /internal/commands/heartbeat                      — userbot pushes live status
  GET  /internal/commands/heartbeat?account_id=X         — admin views live status
"""
from __future__ import annotations

from app.Models.Command import VALID_TYPES, AccountHeartbeat, Command
from app.Support.BridgeAuth import require_bridge_token
from config.bot import BotConfig
from workers import Response


class InternalCommandsController:
    def __init__(self, env) -> None:
        self.config = BotConfig(env)
        self.db = self.config.db

    async def handle(self, request, action: str) -> Response:
        denied = require_bridge_token(request, self.config)
        if denied is not None:
            return denied

        method = request.method.upper()

        if action == "poll" and method == "GET":
            return await self._poll(request)

        if action == "ack" and method == "POST":
            return await self._ack(request)

        if action == "enqueue" and method == "POST":
            return await self._enqueue(request)

        if action == "status" and method == "GET":
            return await self._status(request)

        if action == "heartbeat" and method == "POST":
            return await self._heartbeat_push(request)

        if action == "heartbeat" and method == "GET":
            return await self._heartbeat_get(request)

        return Response.json({"ok": False, "error": "not_found"}, status=404)

    # ------------------------------------------------------------------
    # GET /internal/commands/poll?account_id=X&limit=N
    # Called by userbot every N seconds.
    # ------------------------------------------------------------------
    async def _poll(self, request) -> Response:
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(request.url).query)
        account_id = (qs.get("account_id") or [""])[0].strip().lower()
        if not account_id:
            return Response.json({"ok": False, "error": "missing account_id"}, status=400)
        try:
            limit = max(1, min(int((qs.get("limit") or ["10"])[0]), 50))
        except (ValueError, TypeError):
            limit = 10

        commands = await Command.poll_pending(self.db, account_id, limit=limit)
        return Response.json(
            {
                "ok": True,
                "account_id": account_id,
                "commands": [c.to_view() for c in commands],
            }
        )

    # ------------------------------------------------------------------
    # POST /internal/commands/ack
    # Body: {"id": "...", "account_id": "...", "status": "done|failed",
    #        "result": {...}}
    # ------------------------------------------------------------------
    async def _ack(self, request) -> Response:
        data = await _json_body(request)
        if data is None:
            return Response.json({"ok": False, "error": "bad_json"}, status=400)

        cmd_id = str(data.get("id") or "").strip()
        account_id = str(data.get("account_id") or "").strip().lower()
        status = str(data.get("status") or "done").strip().lower()
        result = data.get("result")

        if not cmd_id or not account_id:
            return Response.json({"ok": False, "error": "missing fields"}, status=400)
        if status not in {"done", "failed", "acked"}:
            status = "done"
        if result is not None and not isinstance(result, dict):
            result = {"value": str(result)}

        found = await Command.ack(
            self.db,
            cmd_id,
            account_id=account_id,
            result=result,
            status=status,
        )
        if not found:
            return Response.json({"ok": False, "error": "command_not_found"}, status=404)
        return Response.json({"ok": True, "id": cmd_id, "status": status})

    # ------------------------------------------------------------------
    # POST /internal/commands/enqueue
    # Body: {"account_id": "...", "type": "...", "payload": {...},
    #        "issued_by": "admin", "ttl_seconds": 300}
    # ------------------------------------------------------------------
    async def _enqueue(self, request) -> Response:
        data = await _json_body(request)
        if data is None:
            return Response.json({"ok": False, "error": "bad_json"}, status=400)

        account_id = str(data.get("account_id") or "").strip().lower()
        command_type = str(data.get("type") or "").strip().lower()
        payload = data.get("payload")
        issued_by = str(data.get("issued_by") or "admin").strip()
        try:
            ttl = max(10, min(int(data.get("ttl_seconds") or 300), 86400))
        except (ValueError, TypeError):
            ttl = 300

        if not account_id:
            return Response.json({"ok": False, "error": "missing account_id"}, status=400)
        if command_type not in VALID_TYPES:
            return Response.json(
                {
                    "ok": False,
                    "error": f"invalid type. valid: {sorted(VALID_TYPES)}",
                },
                status=400,
            )
        if payload is not None and not isinstance(payload, dict):
            return Response.json({"ok": False, "error": "payload must be object"}, status=400)

        cmd = await Command.enqueue(
            self.db,
            account_id=account_id,
            command_type=command_type,
            payload=payload or {},
            issued_by=issued_by,
            ttl_seconds=ttl,
        )
        return Response.json({"ok": True, "command": cmd.to_view()}, status=201)

    # ------------------------------------------------------------------
    # GET /internal/commands/status?account_id=X&limit=N
    # ------------------------------------------------------------------
    async def _status(self, request) -> Response:
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(request.url).query)
        account_id = (qs.get("account_id") or [""])[0].strip().lower()
        if not account_id:
            return Response.json({"ok": False, "error": "missing account_id"}, status=400)
        try:
            limit = max(1, min(int((qs.get("limit") or ["20"])[0]), 50))
        except (ValueError, TypeError):
            limit = 20

        commands = await Command.list_recent(self.db, account_id, limit=limit)
        heartbeat = await AccountHeartbeat.find(self.db, account_id)
        return Response.json(
            {
                "ok": True,
                "account_id": account_id,
                "heartbeat": heartbeat.to_view() if heartbeat else None,
                "commands": [c.to_view() for c in commands],
            }
        )

    # ------------------------------------------------------------------
    # POST /internal/commands/heartbeat
    # Body: {"account_id": "...", "status": "running",
    #        "modules": {...}, "meta": {...}}
    # ------------------------------------------------------------------
    async def _heartbeat_push(self, request) -> Response:
        data = await _json_body(request)
        if data is None:
            return Response.json({"ok": False, "error": "bad_json"}, status=400)

        account_id = str(data.get("account_id") or "").strip().lower()
        if not account_id:
            return Response.json({"ok": False, "error": "missing account_id"}, status=400)

        status = str(data.get("status") or "running").strip().lower()
        modules = data.get("modules")
        meta = data.get("meta")
        if not isinstance(modules, dict):
            modules = {}
        if not isinstance(meta, dict):
            meta = {}

        await AccountHeartbeat.upsert(
            self.db,
            account_id,
            status=status,
            modules=modules,
            meta=meta,
        )
        return Response.json({"ok": True, "account_id": account_id})

    # ------------------------------------------------------------------
    # GET /internal/commands/heartbeat?account_id=X
    # ------------------------------------------------------------------
    async def _heartbeat_get(self, request) -> Response:
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(request.url).query)
        account_id = (qs.get("account_id") or [""])[0].strip().lower()
        if not account_id:
            return Response.json({"ok": False, "error": "missing account_id"}, status=400)

        hb = await AccountHeartbeat.find(self.db, account_id)
        if hb is None:
            return Response.json(
                {"ok": True, "account_id": account_id, "heartbeat": None}
            )
        return Response.json({"ok": True, "account_id": account_id, "heartbeat": hb.to_view()})


async def _json_body(request) -> dict | None:
    try:
        data = await request.json()
        if hasattr(data, "to_py"):
            data = data.to_py()
        return data if isinstance(data, dict) else None
    except Exception:
        return None
