"""Admin commands for /harvest, /inspect, /pool."""
from __future__ import annotations

from typing import Any

from modules.channel_forward.refs import display_ref
from modules.group_pool.pool import GroupPool, normalize_group_ref
from modules.promo_spread.routes import find_route, migrate_routes, upsert_route
from modules.promo_spread.targets import normalize_group_list


async def handle_harvest_command(
    parts: list[str],
    *,
    cfg: dict[str, Any],
    runtime,
    progress,
) -> None:
    action = parts[1].lower() if len(parts) >= 2 else "status"
    dirs = [str(x) for x in (cfg.get("directories") or []) if str(x).strip()]

    if action in {"status", "stat"}:
        await progress.set_title("🧺 Link harvest")
        await progress.step(f"enabled: {cfg.get('enabled')} · paused: {cfg.get('paused')}")
        await progress.step(f"directories: {len(dirs)} · catch_up: {cfg.get('catch_up_limit', 40)}")
        for i, d in enumerate(dirs, 1):
            await progress.step(f"{i}) `{display_ref(d)}`")
        await progress.success("راهنما: `/harvest help`")
        return

    if action == "help":
        await progress.success(
            "🧺 دستورات harvest (collector)\n"
            "`/harvest status`\n"
            "`/harvest add @Link4you`\n"
            "`/harvest remove @Link4you`\n"
            "`/harvest pause` | `/harvest resume`\n"
            "`/harvest catchup <n>`\n"
            "\n"
            "فقط خواندن لینکدونی — جوین گروه مقصد انجام نمی‌شود."
        )
        return

    if action == "add" and len(parts) >= 3:
        ref = parts[2]
        shown = display_ref(ref)
        if any(display_ref(d) == shown for d in dirs):
            await progress.fail("از قبل در لیست است")
            return
        if len(dirs) >= 5:
            await progress.fail("سقف ۵ لینکدونی per collector")
            return
        dirs.append(shown)
        path = await runtime.patch_module_config("link_harvest", {"directories": dirs})
        await progress.success(f"اضافه شد: `{shown}`\n{path}\nماژول را reload کن.")
        return

    if action == "remove" and len(parts) >= 3:
        ref = display_ref(parts[2])
        new_dirs = [d for d in dirs if display_ref(d) != ref]
        if len(new_dirs) == len(dirs):
            await progress.fail("پیدا نشد")
            return
        path = await runtime.patch_module_config("link_harvest", {"directories": new_dirs})
        await progress.success(f"حذف شد: `{ref}`\n{path}")
        return

    if action == "pause":
        path = await runtime.patch_module_config("link_harvest", {"paused": True})
        await progress.success(f"harvest paused\n{path}")
        return

    if action == "resume":
        path = await runtime.patch_module_config("link_harvest", {"paused": False})
        await progress.success(f"harvest resumed\n{path}")
        return

    if action == "catchup" and len(parts) >= 3:
        try:
            n = max(0, min(200, int(parts[2])))
        except ValueError:
            await progress.fail("عدد نامعتبر")
            return
        path = await runtime.patch_module_config("link_harvest", {"catch_up_limit": n})
        await progress.success(f"catch_up_limit={n}\n{path}")
        return

    await progress.fail("دستور نامعتبر — `/harvest help`")


async def handle_inspect_command(
    parts: list[str],
    *,
    cfg: dict[str, Any],
    runtime,
    progress,
) -> None:
    action = parts[1].lower() if len(parts) >= 2 else "status"

    if action in {"status", "stat"}:
        await progress.set_title("🔎 Group inspect")
        await progress.step(
            f"enabled: {cfg.get('enabled')} · dry_run: {cfg.get('dry_run')} · paused: {cfg.get('paused')}"
        )
        await progress.step(
            f"daily_join_budget: {cfg.get('daily_join_budget', 4)} · "
            f"delay: {cfg.get('delay_min_seconds', 1800)}-{cfg.get('delay_max_seconds', 10800)}s"
        )
        await progress.success("راهنما: `/inspect help`")
        return

    if action == "help":
        await progress.success(
            "🔎 دستورات inspect\n"
            "`/inspect status`\n"
            "`/inspect dryrun on|off`\n"
            "`/inspect pause` | `/inspect resume`\n"
            "`/inspect budget <1-12>`\n"
            "\n"
            "جوین خیلی آهسته + چک ربات ضداسپم + leave.\n"
            "هرگز روی اکانت promo روشن نکن."
        )
        return

    if action == "dryrun" and len(parts) >= 3:
        val = parts[2].lower() in {"on", "1", "true", "yes"}
        path = await runtime.patch_module_config("group_inspect", {"dry_run": val})
        await progress.success(f"dry_run={val}\n{path}")
        return

    if action == "pause":
        path = await runtime.patch_module_config("group_inspect", {"paused": True})
        await progress.success(f"inspect paused\n{path}")
        return

    if action == "resume":
        path = await runtime.patch_module_config("group_inspect", {"paused": False})
        await progress.success(f"inspect resumed\n{path}")
        return

    if action == "budget" and len(parts) >= 3:
        try:
            n = max(1, min(12, int(parts[2])))
        except ValueError:
            await progress.fail("عدد 1-12")
            return
        path = await runtime.patch_module_config("group_inspect", {"daily_join_budget": n})
        await progress.success(f"daily_join_budget={n}\n{path}")
        return

    await progress.fail("دستور نامعتبر — `/inspect help`")


async def handle_pool_command(
    parts: list[str],
    *,
    runtime,
    progress,
) -> None:
    action = parts[1].lower() if len(parts) >= 2 else "status"
    pool = GroupPool()

    if action in {"status", "stat"}:
        counts = pool.counts()
        await progress.set_title("📦 Group pool")
        await progress.step(
            f"total={counts['total']} raw={counts['raw']} "
            f"ok={counts['inspected_ok']} rejected={counts['rejected']} "
            f"approved={counts['approved']}"
        )
        await progress.success("راهنما: `/pool help`")
        return

    if action == "help":
        await progress.success(
            "📦 دستورات pool\n"
            "`/pool status`\n"
            "`/pool list [raw|inspected_ok|rejected|approved]`\n"
            "`/pool approve <ref>`\n"
            "`/pool reject <ref>`\n"
            "`/pool to-promo <source_channel> <ref>`\n"
            "\n"
            "approved را دستی به promo بده؛ auto-approve نداریم."
        )
        return

    if action == "list":
        status = parts[2].lower() if len(parts) >= 3 else None
        rows = pool.list_by_status(status, limit=15)
        await progress.set_title(f"📦 pool list ({status or 'all'})")
        if not rows:
            await progress.success("خالی است")
            return
        for i, row in enumerate(rows, 1):
            title = row.get("title") or ""
            await progress.step(
                f"{i}) `{row.get('ref')}` [{row.get('status')}] {title}"
            )
        await progress.success("تمام")
        return

    if action == "approve" and len(parts) >= 3:
        ref = normalize_group_ref(parts[2]) or parts[2]
        item = pool.set_status(ref, "approved", note="admin_approve")
        await progress.success(f"approved: `{item.get('ref')}`")
        return

    if action == "reject" and len(parts) >= 3:
        ref = normalize_group_ref(parts[2]) or parts[2]
        item = pool.set_status(ref, "rejected", note="admin_reject")
        await progress.success(f"rejected: `{item.get('ref')}`")
        return

    if action in {"to-promo", "topromo", "promo"} and len(parts) >= 4:
        source = display_ref(parts[2])
        ref = normalize_group_ref(parts[3]) or parts[3]
        item = pool.get(ref)
        if not item:
            await progress.fail("لینک در pool نیست")
            return
        if item.get("status") != "approved":
            await progress.fail(
                f"وضعیت فعلی `{item.get('status')}` است — اول `/pool approve` بزن"
            )
            return

        promo_cfg = runtime.modules_config.setdefault("promo_spread", {})
        if not isinstance(promo_cfg, dict):
            promo_cfg = {}
            runtime.modules_config["promo_spread"] = promo_cfg
        routes = migrate_routes(promo_cfg)
        route = find_route(routes, source)
        if not route:
            route = {
                "source": source,
                "groups": [],
                "enabled": True,
                "paused": False,
                "mode": promo_cfg.get("mode") or "forward",
            }
        groups = normalize_group_list(route.get("groups"))
        shown = item["ref"]
        if shown not in groups and display_ref(shown) not in [display_ref(g) for g in groups]:
            groups.append(shown)
        route["groups"] = groups
        routes = upsert_route(routes, route)
        path = await runtime.patch_module_config(
            "promo_spread",
            {"routes": routes, "source": None, "groups": [], "auto_join": False},
        )
        await progress.success(
            f"به promo اضافه شد:\nمنبع `{source}` → `{shown}`\n{path}\n"
            "اگر لازم است `/module reload promo_spread`"
        )
        return

    await progress.fail("دستور نامعتبر — `/pool help`")
