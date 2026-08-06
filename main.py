"""Application entrypoint — loads optional modules and runs until stopped."""
from __future__ import annotations

import asyncio
import logging
import sys

from app.client import build_client
from app.config import load_app_config
from app.loader import load_modules, stop_modules
from app.logging_setup import setup_logging
from app.runtime import ModuleRuntime
from app.singleton import ProcessLock

logger = logging.getLogger(__name__)


async def run() -> None:
    config = load_app_config()
    setup_logging(config.log_level, config.root)

    lock = ProcessLock(config.lock_file)
    lock.acquire()

    client = build_client(config)
    runtime = ModuleRuntime(client, config.modules)
    # Shared with modules (admin commands)
    setattr(client, "app_runtime", runtime)

    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError(
                "Session is not authorized. Run: python login.py send "
                "then python login.py sign_in <code> [password]"
            )

        me = await client.get_me()
        logger.info(
            "Connected as %s (@%s) id=%s",
            me.first_name,
            me.username,
            me.id,
        )

        modules = await load_modules(client, config.modules)
        runtime.bind_loaded(modules)
        logger.info("App running. Press Ctrl+C to stop.")
        await client.run_until_disconnected()
    finally:
        await stop_modules(list(runtime.loaded.values()))
        if client.is_connected():
            await client.disconnect()
        lock.release()
        logger.info("Bye.")


def main() -> None:
    try:
        asyncio.run(run())
    except RuntimeError as exc:
        logging.basicConfig(level=logging.ERROR)
        logging.error("%s", exc)
        sys.exit(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
