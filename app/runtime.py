"""Runtime module manager — enable/disable/reload and persist config."""
from __future__ import annotations

import copy
import logging
from typing import Any

from telethon import TelegramClient

from app.base import BaseModule
from app.config import MODULES_CONFIG_PATH, RUNTIME_MODULES_PATH, module_enabled
from app.loader import MODULE_REGISTRY, _import_module_class
from app.storage import save_json

logger = logging.getLogger(__name__)

# Core control plane — must stay on so admin can manage the app
PROTECTED_MODULES = frozenset({"auto_reply"})


class ModuleRuntime:
    def __init__(
        self,
        client: TelegramClient,
        modules_config: dict[str, dict[str, Any]],
    ) -> None:
        self.client = client
        self.modules_config = modules_config
        self.loaded: dict[str, BaseModule] = {}

    def bind_loaded(self, modules: list[BaseModule]) -> None:
        self.loaded = {m.name: m for m in modules}

    def list_status(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for name in MODULE_REGISTRY:
            cfg = self.modules_config.get(name) or {}
            rows.append(
                {
                    "name": name,
                    "enabled": module_enabled(cfg),
                    "running": name in self.loaded,
                    "protected": name in PROTECTED_MODULES,
                    "config": copy.deepcopy(cfg),
                }
            )
        return rows

    def persist(self) -> None:
        payload = {"modules": self.modules_config}
        save_json(MODULES_CONFIG_PATH, payload)
        # Mirror into data/ so GitHub Actions cache restores admin edits
        # (routes added via /forward add) on the next job.
        RUNTIME_MODULES_PATH.parent.mkdir(parents=True, exist_ok=True)
        save_json(RUNTIME_MODULES_PATH, payload)
        logger.info("Saved module config → %s (+ runtime overlay)", MODULES_CONFIG_PATH)

    async def stop_module(self, name: str) -> str:
        mod = self.loaded.pop(name, None)
        if mod is None:
            return f"ماژول `{name}` در حال اجرا نبود."
        try:
            await mod.stop()
        except Exception as exc:
            logger.exception("stop failed for %s", name)
            return f"خطا هنگام توقف `{name}`: {exc}"
        return f"ماژول `{name}` متوقف شد."

    async def start_module(self, name: str) -> str:
        if name not in MODULE_REGISTRY:
            known = ", ".join(MODULE_REGISTRY)
            return f"ماژول `{name}` در رجیستری نیست.\nموجود: {known}"

        cfg = self.modules_config.get(name)
        if not isinstance(cfg, dict):
            return f"تنظیمات `{name}` پیدا نشد."

        if name in self.loaded:
            await self.stop_module(name)

        try:
            cls = _import_module_class(MODULE_REGISTRY[name])
            instance = cls(self.client, copy.deepcopy(cfg))
            await instance.start()
            self.loaded[name] = instance
        except Exception as exc:
            logger.exception("start failed for %s", name)
            return f"خطا در استارت `{name}`: {exc}"
        return f"ماژول `{name}` روشن و اجرا شد."

    async def set_enabled(self, name: str, enabled: bool) -> str:
        if name not in MODULE_REGISTRY:
            known = ", ".join(MODULE_REGISTRY)
            return f"ماژول `{name}` شناخته نشد.\nموجود: {known}"

        if name in PROTECTED_MODULES and not enabled:
            return (
                f"ماژول `{name}` محافظت‌شده است و نمی‌شود خاموشش کرد "
                "(وگرنه دسترسی مدیریت قطع می‌شود)."
            )

        cfg = self.modules_config.setdefault(name, {})
        if not isinstance(cfg, dict):
            cfg = {}
            self.modules_config[name] = cfg
        cfg["enabled"] = bool(enabled)
        self.persist()

        if enabled:
            return await self.start_module(name)
        msg = await self.stop_module(name)
        return f"`{name}` در کانفیگ خاموش شد.\n{msg}"

    async def reload_module(self, name: str) -> str:
        if name not in MODULE_REGISTRY:
            return f"ماژول `{name}` شناخته نشد."
        if name in PROTECTED_MODULES:
            return (
                f"ری‌لود `{name}` از چت مجاز نیست (ماژول مدیریت)."
                " برای اعمال تغییرات کد، یک‌بار `main.py` را ری‌استارت کن."
            )
        cfg = self.modules_config.get(name) or {}
        if not module_enabled(cfg):
            return f"ماژول `{name}` در کانفیگ خاموش است. اول `/module on {name}` بزن."
        return await self.start_module(name)

    async def patch_module_config(
        self,
        name: str,
        patch: dict[str, Any],
        *,
        reload: bool = True,
    ) -> str:
        if name not in MODULE_REGISTRY:
            return f"ماژول `{name}` شناخته نشد."
        cfg = self.modules_config.setdefault(name, {})
        if not isinstance(cfg, dict):
            return f"تنظیمات `{name}` نامعتبر است."
        cfg.update(patch)
        self.persist()
        if reload and module_enabled(cfg):
            result = await self.start_module(name)
            return f"تنظیمات `{name}` ذخیره شد.\n{result}"
        return f"تنظیمات `{name}` ذخیره شد (ماژول خاموش است)."

    def format_status_text(self) -> str:
        lines = ["🧩 وضعیت ماژول‌ها", "────────────"]
        for row in self.list_status():
            flag = "ON" if row["enabled"] else "OFF"
            run = "running" if row["running"] else "stopped"
            prot = " 🔒" if row["protected"] else ""
            lines.append(f"• `{row['name']}` — {flag} / {run}{prot}")
        lines.extend(
            [
                "────────────",
                "`/module on <name>`",
                "`/module off <name>`",
                "`/module reload <name>`",
                "`/forward status`",
                "`/forward add <source> <dest>`",
                "`/forward remove <source>`",
                "`/forward set <source> <dest>`",
                "`/forward mode <source> copy|forward`",
                "`/forward filter <source>`",
                "`/forward filter <source> links on`",
                "`/forward filter <source> prefix متن`",
            ]
        )
        return "\n".join(lines)
