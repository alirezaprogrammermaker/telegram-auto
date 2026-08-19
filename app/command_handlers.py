"""Handlers for remote commands received from the admin-bot bridge.

Each handler receives the command payload dict and the current ModuleRuntime,
executes the action, and returns a result dict.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.runtime import ModuleRuntime

logger = logging.getLogger(__name__)


async def handle_ping(payload: dict[str, Any], runtime: "ModuleRuntime") -> dict[str, Any]:
    """Simple health check — returns module statuses."""
    statuses = runtime.list_status()
    return {
        "pong": True,
        "modules": [
            {"name": s["name"], "running": s["running"], "enabled": s["enabled"]}
            for s in statuses
        ],
    }


async def handle_config_patch(
    payload: dict[str, Any], runtime: "ModuleRuntime"
) -> dict[str, Any]:
    """Hot-patch a module's config and optionally reload it.

    payload: {"module": "channel_forward", "patch": {...}, "reload": true}
    """
    module_name = str(payload.get("module") or "").strip()
    patch = payload.get("patch")
    do_reload = bool(payload.get("reload", True))

    if not module_name:
        return {"ok": False, "error": "missing 'module'"}
    if not isinstance(patch, dict) or not patch:
        return {"ok": False, "error": "missing or empty 'patch'"}

    msg = await runtime.patch_module_config(module_name, patch, reload=do_reload)
    return {"ok": True, "message": msg}


async def handle_module_on(
    payload: dict[str, Any], runtime: "ModuleRuntime"
) -> dict[str, Any]:
    module_name = str(payload.get("module") or "").strip()
    if not module_name:
        return {"ok": False, "error": "missing 'module'"}
    msg = await runtime.set_enabled(module_name, True)
    return {"ok": True, "message": msg}


async def handle_module_off(
    payload: dict[str, Any], runtime: "ModuleRuntime"
) -> dict[str, Any]:
    module_name = str(payload.get("module") or "").strip()
    if not module_name:
        return {"ok": False, "error": "missing 'module'"}
    msg = await runtime.set_enabled(module_name, False)
    return {"ok": True, "message": msg}


async def handle_module_reload(
    payload: dict[str, Any], runtime: "ModuleRuntime"
) -> dict[str, Any]:
    module_name = str(payload.get("module") or "").strip()
    if not module_name:
        return {"ok": False, "error": "missing 'module'"}
    msg = await runtime.reload_module(module_name)
    return {"ok": True, "message": msg}


async def handle_pause_route(
    payload: dict[str, Any], runtime: "ModuleRuntime"
) -> dict[str, Any]:
    """Pause a channel_forward route by source ref.

    payload: {"source": "@channel_or_id"}
    """
    return await _toggle_route_pause(payload, runtime, paused=True)


async def handle_resume_route(
    payload: dict[str, Any], runtime: "ModuleRuntime"
) -> dict[str, Any]:
    """Resume a paused channel_forward route.

    payload: {"source": "@channel_or_id"}
    """
    return await _toggle_route_pause(payload, runtime, paused=False)


async def _toggle_route_pause(
    payload: dict[str, Any], runtime: "ModuleRuntime", *, paused: bool
) -> dict[str, Any]:
    source = str(payload.get("source") or "").strip()
    if not source:
        return {"ok": False, "error": "missing 'source'"}

    cfg = runtime.modules_config.get("channel_forward")
    if not isinstance(cfg, dict):
        return {"ok": False, "error": "channel_forward not configured"}

    from modules.channel_forward.module import display_ref, migrate_routes

    routes = migrate_routes(cfg)
    found = False
    for route in routes:
        if str(route.get("source")) == source or display_ref(
            route.get("source")
        ) == display_ref(source):
            route["paused"] = paused
            found = True
            break

    if not found:
        return {"ok": False, "error": f"route '{source}' not found"}

    msg = await runtime.patch_module_config(
        "channel_forward", {"routes": routes}, reload=False
    )
    action = "paused" if paused else "resumed"
    return {"ok": True, "action": action, "source": source, "message": msg}


async def handle_flush_queue(
    payload: dict[str, Any], runtime: "ModuleRuntime"
) -> dict[str, Any]:
    """Flush a pending queue.

    payload: {"queue": "forward"|"promo"}
    """
    queue_name = str(payload.get("queue") or "forward").strip().lower()

    if queue_name == "forward":
        try:
            from modules.channel_forward.queue import PublishQueue

            q = PublishQueue()
            before = q.pending_count()
            q.clear()
            return {"ok": True, "queue": "forward", "cleared": before}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    if queue_name == "promo":
        try:
            from modules.promo_spread.queue import PromoQueue

            q = PromoQueue()
            before = q.pending_count()
            q.clear()
            return {"ok": True, "queue": "promo", "cleared": before}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    return {"ok": False, "error": f"unknown queue '{queue_name}'. use 'forward' or 'promo'"}


async def handle_heartbeat_request(
    payload: dict[str, Any], runtime: "ModuleRuntime"
) -> dict[str, Any]:
    """Respond with current live status (triggered by admin)."""
    return await handle_ping(payload, runtime)


# Registry: command type → handler function
COMMAND_HANDLERS: dict[str, Any] = {
    "ping": handle_ping,
    "config_patch": handle_config_patch,
    "module_on": handle_module_on,
    "module_off": handle_module_off,
    "module_reload": handle_module_reload,
    "pause_route": handle_pause_route,
    "resume_route": handle_resume_route,
    "flush_queue": handle_flush_queue,
    "heartbeat_request": handle_heartbeat_request,
}


async def dispatch_command(
    command: dict[str, Any], runtime: "ModuleRuntime"
) -> dict[str, Any]:
    """Dispatch a single command dict to its handler. Always returns a result dict."""
    cmd_type = str(command.get("type") or "").strip().lower()
    payload = command.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}

    handler = COMMAND_HANDLERS.get(cmd_type)
    if handler is None:
        logger.warning("command_poller: unknown command type '%s'", cmd_type)
        return {"ok": False, "error": f"unknown command type '{cmd_type}'"}

    try:
        result = await handler(payload, runtime)
        logger.info(
            "command_poller: executed '%s' → ok=%s", cmd_type, result.get("ok", "?")
        )
        return result
    except Exception as exc:
        logger.exception("command_poller: handler '%s' raised", cmd_type)
        return {"ok": False, "error": str(exc)}
