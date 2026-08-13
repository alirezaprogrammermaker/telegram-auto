"""Promo route schema: one source channel → many groups (multi-route)."""
from __future__ import annotations

from typing import Any

from modules.channel_forward.refs import display_ref
from modules.promo_spread.targets import normalize_group_list


def default_route(source: Any, groups: list[Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    return {
        "source": display_ref(source) if source else None,
        "groups": normalize_group_list(groups or []),
        "enabled": bool(kwargs.get("enabled", True)),
        "paused": bool(kwargs.get("paused", False)),
        "mode": str(kwargs.get("mode") or "forward").lower(),
    }


def migrate_routes(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Prefer routes[]; fall back to legacy single source/groups."""
    raw = config.get("routes")
    if isinstance(raw, list) and raw:
        out: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            source = item.get("source")
            groups = normalize_group_list(item.get("groups"))
            if not source or not groups:
                # keep incomplete routes so admin can finish setup via commands
                if not source:
                    continue
            mode = str(item.get("mode") or config.get("mode") or "forward").lower()
            if mode not in {"forward", "copy"}:
                mode = "forward"
            out.append(
                {
                    "source": display_ref(source),
                    "groups": groups,
                    "enabled": bool(item.get("enabled", True)),
                    "paused": bool(item.get("paused", False)),
                    "mode": mode,
                }
            )
        return out

    # Legacy single-source shape
    source = config.get("source")
    groups = normalize_group_list(config.get("groups"))
    if source:
        return [
            default_route(
                source,
                groups,
                enabled=True,
                paused=bool(config.get("paused", False)),
                mode=config.get("mode") or "forward",
            )
        ]
    return []


def find_route(routes: list[dict[str, Any]], source: Any) -> dict[str, Any] | None:
    want = display_ref(source)
    for route in routes:
        if display_ref(route.get("source")) == want:
            return route
    return None


def upsert_route(routes: list[dict[str, Any]], route: dict[str, Any]) -> list[dict[str, Any]]:
    src = display_ref(route.get("source"))
    out: list[dict[str, Any]] = []
    replaced = False
    for item in routes:
        if display_ref(item.get("source")) == src:
            out.append(route)
            replaced = True
        else:
            out.append(item)
    if not replaced:
        out.append(route)
    return out


def remove_route(routes: list[dict[str, Any]], source: Any) -> list[dict[str, Any]]:
    want = display_ref(source)
    return [r for r in routes if display_ref(r.get("source")) != want]
