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

from app.base import BaseModule
from app.config import ROOT
from app.progress import ProgressMessenger
from app.storage import load_json, save_json

logger = logging.getLogger(__name__)


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
            config.get("logout_message") or "دسترسی مدیر غیرفعال شد."
        )
        self.delete_password_message = bool(config.get("delete_password_message", True))
        self.help_commands = {
            str(c).strip().lower()
            for c in (config.get("help_commands") or ["/help", "/commands", "دستورات", "help"])
            if str(c).strip()
        }
        self.send_help_on_login = bool(config.get("send_help_on_login", True))

        state_name = str(config.get("admins_file") or "data/admins.json")
        self.admins_path = Path(state_name)
        if not self.admins_path.is_absolute():
            self.admins_path = ROOT / self.admins_path

        self._admins: set[int] = set()
        self._me_id: int | None = None
        self._last_reply_at: dict[int, float] = {}
        self._event_builder: events.NewMessage | None = None
        self._known_bot_texts = {
            self.reply_text,
            self.admin_welcome,
            self.logout_message,
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
            ("/forward status", "لیست مسیرها (مبدأ → مقصد)"),
            ("/forward add <source> <dest>", "افزودن مسیر جدید"),
            ("/forward remove <source>", "حذف مسیر بر اساس مبدأ"),
            ("/forward set <source> <dest>", "تغییر مقصد یک مبدأ"),
            ("/forward mode <source> copy|forward", "حالت ارسال همان مسیر"),
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
            (self.logout_command, "خروج از حالت مدیر"),
            ("<کلمه رمز>", "فعال‌سازی دسترسی مدیر (فقط یک‌بار برای ورود)"),
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

        return None

    async def _handle_forward_command(
        self,
        parts: list[str],
        progress: ProgressMessenger,
    ) -> None:
        runtime = self._runtime()
        if runtime is None:
            await progress.fail("سیستم مدیریت ماژول در دسترس نیست.")
            return

        from modules.channel_forward.module import (
            display_ref,
            ensure_can_post,
            ensure_joined,
            migrate_routes,
        )

        cfg = runtime.modules_config.setdefault("channel_forward", {})
        if not isinstance(cfg, dict):
            cfg = {}
            runtime.modules_config["channel_forward"] = cfg

        routes = migrate_routes(cfg)
        cfg["routes"] = routes
        cfg.pop("sources", None)
        cfg.pop("destination", None)

        if len(parts) == 1 or parts[1].lower() in {"status", "check"}:
            await progress.set_title("📡 بررسی مسیرهای فوروارد")
            running = "channel_forward" in runtime.loaded
            enabled = bool(cfg.get("enabled"))
            await progress.step(
                f"ماژول: {'ON' if enabled else 'OFF'} / "
                f"{'running' if running else 'stopped'}"
            )
            if not routes:
                await progress.success("هیچ مسیری تعریف نشده.")
                return

            for i, route in enumerate(routes, start=1):
                src = display_ref(route["source"])
                dest = display_ref(route["destination"])
                await progress.step(f"مسیر {i}: `{src}` → `{dest}`")
                try:
                    await ensure_joined(
                        self.client, route["source"], progress, label="مبدأ"
                    )
                    _, reason = await ensure_can_post(
                        self.client, route["destination"], progress, auto_join=True
                    )
                    await progress.step(f"نتیجه مسیر {i}: آماده ({reason})")
                except Exception as exc:
                    await progress.step(f"مسیر {i} خطا: {exc}")

            await progress.success("بررسی مسیرها تمام شد.")
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
                    await progress.fail(
                        f"مبدأ از قبل مسیر دارد → `{display_ref(route.get('destination'))}`.\n"
                        f"برای تغییر: `/forward set {source} {dest}`"
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

            await progress.step("ذخیره مسیر در کانفیگ")
            routes.append(
                {
                    "source": source,
                    "destination": dest,
                    "enabled": True,
                    "forward_mode": None,
                    "filter": {
                        "enabled": False,
                        "remove_links": False,
                        "remove_mentions": False,
                        "remove_hashtags": False,
                        "remove_ids": False,
                        "prefix": "",
                        "suffix": "",
                        "collapse_whitespace": True,
                        "block_enabled": False,
                        "block_words": [],
                    },
                    "schedule": {
                        "enabled": False,
                        "timezone": "Asia/Tehran",
                        "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                        "windows": [],
                    },
                }
            )
            result = await runtime.patch_module_config(
                "channel_forward",
                {"routes": routes, "enabled": True},
            )
            await progress.success(f"مسیر اضافه شد ({reason}).\n{result}")
            return

        if action == "remove" and len(parts) >= 3:
            source = parts[2].strip()
            await progress.set_title(f"⏳ حذف مسیر مبدأ `{display_ref(source)}`")
            new_routes = [
                r
                for r in routes
                if str(r.get("source")) != source
                and display_ref(r.get("source")) != display_ref(source)
            ]
            if len(new_routes) == len(routes):
                await progress.fail(f"مسیری با مبدأ `{display_ref(source)}` پیدا نشد.")
                return
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
            for route in routes:
                if str(route.get("source")) == source or display_ref(
                    route.get("source")
                ) == display_ref(source):
                    try:
                        await ensure_joined(
                            self.client, source, progress, label="مبدأ"
                        )
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
            await progress.fail(
                f"مبدأ `{display_ref(source)}` نیست. "
                f"با `/forward add {source} {dest}` بساز."
            )
            return

        if action == "mode" and len(parts) >= 4:
            source, mode = parts[2].strip(), parts[3].strip().lower()
            await progress.set_title(f"⏳ تغییر mode مسیر `{display_ref(source)}`")
            if mode not in {"copy", "forward"}:
                await progress.fail("mode باید `copy` یا `forward` باشد.")
                return
            for route in routes:
                if str(route.get("source")) == source or display_ref(
                    route.get("source")
                ) == display_ref(source):
                    route["forward_mode"] = mode
                    result = await runtime.patch_module_config(
                        "channel_forward",
                        {"routes": routes},
                    )
                    await progress.success(result)
                    return
            await progress.fail(f"مبدأ `{display_ref(source)}` پیدا نشد.")
            return

        if action == "filter":
            await self._handle_forward_filter(parts, routes, runtime, progress)
            return

        if action == "schedule":
            await self._handle_forward_schedule(parts, routes, runtime, progress)
            return

        await progress.fail(
            "فرمت‌ها:\n"
            "`/forward status`\n"
            "`/forward add <source> <dest>`\n"
            "`/forward schedule <source> ...`\n"
            "`/forward filter <source> ...`\n"
            "`/stats`"
        )

    async def _handle_forward_schedule(
        self,
        parts: list[str],
        routes: list,
        runtime,
        progress: ProgressMessenger,
    ) -> None:
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
        if route is None:
            await progress.fail(f"مبدأ `{display_ref(source)}` پیدا نشد.")
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
    ) -> None:
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
        if route is None:
            await progress.fail(f"مبدأ `{display_ref(source)}` پیدا نشد.")
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
        return result

    def _save_admins(self) -> None:
        save_json(self.admins_path, {"admin_ids": sorted(self._admins)})

    def _is_admin(self, user_id: int) -> bool:
        if not self.require_admin:
            return True
        return user_id in self._admins

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
        if text.startswith("📋 دستورات مدیر") or text.startswith("🧩 وضعیت ماژول"):
            return
        if text.startswith("📡") or text.startswith("⏳"):
            return
        if self.skip_media_only and not text:
            return

        peer_key = await self._resolve_peer(event)
        if peer_key is None:
            return

        cmd = self._normalize_command(text)

        # Unlock with password (exact match, case-sensitive)
        if self.require_admin and self.admin_password and text == self.admin_password:
            self._admins.add(peer_key)
            self._save_admins()
            if self.delete_password_message:
                try:
                    await event.delete()
                except Exception:
                    logger.debug("Could not delete password message", exc_info=True)
            welcome = self.admin_welcome
            if self.send_help_on_login:
                welcome = f"{self.admin_welcome}\n\n{self._build_help_text()}"
            await self._send(event, welcome)
            logger.info("admin unlocked user_id=%s", peer_key)
            return

        # Help / command list — admin only
        if cmd in self.help_commands or text.strip().lower() in self.help_commands:
            if not self._is_admin(peer_key):
                logger.info("help ignored for non-admin user_id=%s", peer_key)
                return
            await self._send(event, self._build_help_text())
            logger.info("help sent to user_id=%s", peer_key)
            return

        if cmd == "/stats":
            if not self._is_admin(peer_key):
                return
            from app.stats import StatsStore

            await self._send(event, StatsStore().summary(days=2))
            return

        # Logout
        if self.require_admin and (
            text == self.logout_command or cmd == self.logout_command.lower()
        ):
            if peer_key in self._admins:
                self._admins.discard(peer_key)
                self._save_admins()
                await self._send(event, self.logout_message)
                logger.info("admin logged out user_id=%s", peer_key)
            return

        if not self._is_admin(peer_key):
            logger.info("auto_reply ignore non-admin user_id=%s", peer_key)
            return

        # Module management commands
        if cmd == "/forward":
            progress = ProgressMessenger(event)
            await progress.start("⏳ صبر کنید…")
            try:
                await self._handle_forward_command(text.split(), progress)
            except Exception as exc:
                logger.exception("forward command failed")
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
