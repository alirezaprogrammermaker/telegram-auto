"""Shared Telethon helpers for linkdir experiments (retries, UTF-8, client)."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

from dotenv import load_dotenv

from app.client import build_client
from app.config import load_app_config

logger = logging.getLogger("linkdir_finders")


def setup_stdio() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def setup_logging(*, verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


async def connect_client(
    *,
    session: str | None = None,
    retries: int = 8,
    retry_sleep: float = 15.0,
) -> tuple[Any, Any]:
    """Return (client, app_config). Raises after exhausted retries."""
    from pathlib import Path

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    if session:
        os.environ["SESSION_NAME"] = session

    config = load_app_config()
    client = build_client(config)
    last_exc: Exception | None = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                raise RuntimeError(f"Session not authorized: {config.session_name}")
            me = await client.get_me()
            logger.info(
                "connected session=%s user=@%s id=%s (attempt %s)",
                config.session_name,
                getattr(me, "username", None),
                me.id,
                attempt,
            )
            return client, config
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "connect failed attempt %s/%s: %s: %s",
                attempt,
                retries,
                type(exc).__name__,
                exc,
            )
            try:
                await client.disconnect()
            except Exception:
                pass
            if attempt < retries:
                await asyncio.sleep(retry_sleep)
            client = build_client(config)

    assert last_exc is not None
    raise last_exc


async def safe_disconnect(client: Any) -> None:
    try:
        await client.disconnect()
    except Exception:
        pass
