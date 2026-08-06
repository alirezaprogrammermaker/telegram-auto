"""Application entrypoint — loads optional modules and runs until stopped."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys

from app.client import build_client
from app.config import load_app_config
from app.loader import load_modules, stop_modules
from app.logging_setup import setup_logging
from app.runtime import ModuleRuntime
from app.singleton import ProcessLock

logger = logging.getLogger(__name__)


def _max_runtime_seconds() -> int:
    raw = os.environ.get("MAX_RUNTIME_SECONDS", "0").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _install_shutdown_handlers(stop_event: asyncio.Event) -> None:
    """Turn SIGINT/SIGTERM into a graceful disconnect.

    CI runners send SIGTERM when a job is cancelled; disconnecting cleanly
    keeps Telegram from seeing an abruptly dropped session every time.
    """
    loop = asyncio.get_running_loop()

    def _request_stop(reason: str) -> None:
        if not stop_event.is_set():
            logger.info("Shutdown requested (%s)", reason)
            stop_event.set()

    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, _request_stop, sig_name)
        except NotImplementedError:
            # Windows event loops don't support add_signal_handler.
            with contextlib.suppress(ValueError, OSError):
                signal.signal(sig, lambda *_, name=sig_name: _request_stop(name))


async def run() -> None:
    config = load_app_config()
    setup_logging(config.log_level, config.root)

    lock = ProcessLock(config.lock_file)
    lock.acquire()

    client = build_client(config)
    runtime = ModuleRuntime(client, config.modules)
    # Shared with modules (admin commands)
    setattr(client, "app_runtime", runtime)

    stop_event = asyncio.Event()
    try:
        _install_shutdown_handlers(stop_event)

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

        max_runtime = _max_runtime_seconds()
        if max_runtime > 0:
            logger.info(
                "Will auto-stop after %s seconds (MAX_RUNTIME_SECONDS)",
                max_runtime,
            )

        logger.info("App running. Press Ctrl+C to stop.")
        disconnected = asyncio.ensure_future(client.run_until_disconnected())
        stopped = asyncio.ensure_future(stop_event.wait())
        waits = [disconnected, stopped]
        timeout = max_runtime if max_runtime > 0 else None

        done, pending = await asyncio.wait(
            waits,
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not done:
            logger.info("MAX_RUNTIME_SECONDS reached; stopping cleanly")
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
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
