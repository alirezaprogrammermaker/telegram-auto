"""Admin alert notifications from modules."""
from __future__ import annotations

import logging
from typing import Iterable

from telethon import TelegramClient

logger = logging.getLogger(__name__)


async def notify_admins(
    client: TelegramClient,
    admin_ids: Iterable[int],
    text: str,
) -> None:
    for uid in admin_ids:
        try:
            await client.send_message(int(uid), text)
        except Exception:
            logger.debug("failed to notify admin %s", uid, exc_info=True)
