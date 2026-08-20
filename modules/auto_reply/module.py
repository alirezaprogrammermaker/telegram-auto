"""Auto-reply to private messages for unlocked admins only."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, RPCError

from telethon import Button

from app.admin_keyboard import (
    KeyboardMenu,
    is_keyboard_label,
    keyboard_command_for,
    keyboard_navigation_for,
    keyboard_rows,
    menu_prompt,
)
from app.base import BaseModule
from app.paths import ROOT, data_path
from app.progress import ProgressMessenger
from app.storage import load_json, save_json

logger = logging.getLogger(__name__)


def _parse_id_list(raw: Any) -> set[int]:
    """Accept "111,222" strings or [111, 222] lists of Telegram user ids."""
    if not raw:
        return set()
    items = raw if isinstance(raw, (list, tuple, set)) else str(raw).replace(";", ",").split(",")
    result: set[int] = set()
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        try:
            result.add(int(text))
        except ValueError:
            logger.warning("Ignoring invalid admin id %r", text)
    return result


class AutoReplyModule(BaseModule):
    name = "auto_reply"

    def __init__(self, client: TelegramClient, config: dict[str, Any]) -> None:
        super().__init__(client, config)
        self.reply_text = str(config.get("reply_text") or "سلام! پیام‌ات رسید ✓")
        raw_cooldown = config.get("cooldown_seconds", 30)
        self.cooldown = max(0.0, float(30 if raw_cooldown is None else raw_cooldown))
        self.whitelist = {
            int(x)
            for x in (config.get("whitelist") or [])
            if str(x).lstrip("-").isdigit()
        }
        self.allow_saved = bool(config.get("allow_saved_messages", True))
        self.skip_media_only = bool(config.get("skip_media_only", True))
        self.show_typing = bool(config.get("show_typing", True))
        self.typing_seconds = max(0.0, float(config.get("typing_seconds", 1.5)))

        self.admin_password = (
            os.environ.get("ADMIN_PASSWORD", "").strip()
            or str(config.get("admin_password") or "").strip()
        )
        self.require_admin = bool(config.get("require_admin", True))
        self.admin_welcome = str(
            config.get("admin_welcome")
            or "دسترسی مدیر فعال شد."
        )
        self.logout_command = str(config.get("logout_command") or "/logout").strip()
        self.logout_message = str(
            config.get("logout_message")
            or "دسترسی مدیر غیرفعال شد.\nبرای ورود دوباره فقط رمز را بفرست یا: /login"
        )
        self.delete_password_message = bool(config.get("delete_password_message", True))
        self.help_commands = {
            str(c).strip().lower()
            for c in (config.get("help_commands") or ["/help", "/commands", "دستورات", "help"])
            if str(c).strip()
        }
        self.send_help_on_login = bool(config.get("send_help_on_login", True))

        state_name = str(config.get("admins_file") or "admins.json")
        # Always keep admins under the account data dir unless absolute path given.
        admins_path = Path(state_name)
        if admins_path.is_absolute():
            self.admins_path = admins_path
        elif state_name.replace("\\", "/").startswith("data/"):
            self.admins_path = data_path(Path(state_name).name)
        else:
            self.admins_path = data_path(state_name)

        # CI runners start with an empty data/ dir, so seed trusted admins
        # from the environment instead of forcing a re-login every restart.
        self.seed_admins = _parse_id_list(os.environ.get("ADMIN_IDS", "")) | _parse_id_list(
            config.get("admin_ids")
        )

        self._admins: set[int] = set()
        self._me_id: int | None = None
        self._last_reply_at: dict[int, float] = {}
        self._event_builder: events.NewMessage | None = None
        self._known_bot_texts = {
            self.reply_text,
            self.admin_welcome,
            self.logout_message,
            menu_prompt("main"),
            menu_prompt("cfai"),
        }

    def _runtime(self):
        return getattr(self.client, "app_runtime", None)

    def _command_catalog(self) -> list[tuple[str, str]]:
        """Admin-facing commands. Extend here as features grow."""
        help_aliases = " / ".join(sorted(self.help_commands))
        return [
            (help_aliases, "لیست دستورات مدیر"),
            ("/modules", "وضعیت ماژول‌ها و راهنمای مدیریت"),
            ("/module on|off|reload <name>", "روشن/خاموش/ری‌لود ماژول"),
            ("/forward status", "مسیرهای قابل‌مشاهده برای تو (خصوصی دیگران مخفی)"),
            ("/forward mine", "فقط مسیرهایی که مال خودت است"),
            ("/forward add <source> <dest>", "افزودن مسیر خصوصی برای خودت"),
            ("/forward remove <source>", "حذف مسیر بر اساس مبدأ"),
            ("/forward set <source> <dest>", "تغییر مقصد یک مبدأ"),
            ("/forward mode <source> copy|forward", "حالت ارسال همان مسیر"),
            ("/forward visibility <source> public|private", "عمومی/خصوصی کردن مسیر"),
            ("/forward claim <source>", "مالک شدن مسیر بدون owner"),
            ("/forward filter <source>", "وضعیت فیلتر متن مسیر"),
            ("/forward filter <source> on|off", "روشن/خاموش کردن فیلتر"),
            ("/stats", "آمار امروز فوروارد/بلاک/صف"),
            ("/forward schedule <source>", "وضعیت زمان‌بندی مسیر"),
            ("/forward schedule <source> on|off", "روشن/خاموش زمان‌بندی"),
            ("/forward schedule <source> tz Asia/Tehran", "منطقه زمانی"),
            ("/forward schedule <source> days sat,sun,mon", "روزهای مجاز"),
            ("/forward schedule <source> hours 09:00-12:00,18:00-22:00", "بازه ساعت"),
            ("/forward filter <source> block on|off", "بلاک‌لیست کلمات"),
            ("/forward filter <source> block add|remove <کلمه>", "مدیریت کلمات بلاک"),
            ("/forward filter <source> links|لینک on|off", "حذف لینک‌ها"),
            ("/forward filter <source> mentions|منشن on|off", "حذف منشن‌ها (@ و منشن مخفی)"),
            ("/forward filter <source> hashtags|هشتگ on|off", "حذف هشتگ‌ها"),
            ("/forward filter <source> ids|آیدی on|off", "حذف آیدی عددی"),
            ("/forward filter <source> prefix|suffix <text|off>", "متن اول/آخر (\\n برای خط جدید)"),
            ("/forward queue [clear]", "وضعیت یا پاک کردن صف pending"),
            ("/forward pause|resume <source>", "توقف/ادامه موقت مسیر"),
            ("/forward dest add|remove <source> <dest>", "چند مقصد برای یک مبدأ"),
            ("/forward media <source> on|allow photo,video", "فیلتر نوع رسانه"),
            ("/forward dedup <source> on|off [hours]", "حذف پست تکراری"),
            ("/forward allow <source> on|add|clear", "فقط اگر کلمه خاص بود"),
            ("/forward regex <source> on|set <pattern>", "فیلتر regex"),
            ("/forward delivery <source> pin|button|sync ...", "پین، دکمه، همگام ادیت/حذف"),
            ("/forward dryrun [on|off]", "حالت تست بدون ارسال واقعی"),
            ("/forward link <source> set <from> <to>", "جایگزینی لینک در کپشن"),
            ("/forward import @a,@b <dest>", "افزودن چند مبدأ یکجا"),
            ("/config reply <text>", "تغییر متن پاسخ خودکار"),
            ("/config whitelist add|remove <id>", "لیست سفید پیام"),
            ("/digest", "خلاصه روزانه فوری"),
            ("/promo status|help", "وضعیت پخش تبلیغات (چند مسیر)"),
            ("/promo add @channel @g1,@g2", "مسیر کانال→گروه‌ها"),
            ("/promo remove @channel", "حذف یک مسیر"),
            ("/promo group add|remove @channel @group", "گروه یک مسیر"),
            ("/promo dryrun|pause|resume|queue", "ایمنی و صف پخش"),
            ("/promo safety delay|budget|windows", "تنظیم فاصله/سقف/بازه"),
            ("/harvest status|add|remove", "جمع‌آوری لینک از لینکدونی (collector)"),
            ("/inspect status|dryrun|budget", "بازرسی آهسته گروه (inspector)"),
            ("/pool status|list|approve|to-promo", "استخر مشترک کشف گروه"),
            ("/cfai status|accounts|test|model", "مدیریت Cloudflare Workers AI"),
            (self.logout_command, "خروج از حالت مدیر"),
            ("/login", "راهنمای ورود دوباره"),
            ("/login <رمز>", "ورود مدیر با رمز"),
            ("<کلمه رمز>", "فعال‌سازی دسترسی مدیر"),
        ]

    def _build_help_text(self) -> str:
        lines = [
            "📋 دستورات مدیر",
            "────────────",
        ]
        for command, description in self._command_catalog():
            lines.append(f"• `{command}`")
            lines.append(f"  {description}")
        lines.extend(
            [
                "────────────",
                "ماژول جدید فقط اگر در کد رجیستر شده باشد قابل روشن‌شدن است.",
                f"وضعیت فعلی: {len(self._admins)} مدیر فعال",
            ]
        )
        return "\n".join(lines)

    async def _handle_module_command(self, text: str) -> str | None:
        runtime = self._runtime()
        if runtime is None:
            return "سیستم مدیریت ماژول در دسترس نیست."

        parts = text.split()
        cmd = parts[0].split("@", 1)[0].lower()

        if cmd in {"/modules", "/module"} and len(parts) == 1:
            return runtime.format_status_text()

        if cmd == "/module" and len(parts) >= 2:
            action = parts[1].lower()
            if action in {"on", "off", "reload"} and len(parts) < 3:
                return "فرمت: `/module on|off|reload <name>`"
            name = parts[2].strip() if len(parts) >= 3 else ""
            if action == "on":
                return await runtime.set_enabled(name, True)
            if action == "off":
                return await runtime.set_enabled(name, False)
            if action == "reload":
                return await runtime.reload_module(name)
            if action == "list":
                return runtime.format_status_text()
            return "اکشن نامعتبر. استفاده: `/module on|off|reload <name>`"

        if cmd == "/forward":
            # Handled with ProgressMessenger by caller
            return "__FORWARD_PROGRESS__"

        if cmd == "/config":
            return "__CONFIG_PROGRESS__"

        if cmd == "/digest":
            return "__DIGEST_PROGRESS__"

        if cmd == "/promo":
            return "__PROMO_PROGRESS__"

        if cmd in {"/harvest", "/inspect", "/pool"}:
            return "__POOL_PROGRESS__"

        if cmd == "/cfai":
            return "__CFAI_PROGRESS__"

        return None

    async def _handle_forward_command(
        self,
        parts: list[str],
        progress: ProgressMessenger,
        actor_id: int,
    ) -> None:
        runtime = self._runtime()
        if runtime is None:
            await progress.fail("سیستم مدیریت ماژول در دسترس نیست.")
            return

        from modules.channel_forward.access import (
            can_edit_route,
            can_view_route,
            normalize_visibility,
            visibility_label,
        )
        from modules.channel_forward.module import (
            display_ref,
            ensure_can_post,
            ensure_joined,
            migrate_routes,
        )

        from modules.channel_forward.route_config import default_route_dict

        cfg = runtime.modules_config.setdefault("channel_forward", {})
        if not isinstance(cfg, dict):
            cfg = {}
            runtime.modules_config["channel_forward"] = cfg

        routes = migrate_routes(cfg)
        cfg["routes"] = routes
        cfg.pop("sources", None)
        cfg.pop("destination", None)

        def _visible_routes() -> list[dict]:
            return [r for r in routes if can_view_route(r, actor_id)]

        def _find_route(source: str, *, need_edit: bool = False) -> dict | None:
            for route in routes:
                if not (
                    str(route.get("source")) == source
                    or display_ref(route.get("source")) == display_ref(source)
                ):
                    continue
                if need_edit and not can_edit_route(route, actor_id):
                    return None
                if not need_edit and not can_view_route(route, actor_id):
                    return None
                return route
            return None

        if len(parts) == 1 or parts[1].lower() in {"status", "check", "mine"}:
            only_mine = len(parts) > 1 and parts[1].lower() == "mine"
            await progress.set_title("📡 مسیرهای قابل‌مشاهده برای تو")
            running = "channel_forward" in runtime.loaded
            enabled = bool(cfg.get("enabled"))
            await progress.step(
                f"ماژول: {'ON' if enabled else 'OFF'} / "
                f"{'running' if running else 'stopped'}"
            )
            shown = _visible_routes()
            if only_mine:
                shown = [
                    r
                    for r in shown
                    if r.get("owner_id") is not None and int(r["owner_id"]) == actor_id
                ]
            if not shown:
                await progress.success(
                    "مسیری برای نمایش نیست.\n"
                    "مسیرهای خصوصی دیگران دیده نمی‌شوند مگر public باشند."
                )
                return

            do_check = len(parts) > 1 and parts[1].lower() in {"status", "check"}
            for i, route in enumerate(shown, start=1):
                src = display_ref(route["source"])
                from modules.channel_forward.route_config import route_destinations

                dests = [display_ref(d) for d in route_destinations(route)]
                dest_label = " → ".join(dests) if dests else "(no dest)"
                paused = " ⏸" if route.get("paused") else ""
                await progress.step(
                    f"{i}) `{src}` → `{dest_label}` [{visibility_label(route)}]{paused}"
                )
                if do_check:
                    try:
                        await ensure_joined(
                            self.client, route["source"], progress, label="مبدأ"
                        )
                        _, reason = await ensure_can_post(
                            self.client, route["destination"], progress, auto_join=True
                        )
                        await progress.step(f"نتیجه: آماده ({reason})")
                    except Exception as exc:
                        await progress.step(f"خطا: {exc}")

            await progress.success(
                "تمام.\n"
                "`/forward visibility <source> public|private`\n"
                "`/forward mine` فقط مسیرهای خودت"
            )
            return

        action = parts[1].lower()

        if action == "add" and len(parts) >= 4:
            source, dest = parts[2].strip(), parts[3].strip()
            await progress.set_title(
                f"⏳ افزودن مسیر `{display_ref(source)}` → `{display_ref(dest)}`"
            )
            for route in routes:
                if str(route.get("source")) == source or display_ref(
                    route.get("source")
                ) == display_ref(source):
                    if can_view_route(route, actor_id):
                        await progress.fail(
                            f"مبدأ از قبل مسیر دارد → `{display_ref(route.get('destination'))}`.\n"
                            f"برای تغییر: `/forward set {source} {dest}`"
                        )
                    else:
                        await progress.fail(
                            "این مبدأ توسط مدیر دیگری به‌صورت خصوصی ثبت شده است."
                        )
                    return
            try:
                await ensure_joined(self.client, source, progress, label="مبدأ")
                _, reason = await ensure_can_post(
                    self.client, dest, progress, auto_join=True
                )
            except ValueError as exc:
                await progress.fail(str(exc))
                return

            await progress.step("ذخیره مسیر خصوصی برای تو")
            routes.append(default_route_dict(source, dest, owner_id=actor_id, visibility="private"))
            result = await runtime.patch_module_config(
                "channel_forward",
                {"routes": routes, "enabled": True},
            )
            await progress.success(
                f"مسیر خصوصی اضافه شد ({reason}).\n"
                f"برای عمومی کردن: `/forward visibility {source} public`\n{result}"
            )
            return

        if action == "visibility" and len(parts) >= 4:
            source, vis_raw = parts[2].strip(), parts[3].strip()
            route = _find_route(source, need_edit=True)
            if route is None:
                await progress.fail("مسیر پیدا نشد یا اجازه ویرایش نداری.")
                return
            vis = normalize_visibility(vis_raw)
            route["visibility"] = vis
            if route.get("owner_id") is None:
                route["owner_id"] = actor_id
            result = await runtime.patch_module_config(
                "channel_forward",
                {"routes": routes},
            )
            await progress.success(f"visibility=`{vis}`\n{result}")
            return

        if action == "claim" and len(parts) >= 3:
            source = parts[2].strip()
            route = None
            for item in routes:
                if str(item.get("source")) == source or display_ref(
                    item.get("source")
                ) == display_ref(source):
                    route = item
                    break
            if route is None:
                await progress.fail("مسیر پیدا نشد.")
                return
            if route.get("owner_id") not in (None, ""):
                if int(route["owner_id"]) == actor_id:
                    await progress.success("از قبل مال خودت است.")
                else:
                    await progress.fail("این مسیر مالک دیگری دارد.")
                return
            route["owner_id"] = actor_id
            route["visibility"] = normalize_visibility(
                route.get("visibility") or "private"
            )
            result = await runtime.patch_module_config(
                "channel_forward",
                {"routes": routes},
            )
            await progress.success(
                f"مالکیت ثبت شد (visibility={route['visibility']}).\n{result}"
            )
            return

        if action == "remove" and len(parts) >= 3:
            source = parts[2].strip()
            await progress.set_title(f"⏳ حذف مسیر مبدأ `{display_ref(source)}`")
            route = _find_route(source, need_edit=True)
            if route is None:
                exists = any(
                    str(r.get("source")) == source
                    or display_ref(r.get("source")) == display_ref(source)
                    for r in routes
                )
                if exists:
                    await progress.fail("اجازه حذف این مسیر را نداری.")
                else:
                    await progress.fail(
                        f"مسیری با مبدأ `{display_ref(source)}` پیدا نشد."
                    )
                return
            new_routes = [r for r in routes if r is not route]
            await progress.step("به‌روزرسانی کانفیگ و ری‌لود ماژول")
            result = await runtime.patch_module_config(
                "channel_forward",
                {"routes": new_routes},
            )
            await progress.success(result)
            return

        if action == "set" and len(parts) >= 4:
            source, dest = parts[2].strip(), parts[3].strip()
            await progress.set_title(
                f"⏳ تغییر مقصد `{display_ref(source)}` → `{display_ref(dest)}`"
            )
            route = _find_route(source, need_edit=True)
            if route is None:
                await progress.fail("مسیر پیدا نشد یا اجازه ویرایش نداری.")
                return
            try:
                await ensure_joined(self.client, source, progress, label="مبدأ")
                _, reason = await ensure_can_post(
                    self.client, dest, progress, auto_join=True
                )
            except ValueError as exc:
                await progress.fail(str(exc))
                return
            route["destination"] = dest
            await progress.step("ذخیره و ری‌لود")
            result = await runtime.patch_module_config(
                "channel_forward",
                {"routes": routes},
            )
            await progress.success(f"مقصد عوض شد ({reason}).\n{result}")
            return

        if action == "mode" and len(parts) >= 4:
            source, mode = parts[2].strip(), parts[3].strip().lower()
            await progress.set_title(f"⏳ تغییر mode مسیر `{display_ref(source)}`")
            if mode not in {"copy", "forward"}:
                await progress.fail("mode باید `copy` یا `forward` باشد.")
                return
            route = _find_route(source, need_edit=True)
            if route is None:
                await progress.fail("مسیر پیدا نشد یا اجازه ویرایش نداری.")
                return
            route["forward_mode"] = mode
            result = await runtime.patch_module_config(
                "channel_forward",
                {"routes": routes},
            )
            await progress.success(result)
            return

        if action == "filter":
            await self._handle_forward_filter(
                parts, routes, runtime, progress, actor_id=actor_id
            )
            return

        if action == "schedule":
            await self._handle_forward_schedule(
                parts, routes, runtime, progress, actor_id=actor_id
            )
            return

        from modules.channel_forward.admin_commands import handle_forward_extended

        handled = await handle_forward_extended(
            action,
            parts,
            routes=routes,
            runtime=runtime,
            progress=progress,
            actor_id=actor_id,
            find_route=lambda src, need_edit=False: _find_route(src, need_edit=need_edit),
            can_edit=lambda r: can_edit_route(r, actor_id),
        )
        if handled:
            return

        await progress.fail(
            "فرمت‌ها:\n"
            "`/forward status` | `/forward mine`\n"
            "`/forward add <source> <dest>`\n"
            "`/forward visibility <source> public|private`\n"
            "`/forward claim <source>`\n"
            "`/forward schedule <source> ...`\n"
            "`/forward filter <source> ...`"
        )

    async def _handle_promo_command(
        self,
        parts: list[str],
        progress: ProgressMessenger,
    ) -> None:
        runtime = self._runtime()
        if runtime is None:
            await progress.fail("runtime unavailable")
            return
        from modules.promo_spread.admin_commands import handle_promo_command
        from modules.promo_spread.queue import PromoQueue
        from modules.promo_spread.safety import SafetyConfig, SafetyGuard

        cfg = runtime.modules_config.setdefault("promo_spread", {})
        if not isinstance(cfg, dict):
            cfg = {}
            runtime.modules_config["promo_spread"] = cfg
        guard = SafetyGuard(SafetyConfig.from_dict(cfg.get("safety")))
        await handle_promo_command(
            parts,
            cfg=cfg,
            runtime=runtime,
            progress=progress,
            safety_summary=guard.summary_lines(),
            queue_pending=PromoQueue().pending_count(),
        )

    async def _handle_pool_family_command(
        self,
        parts: list[str],
        progress: ProgressMessenger,
    ) -> None:
        runtime = self._runtime()
        if runtime is None:
            await progress.fail("runtime unavailable")
            return
        from modules.group_pool.admin_commands import (
            handle_harvest_command,
            handle_inspect_command,
            handle_pool_command,
        )

        cmd = (parts[0] if parts else "").lower()
        if cmd == "/harvest":
            cfg = runtime.modules_config.setdefault("link_harvest", {})
            if not isinstance(cfg, dict):
                cfg = {}
                runtime.modules_config["link_harvest"] = cfg
            await handle_harvest_command(parts, cfg=cfg, runtime=runtime, progress=progress)
            return
        if cmd == "/inspect":
            cfg = runtime.modules_config.setdefault("group_inspect", {})
            if not isinstance(cfg, dict):
                cfg = {}
                runtime.modules_config["group_inspect"] = cfg
            await handle_inspect_command(parts, cfg=cfg, runtime=runtime, progress=progress)
            return
        await handle_pool_command(parts, runtime=runtime, progress=progress)

    async def _handle_cfai_command(
        self,
        parts: list[str],
        progress: ProgressMessenger,
    ) -> None:
        from app.cloudflare_ai.admin_commands import handle_cfai_command

        await handle_cfai_command(parts, progress=progress)

    async def _handle_config_command(
        self,
        parts: list[str],
        progress: ProgressMessenger,
        *,
        runtime,
    ) -> None:
        if runtime is None:
            await progress.fail("runtime unavailable")
            return
        if len(parts) < 2:
            await progress.fail("`/config reply <text>` | `/config whitelist add <id>`")
            return
        key = parts[1].lower()
        cfg = runtime.modules_config.setdefault("auto_reply", {})

        if key == "reply" and len(parts) >= 3:
            text = " ".join(parts[2:]).strip()
            cfg["reply_text"] = text
            self.reply_text = text
            result = await runtime.patch_module_config("auto_reply", {"reply_text": text}, reload=False)
            await progress.success(f"reply_text updated.\n{result}")
            return

        if key == "whitelist" and len(parts) >= 4:
            sub = parts[2].lower()
            try:
                uid = int(parts[3].strip())
            except ValueError:
                await progress.fail("id عددی بده")
                return
            wl = set(int(x) for x in (cfg.get("whitelist") or []) if str(x).lstrip("-").isdigit())
            if sub == "add":
                wl.add(uid)
            elif sub == "remove":
                wl.discard(uid)
            else:
                await progress.fail("add|remove")
                return
            cfg["whitelist"] = sorted(wl)
            self.whitelist = wl
            result = await runtime.patch_module_config(
                "auto_reply", {"whitelist": cfg["whitelist"]}, reload=False
            )
            await progress.success(f"whitelist={cfg['whitelist']}\n{result}")
            return

        await progress.fail("`/config reply ...` | `/config whitelist add|remove <id>`")

    async def _handle_forward_schedule(
        self,
        parts: list[str],
        routes: list,
        runtime,
        progress: ProgressMessenger,
        actor_id: int,
    ) -> None:
        from modules.channel_forward.access import can_edit_route, can_view_route
        from modules.channel_forward.module import display_ref
        from modules.channel_forward.schedule import (
            ScheduleConfig,
            parse_days_csv,
            parse_windows_csv,
        )

        if len(parts) < 3:
            await progress.fail(
                "فرمت:\n"
                "`/forward schedule <source>`\n"
                "`/forward schedule <source> on|off`\n"
                "`/forward schedule <source> tz Asia/Tehran`\n"
                "`/forward schedule <source> days sat,sun,mon`\n"
                "`/forward schedule <source> hours 09:00-12:00,18:00-22:00`"
            )
            return

        source = parts[2].strip()
        route = None
        for item in routes:
            if str(item.get("source")) == source or display_ref(
                item.get("source")
            ) == display_ref(source):
                route = item
                break
        if route is None or not can_view_route(route, actor_id):
            await progress.fail(f"مبدأ `{display_ref(source)}` پیدا نشد.")
            return
        if len(parts) > 3 and not can_edit_route(route, actor_id):
            await progress.fail("اجازه ویرایش این مسیر را نداری.")
            return

        sched = ScheduleConfig.from_dict(route.get("schedule"))
        await progress.set_title(f"🗓 زمان‌بندی `{display_ref(source)}`")

        if len(parts) == 3:
            for line in sched.summary_lines():
                await progress.step(line)
            await progress.success(
                "خارج از بازه، پست‌ها صف می‌شوند و سر ساعت مجاز منتشر می‌گردند."
            )
            return

        key = parts[3].strip().lower()

        async def _save(msg: str) -> None:
            route["schedule"] = sched.to_dict()
            await progress.step("ذخیره و ری‌لود")
            result = await runtime.patch_module_config(
                "channel_forward",
                {"routes": routes},
            )
            await progress.success(f"{msg}\n{result}")

        if key in {"on", "off"}:
            if key == "on" and not sched.windows:
                await progress.fail(
                    "اول بازه ساعت بده:\n"
                    f"`/forward schedule {source} hours 09:00-22:00`"
                )
                return
            sched.enabled = key == "on"
            await progress.step(f"schedule.enabled = {sched.enabled}")
            await _save("زمان‌بندی به‌روز شد.")
            return

        if key in {"tz", "timezone"} and len(parts) >= 5:
            tz = parts[4].strip()
            try:
                from zoneinfo import ZoneInfo

                ZoneInfo(tz)
            except Exception:
                await progress.fail(f"timezone نامعتبر: `{tz}`")
                return
            sched.timezone = tz
            await progress.step(f"timezone = {tz}")
            await _save("منطقه زمانی ذخیره شد.")
            return

        if key == "days" and len(parts) >= 5:
            try:
                sched.days = parse_days_csv(" ".join(parts[4:]))
            except ValueError as exc:
                await progress.fail(str(exc))
                return
            await progress.step(f"days = {', '.join(sched.days)}")
            await _save("روزها ذخیره شد.")
            return

        if key in {"hours", "windows"} and len(parts) >= 5:
            try:
                sched.windows = parse_windows_csv("".join(parts[4:]))
            except ValueError as exc:
                await progress.fail(str(exc))
                return
            await progress.step(
                "windows = " + ", ".join(f"{w.start}-{w.end}" for w in sched.windows)
            )
            await _save("بازه ساعت ذخیره شد.")
            return

        if key == "clear":
            sched = ScheduleConfig()
            await progress.step("زمان‌بندی ریست شد")
            await _save("پاک شد.")
            return

        await progress.fail("دستور schedule نامعتبر است. `/forward schedule <source>`")

    async def _handle_forward_filter(
        self,
        parts: list[str],
        routes: list,
        runtime,
        progress: ProgressMessenger,
        actor_id: int,
    ) -> None:
        from modules.channel_forward.access import can_edit_route, can_view_route
        from modules.channel_forward.filters import TextFilterConfig, unescape_admin_text
        from modules.channel_forward.module import display_ref

        if len(parts) < 3:
            await progress.fail(
                "فرمت:\n"
                "`/forward filter <source>`\n"
                "`/forward filter <source> on|off`\n"
                "`/forward filter <source> links|mentions|hashtags|ids on|off`\n"
                "`/forward filter <source> prefix|suffix <متن|off>`"
            )
            return

        source = parts[2].strip()
        route = None
        for item in routes:
            if str(item.get("source")) == source or display_ref(
                item.get("source")
            ) == display_ref(source):
                route = item
                break
        if route is None or not can_view_route(route, actor_id):
            await progress.fail(f"مبدأ `{display_ref(source)}` پیدا نشد.")
            return
        if len(parts) > 3 and not can_edit_route(route, actor_id):
            await progress.fail("اجازه ویرایش این مسیر را نداری.")
            return

        filt = TextFilterConfig.from_dict(route.get("filter"))
        await progress.set_title(f"🛠 فیلتر مسیر `{display_ref(source)}`")

        # /forward filter <source>
        if len(parts) == 3:
            await progress.step("خواندن تنظیمات فیلتر")
            for line in filt.summary_lines():
                await progress.step(line)
            note = (
                "فیلتر فقط روی حالت copy اثر دارد؛ اگر روشن باشد "
                "حتی در mode=forward هم به‌صورت copy+فیلتر ارسال می‌شود."
            )
            await progress.success(note)
            return

        key = parts[3].strip().lower()

        async def _save(message: str) -> None:
            route["filter"] = filt.to_dict()
            # Filtering requires editable text → prefer copy
            if filt.enabled and route.get("forward_mode") == "forward":
                route["forward_mode"] = "copy"
                await progress.step("mode به‌خاطر فیلتر روی copy تنظیم شد")
            await progress.step("ذخیره و ری‌لود ماژول")
            result = await runtime.patch_module_config(
                "channel_forward",
                {"routes": routes},
            )
            await progress.success(f"{message}\n{result}")

        if key in {"on", "off", "enable", "disable"}:
            filt.enabled = key in {"on", "enable"}
            await progress.step(f"filter.enabled = {filt.enabled}")
            await _save("فیلتر به‌روز شد.")
            return

        if key in {"block", "بلاک", "blocklist"}:
            if len(parts) == 4:
                await progress.step(f"block_enabled={filt.block_enabled}")
                await progress.step(
                    "words=" + (", ".join(filt.block_words) if filt.block_words else "(خالی)")
                )
                await progress.success("برای افزودن: `/forward filter <source> block add کلمه`")
                return
            sub = parts[4].strip().lower()
            if sub in {"on", "off"}:
                filt.block_enabled = sub == "on"
                await progress.step(f"block_enabled = {filt.block_enabled}")
                await _save("بلاک‌لیست به‌روز شد.")
                return
            if sub in {"add", "remove", "rm", "del"} and len(parts) >= 6:
                word = " ".join(parts[5:]).strip()
                if not word:
                    await progress.fail("کلمه خالی است.")
                    return
                words = list(filt.block_words)
                if sub == "add":
                    if word not in words:
                        words.append(word)
                    filt.block_enabled = True
                    await progress.step(f"added: {word}")
                else:
                    words = [w for w in words if w.casefold() != word.casefold()]
                    await progress.step(f"removed: {word}")
                filt.block_words = words
                await _save("لیست کلمات ذخیره شد.")
                return
            if sub == "clear":
                filt.block_words = []
                filt.block_enabled = False
                await progress.step("block list cleared")
                await _save("بلاک‌لیست پاک شد.")
                return
            await progress.fail(
                f"فرمت: `/forward filter {source} block on|off|add|remove|clear`"
            )
            return

        bool_keys = {
            "links": "remove_links",
            "link": "remove_links",
            "لینک": "remove_links",
            "لینکها": "remove_links",
            "mentions": "remove_mentions",
            "mention": "remove_mentions",
            "منشن": "remove_mentions",
            "منشنها": "remove_mentions",
            "hashtags": "remove_hashtags",
            "hashtag": "remove_hashtags",
            "هشتگ": "remove_hashtags",
            "هشتگها": "remove_hashtags",
            "ids": "remove_ids",
            "id": "remove_ids",
            "آیدی": "remove_ids",
            "ایدی": "remove_ids",
            "collapse": "collapse_whitespace",
        }
        if key in bool_keys:
            if len(parts) < 5 or parts[4].lower() not in {"on", "off"}:
                await progress.fail(f"فرمت: `/forward filter {source} {key} on|off`")
                return
            value = parts[4].lower() == "on"
            setattr(filt, bool_keys[key], value)
            if value:
                filt.enabled = True
            await progress.step(f"{bool_keys[key]} = {value}")
            await _save("تنظیم فیلتر ذخیره شد.")
            return

        if key in {"prefix", "suffix"}:
            if len(parts) < 5:
                await progress.fail(
                    f"فرمت: `/forward filter {source} {key} متن` یا `{key} off`"
                )
                return
            raw = " ".join(parts[4:]).strip()
            if raw.lower() in {"off", "clear", "-", "none"}:
                setattr(filt, key, "")
                await progress.step(f"{key} پاک شد")
            else:
                setattr(filt, key, unescape_admin_text(raw))
                filt.enabled = True
                await progress.step(f"{key} تنظیم شد")
            await _save("متن ثابت ذخیره شد.")
            return

        if key == "clear":
            filt = TextFilterConfig()
            await progress.step("همه تنظیمات فیلتر ریست شد")
            await _save("فیلتر پاک شد.")
            return

        await progress.fail(
            "کلید نامعتبر. مثال‌ها:\n"
            f"`/forward filter {source}`\n"
            f"`/forward filter {source} on`\n"
            f"`/forward filter {source} links on`\n"
            f"`/forward filter {source} hashtags on`\n"
            f"`/forward filter {source} prefix کانال ما\\n`\n"
            f"`/forward filter {source} suffix off`"
        )

    async def start(self) -> None:
        if self.require_admin and not self.admin_password:
            raise ValueError(
                "auto_reply.require_admin=true but ADMIN_PASSWORD / admin_password is empty"
            )

        me = await self.client.get_me()
        self._me_id = me.id
        self._admins = self._load_admins()

        def _is_private(event: events.NewMessage.Event) -> bool:
            return bool(event.is_private)

        self._event_builder = events.NewMessage(func=_is_private)
        self.client.add_event_handler(self._on_message, self._event_builder)
        logger.info(
            "auto_reply ready (cooldown=%ss, require_admin=%s, admins=%s)",
            self.cooldown,
            self.require_admin,
            len(self._admins),
        )

    async def stop(self) -> None:
        if self._event_builder is not None:
            self.client.remove_event_handler(self._on_message, self._event_builder)
            self._event_builder = None
        self._save_admins()

    def _load_admins(self) -> set[int]:
        data = load_json(self.admins_path, {"admin_ids": []})
        ids = data.get("admin_ids") if isinstance(data, dict) else []
        result: set[int] = set()
        if isinstance(ids, list):
            for item in ids:
                try:
                    result.add(int(item))
                except (TypeError, ValueError):
                    continue
        return result | self.seed_admins

    def _save_admins(self) -> None:
        save_json(self.admins_path, {"admin_ids": sorted(self._admins)})

    def _is_admin(self, user_id: int) -> bool:
        if not self.require_admin:
            return True
        return user_id in self._admins

    @staticmethod
    def _normalize_secret(value: str) -> str:
        text = value or ""
        for ch in ("\u200c", "\u200e", "\u200f", "\ufeff", "\xa0"):
            text = text.replace(ch, "")
        return text.strip()

    def _password_matches(self, text: str) -> bool:
        if not self.admin_password:
            return False
        got = self._normalize_secret(text)
        expected = self._normalize_secret(self.admin_password)
        if not got or not expected:
            return False
        return got == expected

    def _admin_keyboard_markup(self, menu: str):
        return self.client.build_reply_markup(keyboard_rows(menu))

    async def _show_admin_keyboard(
        self,
        event: events.NewMessage.Event,
        menu: KeyboardMenu,
        *,
        prefix: str | None = None,
    ) -> None:
        text = menu_prompt(menu)
        if prefix:
            text = f"{prefix}\n\n{text}"
        markup = self._admin_keyboard_markup(menu)
        chat_id = event.chat_id
        if chat_id is None:
            return
        await self.client.send_message(chat_id, text, buttons=markup)

    async def _grant_admin(self, event: events.NewMessage.Event, peer_key: int) -> None:
        self._admins.add(peer_key)
        self._save_admins()
        welcome = self.admin_welcome
        if self.send_help_on_login:
            welcome = f"{self.admin_welcome}\n\n{self._build_help_text()}"
        # Send first, then delete password message (respond-after-delete is unreliable)
        chat_id = event.chat_id
        if chat_id is not None:
            await self.client.send_message(
                chat_id,
                welcome,
                buttons=self._admin_keyboard_markup("main"),
            )
        if self.delete_password_message and not event.out:
            try:
                await event.delete()
            except Exception:
                logger.debug("Could not delete password message", exc_info=True)
        logger.info("admin unlocked user_id=%s", peer_key)

    async def _on_message(self, event: events.NewMessage.Event) -> None:
        try:
            await self._handle(event)
        except FloodWaitError as exc:
            logger.warning("auto_reply FloodWait %ss - sleeping", exc.seconds)
            await asyncio.sleep(exc.seconds)
        except RPCError as exc:
            logger.error("auto_reply RPC error: %s", exc)
        except Exception:
            logger.exception("auto_reply unexpected error")

    async def _resolve_peer(self, event: events.NewMessage.Event) -> int | None:
        assert self._me_id is not None
        chat_id = event.chat_id
        if chat_id is None:
            return None

        if event.out:
            if not self.allow_saved or chat_id != self._me_id:
                return None
            return self._me_id

        sender = await event.get_sender()
        if sender is None:
            return None
        if getattr(sender, "bot", False):
            return None
        sender_id = getattr(sender, "id", None)
        if sender_id is None:
            return None
        if self.whitelist and int(sender_id) not in self.whitelist:
            return None
        return int(sender_id)

    async def _send(self, event: events.NewMessage.Event, text: str) -> None:
        if not event.out:
            try:
                await self.client.send_read_acknowledge(
                    event.chat_id,
                    event.message,
                    clear_mentions=True,
                )
            except Exception:
                logger.debug("mark-as-seen failed", exc_info=True)

        chat_id = event.chat_id
        if self.show_typing and chat_id is not None:
            async with self.client.action(chat_id, "typing"):
                if self.typing_seconds > 0:
                    await asyncio.sleep(self.typing_seconds)
                await event.respond(text)
        else:
            await event.respond(text)

    def _normalize_command(self, text: str) -> str:
        # "/help@BotName" -> "/help"
        primary = text.split()[0] if text else ""
        return primary.split("@", 1)[0].strip().lower()

    async def _handle(self, event: events.NewMessage.Event) -> None:
        assert self._me_id is not None
        text = (event.raw_text or "").strip()

        if text in self._known_bot_texts:
            return
        if text.startswith("📡") or text.startswith("⏳"):
            return
        if self.skip_media_only and not text:
            return

        peer_key = await self._resolve_peer(event)
        if peer_key is None:
            return

        # Keep in-memory set synced with disk (multi-instance safety)
        self._admins = self._load_admins()
        cmd = self._normalize_command(text)

        # /login or /login <password>
        if cmd == "/login":
            parts = text.split(maxsplit=1)
            if len(parts) == 2 and self._password_matches(parts[1]):
                await self._grant_admin(event, peer_key)
                return
            if self._is_admin(peer_key):
                await self._send(event, "قبلاً وارد شده‌ای. /help را بفرست.")
                return
            await self._send(
                event,
                "برای ورود، فقط کلمه رمز را بفرست\nیا این فرم را استفاده کن:\n`/login <رمز>`",
            )
            return

        # Unlock with password
        if self.require_admin and self._password_matches(text):
            await self._grant_admin(event, peer_key)
            return

        if cmd == "/start":
            if not self._is_admin(peer_key):
                await self._send(
                    event,
                    "ابتدا وارد شو: رمز را بفرست یا `/login`",
                )
                return
            await self._show_admin_keyboard(event, "main")
            return

        mapped_cmd = keyboard_command_for(text)
        nav_menu = keyboard_navigation_for(text)
        if mapped_cmd:
            text = mapped_cmd
            cmd = self._normalize_command(text)
        elif is_keyboard_label(text):
            if not self._is_admin(peer_key):
                await self._send(
                    event,
                    "ابتدا وارد شو: رمز را بفرست یا `/login`",
                )
                return
            if nav_menu:
                await self._show_admin_keyboard(event, nav_menu)
                return
            return

        # Help / command list — admin only
        if cmd in self.help_commands or text.strip().lower() in self.help_commands:
            if not self._is_admin(peer_key):
                await self._send(
                    event,
                    "ابتدا وارد شو: رمز را بفرست یا `/login`",
                )
                return
            chat_id = event.chat_id
            help_text = self._build_help_text()
            if chat_id is not None:
                await self.client.send_message(
                    chat_id,
                    help_text,
                    buttons=self._admin_keyboard_markup("main"),
                )
            else:
                await self._send(event, help_text)
            logger.info("help sent to user_id=%s", peer_key)
            return

        if cmd == "/stats":
            if not self._is_admin(peer_key):
                await self._send(event, "نیاز به ورود مدیر دارد. `/login`")
                return
            from app.stats import StatsStore
            from modules.channel_forward.access import can_view_route
            from modules.channel_forward.module import display_ref, migrate_routes

            visible: set[str] = set()
            runtime = self._runtime()
            if runtime is not None:
                cfg = runtime.modules_config.get("channel_forward") or {}
                if isinstance(cfg, dict):
                    for route in migrate_routes(cfg):
                        if can_view_route(route, peer_key):
                            visible.add(display_ref(route.get("source")))
                            visible.add(str(route.get("source")))

            await self._send(
                event,
                StatsStore().summary(days=2, visible_route_keys=visible),
            )
            return

        # Logout
        if self.require_admin and (
            text == self.logout_command or cmd == self.logout_command.lower()
        ):
            if peer_key in self.seed_admins:
                await self._send(
                    event,
                    "این اکانت به‌صورت ثابت در `ADMIN_IDS` مدیر است و با /logout خارج نمی‌شود.",
                )
                return
            if peer_key in self._admins:
                self._admins.discard(peer_key)
                self._save_admins()
                logout_text = (
                    self.logout_message
                    if "login" in self.logout_message.lower()
                    or "رمز" in self.logout_message
                    else (
                        f"{self.logout_message}\n"
                        "برای ورود دوباره فقط رمز را بفرست یا: /login"
                    )
                )
                chat_id = event.chat_id
                if chat_id is not None:
                    await self.client.send_message(
                        chat_id,
                        logout_text,
                        buttons=Button.clear(),
                    )
                else:
                    await self._send(event, logout_text)
                logger.info("admin logged out user_id=%s", peer_key)
            else:
                await self._send(event, "الان وارد نیستی. برای ورود: `/login`")
            return

        if not self._is_admin(peer_key):
            logger.info(
                "auto_reply ignore non-admin user_id=%s text_len=%s",
                peer_key,
                len(text),
            )
            return

        # Module management commands
        if cmd == "/forward":
            progress = ProgressMessenger(event)
            await progress.start("⏳ صبر کنید…")
            try:
                await self._handle_forward_command(text.split(), progress, peer_key)
            except Exception as exc:
                logger.exception("forward command failed")
                await progress.fail(str(exc))
            return

        if cmd == "/config":
            progress = ProgressMessenger(event)
            await progress.start("⏳ تنظیمات…")
            try:
                await self._handle_config_command(text.split(), progress, runtime=self._runtime())
            except Exception as exc:
                logger.exception("config command failed")
                await progress.fail(str(exc))
            return

        if cmd == "/digest":
            from app.stats import StatsStore
            from modules.channel_forward.queue import PublishQueue

            stats = StatsStore()
            pending = PublishQueue().pending_count()
            body = f"📰 Digest\n────────────\n{stats.summary(days=1)}\n────────────\nصف pending: {pending}"
            await self._send(event, body)
            return

        if cmd == "/promo":
            progress = ProgressMessenger(event)
            await progress.start("⏳ promo…")
            try:
                await self._handle_promo_command(text.split(), progress)
            except Exception as exc:
                logger.exception("promo command failed")
                await progress.fail(str(exc))
            return

        if cmd in {"/harvest", "/inspect", "/pool"}:
            progress = ProgressMessenger(event)
            await progress.start("⏳ …")
            try:
                await self._handle_pool_family_command(text.split(), progress)
            except Exception as exc:
                logger.exception("%s command failed", cmd)
                await progress.fail(str(exc))
            return

        if cmd == "/cfai":
            progress = ProgressMessenger(event)
            await progress.start("⏳ Cloudflare AI…")
            try:
                await self._handle_cfai_command(text.split(), progress)
            except Exception as exc:
                logger.exception("cfai command failed")
                await progress.fail(str(exc))
            return

        if cmd in {"/modules", "/module"}:
            result = await self._handle_module_command(text)
            if result and result != "__FORWARD_PROGRESS__":
                await self._send(event, result)
            return

        # Don't treat slash-commands as normal chat for default reply
        if text.startswith("/"):
            await self._send(
                event,
                "دستور ناشناخته است. برای لیست دستورات بفرست: /help",
            )
            return

        now = time.monotonic()
        last = self._last_reply_at.get(peer_key, 0.0)
        if now - last < self.cooldown:
            return

        await self._send(event, self.reply_text)
        self._last_reply_at[peer_key] = now
        logger.info("auto_reply sent → user:%s (%r)", peer_key, text[:80])
