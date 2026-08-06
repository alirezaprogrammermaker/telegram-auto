"""Route ownership and visibility helpers."""
from __future__ import annotations

from typing import Any


def normalize_visibility(value: Any) -> str:
    text = str(value or "private").strip().lower()
    if text in {"public", "pub", "عمومی", "shared", "share"}:
        return "public"
    return "private"


def route_owner_id(route: dict[str, Any]) -> int | None:
    raw = route.get("owner_id")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def can_view_route(route: dict[str, Any], user_id: int) -> bool:
    """Public or owned (legacy without owner is treated as public)."""
    owner = route_owner_id(route)
    if owner is None:
        return True
    if normalize_visibility(route.get("visibility")) == "public":
        return True
    return owner == int(user_id)


def can_edit_route(route: dict[str, Any], user_id: int) -> bool:
    """Only owner can edit; legacy without owner is editable until claimed."""
    owner = route_owner_id(route)
    if owner is None:
        return True
    return owner == int(user_id)


def visibility_label(route: dict[str, Any]) -> str:
    owner = route_owner_id(route)
    vis = normalize_visibility(route.get("visibility"))
    if owner is None:
        return "public(legacy)"
    return f"{vis} owner={owner}"
