"""Discover, load, and start optional modules safely."""
from __future__ import annotations

import importlib
import logging
from typing import Any

from telethon import TelegramClient

from app.base import BaseModule
from app.config import module_enabled

logger = logging.getLogger(__name__)

# Registry: config key -> import path of Module class
MODULE_REGISTRY: dict[str, str] = {
    "auto_reply": "modules.auto_reply.module:AutoReplyModule",
    "channel_forward": "modules.channel_forward.module:ChannelForwardModule",
    "digest": "modules.digest.module:DigestModule",
    "promo_spread": "modules.promo_spread.module:PromoSpreadModule",
    "link_harvest": "modules.link_harvest.module:LinkHarvestModule",
    "group_inspect": "modules.group_inspect.module:GroupInspectModule",
}


def _import_module_class(dotted: str) -> type[BaseModule]:
    module_path, _, class_name = dotted.partition(":")
    if not module_path or not class_name:
        raise ImportError(f"Invalid module path: {dotted}")
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name, None)
    if cls is None:
        raise ImportError(f"{class_name} not found in {module_path}")
    if not issubclass(cls, BaseModule):
        raise TypeError(f"{class_name} must subclass BaseModule")
    return cls


async def load_modules(
    client: TelegramClient,
    modules_config: dict[str, dict[str, Any]],
) -> list[BaseModule]:
    """Load enabled modules. Failures are isolated — app keeps running."""
    loaded: list[BaseModule] = []

    for name, import_path in MODULE_REGISTRY.items():
        cfg = modules_config.get(name)
        if not module_enabled(cfg):
            logger.info("Module '%s' is disabled - skipped", name)
            continue

        assert cfg is not None
        try:
            cls = _import_module_class(import_path)
            instance = cls(client, cfg)
            await instance.start()
            loaded.append(instance)
            logger.info("Module '%s' started", name)
        except Exception:
            logger.exception(
                "Module '%s' failed to load/start - continuing without it",
                name,
            )

    # Warn about unknown keys in config (typos)
    for name in modules_config:
        if name not in MODULE_REGISTRY:
            logger.warning(
                "Unknown module '%s' in config/modules.json (not in registry)",
                name,
            )

    if not loaded:
        logger.warning("No modules are active. Enable modules in config/modules.json")
    else:
        logger.info("Active modules: %s", ", ".join(m.name for m in loaded))

    return loaded


async def stop_modules(modules: list[BaseModule]) -> None:
    for mod in modules:
        try:
            await mod.stop()
            logger.info("Module '%s' stopped", mod.name)
        except Exception:
            logger.exception("Module '%s' failed during stop", mod.name)
