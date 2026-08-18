"""Pure Telegram ref helpers for the Worker (no Telethon)."""
from __future__ import annotations

from typing import Any


def display_ref(value: Any) -> str:
    if isinstance(value, int):
        return str(value)
    text = str(value or "").strip()
    if not text:
        return text
    if text.startswith("@") or text.lstrip("-").isdigit() or "t.me/" in text:
        if text.startswith("@") or "t.me/" in text or text.startswith("-"):
            return text
        return f"@{text}"
    return f"@{text}"


def normalize_group_list(items: list[Any] | None) -> list[str]:
    out: list[str] = []
    for item in items or []:
        ref = display_ref(item)
        if not ref:
            continue
        if ref not in out and display_ref(ref) not in [display_ref(x) for x in out]:
            out.append(ref)
    return out


def default_route(
    source: Any,
    groups: list[Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    mode = str(kwargs.get("mode") or "forward").lower()
    if mode not in {"forward", "copy"}:
        mode = "forward"
    return {
        "source": display_ref(source) if source else None,
        "groups": normalize_group_list(groups or []),
        "enabled": bool(kwargs.get("enabled", True)),
        "paused": bool(kwargs.get("paused", False)),
        "mode": mode,
    }


def migrate_routes(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw = config.get("routes")
    if isinstance(raw, list) and raw:
        out: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            source = item.get("source")
            if not source:
                continue
            mode = str(item.get("mode") or config.get("mode") or "forward").lower()
            if mode not in {"forward", "copy"}:
                mode = "forward"
            out.append(
                {
                    "source": display_ref(source),
                    "groups": normalize_group_list(item.get("groups")),
                    "enabled": bool(item.get("enabled", True)),
                    "paused": bool(item.get("paused", False)),
                    "mode": mode,
                }
            )
        return out
    source = config.get("source")
    groups = normalize_group_list(config.get("groups"))
    if source:
        return [
            default_route(
                source,
                groups,
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


def upsert_route(
    routes: list[dict[str, Any]], route: dict[str, Any]
) -> list[dict[str, Any]]:
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
