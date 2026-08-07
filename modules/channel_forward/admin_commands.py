"""Extended /forward admin command handlers."""
from __future__ import annotations

from typing import Any

from app.progress import ProgressMessenger
from modules.channel_forward.filters import TextFilterConfig, unescape_admin_text
from modules.channel_forward.media_filter import MEDIA_TYPES, MediaFilterConfig
from modules.channel_forward.module import display_ref
from modules.channel_forward.queue import PublishQueue
from modules.channel_forward.route_config import DedupConfig, DeliveryConfig, default_route_dict


async def handle_forward_extended(
    action: str,
    parts: list[str],
    *,
    routes: list[dict[str, Any]],
    runtime,
    progress: ProgressMessenger,
    actor_id: int,
    find_route,
    can_edit,
) -> bool:
    """Return True if handled."""
    queue = PublishQueue()

    if action == "queue":
        sub = parts[2].lower() if len(parts) >= 3 else "status"
        if sub == "clear":
            n = queue.clear(status="pending")
            await progress.success(f"صف pending پاک شد ({n} مورد).")
            return True
        pending = queue.list_pending()
        await progress.set_title("📥 صف انتشار")
        if not pending:
            await progress.success("صف خالی است.")
            return True
        for i, item in enumerate(pending[:15], start=1):
            await progress.step(
                f"{i}) `{item.get('route_key')}` ids={item.get('message_ids')} "
                f"status={item.get('status')}"
            )
        await progress.success(f"مجموع pending: {len(pending)}")
        return True

    if action in {"pause", "resume"} and len(parts) >= 3:
        source = parts[2].strip()
        route = find_route(source, need_edit=True)
        if route is None:
            await progress.fail("مسیر پیدا نشد یا اجازه ویرایش نداری.")
            return True
        route["paused"] = action == "pause"
        result = await runtime.patch_module_config("channel_forward", {"routes": routes})
        await progress.success(f"paused={route['paused']}\n{result}")
        return True

    if action == "dest" and len(parts) >= 4:
        sub = parts[2].lower()
        source = parts[3].strip()
        route = find_route(source, need_edit=True)
        if route is None:
            await progress.fail("مسیر پیدا نشد.")
            return True
        dests = route.get("destinations") or ([route.get("destination")] if route.get("destination") else [])
        if sub == "add" and len(parts) >= 5:
            dests.append(parts[4].strip())
            route["destinations"] = dests
            route["destination"] = dests[0]
            result = await runtime.patch_module_config("channel_forward", {"routes": routes})
            await progress.success(f"مقصد اضافه شد → {display_ref(parts[4])}\n{result}")
            return True
        if sub == "remove" and len(parts) >= 5:
            target = display_ref(parts[4])
            dests = [d for d in dests if display_ref(d) != target]
            if not dests:
                await progress.fail("حداقل یک مقصد لازم است.")
                return True
            route["destinations"] = dests
            route["destination"] = dests[0]
            result = await runtime.patch_module_config("channel_forward", {"routes": routes})
            await progress.success(f"مقصد حذف شد.\n{result}")
            return True
        await progress.fail("`/forward dest add|remove <source> <dest>`")
        return True

    if action == "media" and len(parts) >= 3:
        source = parts[2].strip()
        route = find_route(source, need_edit=len(parts) > 3)
        if route is None:
            await progress.fail("مسیر پیدا نشد.")
            return True
        mf = MediaFilterConfig.from_dict(route.get("media_filter"))
        if len(parts) == 3:
            for line in mf.summary_lines():
                await progress.step(line)
            await progress.success(f"انواع: {', '.join(MEDIA_TYPES)}")
            return True
        key = parts[3].lower()
        if key in {"on", "off"}:
            mf.enabled = key == "on"
        elif key == "allow" and len(parts) >= 5:
            mf.allow = [p.strip().lower() for p in " ".join(parts[4:]).replace("،", ",").split(",") if p.strip()]
            mf.enabled = True
        elif key == "deny" and len(parts) >= 5:
            mf.deny = [p.strip().lower() for p in " ".join(parts[4:]).replace("،", ",").split(",") if p.strip()]
            mf.enabled = True
        else:
            await progress.fail("`/forward media <source> on|allow photo,video`")
            return True
        route["media_filter"] = mf.to_dict()
        result = await runtime.patch_module_config("channel_forward", {"routes": routes})
        await progress.success(result)
        return True

    if action == "dedup" and len(parts) >= 3:
        source = parts[2].strip()
        route = find_route(source, need_edit=len(parts) > 3)
        if route is None:
            await progress.fail("مسیر پیدا نشد.")
            return True
        dd = DedupConfig.from_dict(route.get("dedup"))
        if len(parts) == 3:
            await progress.step(f"enabled={dd.enabled} window={dd.window_hours}h")
            await progress.success("`/forward dedup <source> on|off [hours]`")
            return True
        key = parts[3].lower()
        if key in {"on", "off"}:
            dd.enabled = key == "on"
        if len(parts) >= 5 and parts[4].isdigit():
            dd.window_hours = int(parts[4])
        route["dedup"] = dd.to_dict()
        result = await runtime.patch_module_config("channel_forward", {"routes": routes})
        await progress.success(result)
        return True

    if action == "dryrun":
        cfg = runtime.modules_config.setdefault("channel_forward", {})
        if len(parts) >= 3 and parts[2].lower() in {"on", "off"}:
            cfg["dry_run"] = parts[2].lower() == "on"
        else:
            cfg["dry_run"] = not bool(cfg.get("dry_run"))
        result = await runtime.patch_module_config("channel_forward", {"dry_run": cfg["dry_run"]})
        await progress.success(f"dry_run={cfg['dry_run']}\n{result}")
        return True

    if action == "delivery" and len(parts) >= 4:
        source = parts[2].strip()
        route = find_route(source, need_edit=True)
        if route is None:
            await progress.fail("مسیر پیدا نشد.")
            return True
        dlv = DeliveryConfig.from_dict(route.get("delivery"))
        key = parts[3].lower()
        if key == "pin" and len(parts) >= 5:
            dlv.pin_latest = parts[4].lower() == "on"
        elif key == "button" and len(parts) >= 6:
            dlv.button_text = parts[4]
            dlv.button_url = parts[5]
        elif key == "sync" and len(parts) >= 5:
            dlv.sync_edits = parts[4].lower() == "on"
            if len(parts) >= 6:
                dlv.sync_deletes = parts[5].lower() == "on"
        else:
            await progress.fail("delivery: pin|button|sync")
            return True
        route["delivery"] = dlv.to_dict()
        result = await runtime.patch_module_config("channel_forward", {"routes": routes})
        await progress.success(result)
        return True

    if action == "allow" and len(parts) >= 4:
        source = parts[2].strip()
        route = find_route(source, need_edit=True)
        if route is None:
            await progress.fail("مسیر پیدا نشد.")
            return True
        flt = TextFilterConfig.from_dict(route.get("filter"))
        sub = parts[3].lower()
        if sub in {"on", "off"}:
            flt.allow_enabled = sub == "on"
        elif sub == "add":
            word = unescape_admin_text(" ".join(parts[4:]).strip())
            if word and word not in flt.allow_words:
                flt.allow_words.append(word)
            flt.allow_enabled = True
        elif sub == "clear":
            flt.allow_words = []
        route["filter"] = flt.to_dict()
        result = await runtime.patch_module_config("channel_forward", {"routes": routes})
        await progress.success(result)
        return True

    if action == "regex" and len(parts) >= 4:
        source = parts[2].strip()
        route = find_route(source, need_edit=True)
        if route is None:
            await progress.fail("مسیر پیدا نشد.")
            return True
        flt = TextFilterConfig.from_dict(route.get("filter"))
        sub = parts[3].lower()
        if sub in {"on", "off"}:
            flt.regex_enabled = sub == "on"
        elif sub == "set":
            flt.regex_pattern = unescape_admin_text(" ".join(parts[4:]).strip())
            flt.regex_enabled = True
        route["filter"] = flt.to_dict()
        result = await runtime.patch_module_config("channel_forward", {"routes": routes})
        await progress.success(result)
        return True

    if action == "link" and len(parts) >= 6:
        source = parts[2].strip()
        route = find_route(source, need_edit=True)
        if route is None:
            await progress.fail("مسیر پیدا نشد.")
            return True
        flt = TextFilterConfig.from_dict(route.get("filter"))
        src_link, dst_link = parts[4], parts[5]
        flt.link_replacements[src_link] = dst_link
        flt.enabled = True
        route["filter"] = flt.to_dict()
        result = await runtime.patch_module_config("channel_forward", {"routes": routes})
        await progress.success(result)
        return True

    if action == "import" and len(parts) >= 5:
        dest = parts[-1].strip()
        sources_raw = " ".join(parts[2:-1]).replace("،", ",")
        sources = [s.strip() for s in sources_raw.split(",") if s.strip()]
        if not sources:
            await progress.fail("`/forward import @a,@b <dest>`")
            return True
        added = 0
        for src in sources:
            exists = any(
                display_ref(r.get("source")) == display_ref(src) for r in routes
            )
            if exists:
                continue
            routes.append(
                default_route_dict(src, dest, owner_id=actor_id, visibility="private")
            )
            added += 1
        result = await runtime.patch_module_config(
            "channel_forward", {"routes": routes, "enabled": True}
        )
        await progress.success(f"{added} مسیر import شد → `{display_ref(dest)}`\n{result}")
        return True

    return False
