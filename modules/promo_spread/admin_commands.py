"""Admin chat commands for /promo (multi-route)."""
from __future__ import annotations

from typing import Any

from app.progress import ProgressMessenger
from modules.channel_forward.refs import display_ref
from modules.promo_spread.routes import (
    default_route,
    find_route,
    migrate_routes,
    remove_route,
    upsert_route,
)
from modules.promo_spread.safety import SafetyConfig
from modules.promo_spread.targets import normalize_group_list


def _parse_windows(raw: str) -> list[dict[str, str]]:
    windows: list[dict[str, str]] = []
    for part in raw.replace("،", ",").split(","):
        part = part.strip()
        if not part or "-" not in part:
            continue
        start, end = part.split("-", 1)
        windows.append({"start": start.strip(), "end": end.strip()})
    return windows


def _routes(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    return migrate_routes(cfg)


async def _save_routes(runtime, cfg: dict[str, Any], routes: list[dict[str, Any]]) -> str:
    # Keep routes as source of truth; clear legacy single-source fields.
    cfg["routes"] = routes
    cfg["source"] = None
    cfg["groups"] = []
    return await runtime.patch_module_config(
        "promo_spread",
        {"routes": routes, "source": None, "groups": []},
    )


async def handle_promo_command(
    parts: list[str],
    *,
    cfg: dict[str, Any],
    runtime,
    progress: ProgressMessenger,
    safety_summary: list[str],
    queue_pending: int,
) -> None:
    action = parts[1].lower() if len(parts) >= 2 else "status"
    routes = _routes(cfg)

    if action in {"status", "stat"}:
        await progress.set_title("📣 Promo Spread")
        await progress.step(
            f"enabled/paused: {cfg.get('enabled')} / {cfg.get('paused')}"
        )
        await progress.step(
            f"dry_run: {cfg.get('dry_run')} · default mode: {cfg.get('mode', 'forward')}"
        )
        await progress.step(f"routes: {len(routes)} · queue pending: {queue_pending}")
        if not routes:
            await progress.step("هیچ مسیری نیست — `/promo add @channel @group1,@group2`")
        for i, route in enumerate(routes, 1):
            groups = normalize_group_list(route.get("groups"))
            flag = "ON" if route.get("enabled", True) else "OFF"
            pause = "paused" if route.get("paused") else "live"
            await progress.step(
                f"{i}) `{route.get('source')}` → {len(groups)} group(s) "
                f"[{flag}/{pause}/{route.get('mode', 'forward')}]"
            )
            preview = ", ".join(f"`{g}`" for g in groups[:6]) or "—"
            await progress.step(f"   {preview}" + (" …" if len(groups) > 6 else ""))
        for line in safety_summary:
            await progress.step(line)
        await progress.success("راهنما: `/promo help`")
        return

    if action == "help":
        await progress.success(
            "📣 دستورات promo (چند مسیر)\n"
            "────────────\n"
            "`/promo status`\n"
            "`/promo add @channel @g1,@g2` — مسیر جدید\n"
            "`/promo remove @channel` — حذف مسیر\n"
            "`/promo group add @channel @group`\n"
            "`/promo group remove @channel @group`\n"
            "`/promo groups @channel`\n"
            "`/promo mode @channel forward|copy`\n"
            "`/promo pause @channel` | `/promo resume @channel`\n"
            "`/promo pause` | `/promo resume` — همه مسیرها\n"
            "`/promo dryrun on|off`\n"
            "`/promo queue [clear]`\n"
            "`/promo safety …`\n"
            "\n"
            "هر کانال فقط به گروه‌های خودش وصل است.\n"
            "گروه خصوصی: لینک دعوت هم قبول است\n"
            "`https://t.me/+xxxx` یا `t.me/joinchat/xxxx`\n"
            "اول `dryrun on`، بعد تست."
        )
        return

    if action == "add" and len(parts) >= 4:
        source = display_ref(parts[2])
        groups = normalize_group_list(parts[3].replace("،", ",").split(","))
        if not groups:
            await progress.fail("حداقل یک گروه بده: `@g1,@g2`")
            return
        route = default_route(source, groups, mode=cfg.get("mode") or "forward")
        # merge groups if route exists
        existing = find_route(routes, source)
        if existing:
            merged = normalize_group_list(list(existing.get("groups") or []) + groups)
            route = default_route(
                source,
                merged,
                enabled=existing.get("enabled", True),
                paused=existing.get("paused", False),
                mode=existing.get("mode") or route["mode"],
            )
        routes = upsert_route(routes, route)
        result = await _save_routes(runtime, cfg, routes)
        await progress.success(
            f"مسیر `{source}` → {len(route['groups'])} گروه\n{result}"
        )
        return

    if action == "remove" and len(parts) >= 3:
        source = display_ref(parts[2])
        routes = remove_route(routes, source)
        result = await _save_routes(runtime, cfg, routes)
        await progress.success(f"مسیر `{source}` حذف شد.\n{result}")
        return

    # Legacy: /promo source @channel  → create/empty route
    if action == "source" and len(parts) >= 3:
        source = display_ref(parts[2])
        existing = find_route(routes, source)
        if existing is None:
            routes = upsert_route(routes, default_route(source, [], mode=cfg.get("mode")))
            result = await _save_routes(runtime, cfg, routes)
            await progress.success(
                f"مسیر `{source}` ساخته شد (هنوز گروه ندارد).\n"
                f"`/promo group add {source} @group`\n{result}"
            )
            return
        await progress.success(f"مسیر `{source}` از قبل هست.")
        return

    if action == "group" and len(parts) >= 4:
        sub = parts[2].lower()
        source = display_ref(parts[3])
        route = find_route(routes, source)
        if route is None and sub == "add" and len(parts) >= 5:
            route = default_route(source, [], mode=cfg.get("mode"))
        if route is None:
            await progress.fail(f"مسیر `{source}` نیست. اول `/promo add` بزن.")
            return
        groups = normalize_group_list(route.get("groups"))
        if sub == "add" and len(parts) >= 5:
            ref = display_ref(parts[4])
            if ref not in groups:
                groups.append(ref)
            route["groups"] = groups
            routes = upsert_route(routes, route)
            result = await _save_routes(runtime, cfg, routes)
            await progress.success(f"`{source}` ← `{ref}`\nجمع گروه: {len(groups)}\n{result}")
            return
        if sub == "remove" and len(parts) >= 5:
            ref = display_ref(parts[4])
            groups = [g for g in groups if g != ref]
            route["groups"] = groups
            routes = upsert_route(routes, route)
            result = await _save_routes(runtime, cfg, routes)
            await progress.success(f"`{ref}` از `{source}` حذف شد.\nجمع: {len(groups)}\n{result}")
            return
        await progress.fail("`/promo group add|remove @channel @group`")
        return

    if action == "groups":
        if len(parts) >= 3:
            source = display_ref(parts[2])
            route = find_route(routes, source)
            if route is None:
                await progress.fail("مسیر پیدا نشد.")
                return
            groups = normalize_group_list(route.get("groups"))
            for i, g in enumerate(groups, 1):
                await progress.step(f"{i}) `{g}`")
            await progress.success(f"`{source}` — {len(groups)} گروه")
            return
        if not routes:
            await progress.success("مسیری نیست.")
            return
        for route in routes:
            groups = normalize_group_list(route.get("groups"))
            await progress.step(
                f"`{route.get('source')}` → " + (", ".join(f"`{g}`" for g in groups) or "—")
            )
        await progress.success(f"{len(routes)} مسیر")
        return

    if action == "mode":
        # /promo mode forward  OR  /promo mode @channel forward
        if len(parts) == 3 and parts[2].lower() in {"forward", "copy"}:
            mode = parts[2].lower()
            result = await runtime.patch_module_config("promo_spread", {"mode": mode})
            await progress.success(f"default mode={mode}\n{result}")
            return
        if len(parts) >= 4:
            source = display_ref(parts[2])
            mode = parts[3].lower()
            if mode not in {"forward", "copy"}:
                await progress.fail("`forward` یا `copy`")
                return
            route = find_route(routes, source)
            if route is None:
                await progress.fail("مسیر پیدا نشد.")
                return
            route["mode"] = mode
            routes = upsert_route(routes, route)
            result = await _save_routes(runtime, cfg, routes)
            await progress.success(f"`{source}` mode={mode}\n{result}")
            return
        await progress.fail("`/promo mode forward` یا `/promo mode @channel copy`")
        return

    if action == "dryrun":
        if len(parts) >= 3:
            val = parts[2].lower() == "on"
        else:
            val = not bool(cfg.get("dry_run"))
        result = await runtime.patch_module_config("promo_spread", {"dry_run": val})
        await progress.success(f"dry_run={val}\n{result}")
        return

    if action == "pause":
        if len(parts) >= 3:
            source = display_ref(parts[2])
            route = find_route(routes, source)
            if route is None:
                await progress.fail("مسیر پیدا نشد.")
                return
            route["paused"] = True
            routes = upsert_route(routes, route)
            result = await _save_routes(runtime, cfg, routes)
            await progress.success(f"`{source}` paused\n{result}")
            return
        result = await runtime.patch_module_config("promo_spread", {"paused": True})
        await progress.success(f"همه مسیرها paused (global)\n{result}")
        return

    if action == "resume":
        if len(parts) >= 3:
            source = display_ref(parts[2])
            route = find_route(routes, source)
            if route is None:
                await progress.fail("مسیر پیدا نشد.")
                return
            route["paused"] = False
            routes = upsert_route(routes, route)
            result = await _save_routes(runtime, cfg, routes)
            await progress.success(f"`{source}` resumed\n{result}")
            return
        result = await runtime.patch_module_config("promo_spread", {"paused": False})
        await progress.success(f"global resume\n{result}")
        return

    if action == "queue":
        sub = parts[2].lower() if len(parts) >= 3 else "status"
        if sub == "clear":
            from modules.promo_spread.queue import PromoQueue

            n = PromoQueue().clear_pending()
            await progress.success(f"صف پاک شد ({n})")
            return
        await progress.success(f"صف pending: {queue_pending}")
        return

    if action == "safety":
        safety = SafetyConfig.from_dict(cfg.get("safety"))
        if len(parts) == 2:
            for line in safety_summary:
                await progress.step(line)
            await progress.success("برای تغییر: `/promo safety delay|budget|windows|cooldown`")
            return
        sub = parts[2].lower()
        patch: dict[str, Any] = safety.to_dict()
        if sub == "delay" and len(parts) >= 5:
            patch["delay_min_seconds"] = float(parts[3])
            patch["delay_max_seconds"] = float(parts[4])
        elif sub == "budget":
            i = 3
            while i + 1 < len(parts):
                key = parts[i].lower()
                val = int(parts[i + 1])
                if key == "daily":
                    patch["daily_budget"] = val
                elif key == "hourly":
                    patch["hourly_budget"] = val
                i += 2
        elif sub == "windows" and len(parts) >= 4:
            wins = _parse_windows(" ".join(parts[3:]))
            if not wins:
                await progress.fail("فرمت: `09:30-13:00,16:00-22:00`")
                return
            patch["active_windows"] = wins
        elif sub == "cooldown" and len(parts) >= 4:
            patch["per_group_cooldown_minutes"] = int(parts[3])
        elif sub == "tz" and len(parts) >= 4:
            patch["timezone"] = parts[3]
        else:
            await progress.fail(
                "`/promo safety delay 70 190`\n"
                "`/promo safety budget daily 28 hourly 5`\n"
                "`/promo safety windows 09:30-13:00,16:00-22:00`\n"
                "`/promo safety cooldown 50`"
            )
            return
        result = await runtime.patch_module_config("promo_spread", {"safety": patch})
        await progress.success(f"safety به‌روز شد\n{result}")
        return

    await progress.fail("دستور ناشناخته — `/promo help`")
