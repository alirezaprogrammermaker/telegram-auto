"""Shared Bearer check for Worker↔GHA bridge endpoints."""
from __future__ import annotations

from app.Support.Lang import __
from config.bot import BotConfig
from workers import Response


def unauthorized() -> Response:
    return Response.json({"ok": False, "error": __("error.unauthorized")}, status=401)


def bridge_disabled() -> Response:
    return Response.json({"ok": False, "error": "bridge_disabled"}, status=503)


def require_bridge_token(request, config: BotConfig) -> Response | None:
    """Return an error Response if auth fails; None if OK."""
    expected = config.bridge_token
    if not expected:
        return bridge_disabled()
    auth = request.headers.get("Authorization") or ""
    token = ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if token != expected:
        return unauthorized()
    return None
