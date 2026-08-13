"""Resolve and validate promo source channel + destination groups.

Supports public @usernames, numeric ids, and private invite links:
  https://t.me/+HASH  /  t.me/joinchat/HASH
"""
from __future__ import annotations

import logging
from typing import Any

from telethon import TelegramClient, utils
from telethon.errors import (
    ChannelPrivateError,
    FloodWaitError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    RPCError,
    UserAlreadyParticipantError,
    UserNotParticipantError,
)
from telethon.tl.functions.channels import GetParticipantRequest, JoinChannelRequest
from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest
from telethon.tl.types import Channel, Chat, ChatInvite, ChatInviteAlready

from modules.channel_forward.refs import display_ref, invite_hash, normalize_ref

logger = logging.getLogger(__name__)


def _stable_label(entity: Any, fallback: Any) -> str:
    username = getattr(entity, "username", None)
    if username:
        return f"@{username}"
    title = getattr(entity, "title", None)
    if title:
        return str(title)
    try:
        return str(utils.get_peer_id(entity))
    except Exception:
        return display_ref(fallback)


async def _resolve_invite(client: TelegramClient, ref: Any) -> Any:
    """Join or resolve a private invite link (+hash / joinchat)."""
    inv = invite_hash(ref)
    if not inv:
        raise ValueError("invite hash missing")

    try:
        updates = await client(ImportChatInviteRequest(inv))
        chats = getattr(updates, "chats", None) or []
        if chats:
            return chats[0]
    except UserAlreadyParticipantError:
        pass
    except (InviteHashInvalidError, InviteHashExpiredError) as exc:
        raise ValueError(f"لینک دعوت نامعتبر/منقضی است: `{display_ref(ref)}`") from exc
    except FloodWaitError:
        raise
    except RPCError as exc:
        # Fall through to CheckChatInvite for already-member / preview cases
        logger.debug("ImportChatInvite soft-fail: %s", exc.__class__.__name__)

    try:
        checked = await client(CheckChatInviteRequest(inv))
    except (InviteHashInvalidError, InviteHashExpiredError) as exc:
        raise ValueError(f"لینک دعوت نامعتبر/منقضی است: `{display_ref(ref)}`") from exc
    except FloodWaitError:
        raise
    except RPCError as exc:
        raise ValueError(f"بررسی لینک دعوت ناموفق: {exc.__class__.__name__}") from exc

    if isinstance(checked, ChatInviteAlready):
        return checked.chat
    if isinstance(checked, ChatInvite):
        # Not a member yet and import didn't return chats — try import once more
        try:
            updates = await client(ImportChatInviteRequest(inv))
            chats = getattr(updates, "chats", None) or []
            if chats:
                return chats[0]
        except UserAlreadyParticipantError:
            pass
        except RPCError as exc:
            raise ValueError(
                f"جوین با لینک دعوت ناموفق: {exc.__class__.__name__}"
            ) from exc
        raise ValueError(
            f"با لینک `{display_ref(ref)}` جوین نشدم — لینک را چک کن یا دستی عضو شو"
        )

    raise ValueError(f"پاسخ ناشناخته برای لینک دعوت: `{display_ref(ref)}`")


async def resolve_entity(client: TelegramClient, ref: Any):
    if invite_hash(ref):
        return await _resolve_invite(client, ref)
    normalized = normalize_ref(ref)
    return await client.get_entity(normalized)


async def ensure_source_channel(client: TelegramClient, ref: Any) -> tuple[Any, str]:
    entity = await resolve_entity(client, ref)
    if not isinstance(entity, Channel) or not bool(getattr(entity, "broadcast", False)):
        raise ValueError("منبع باید یک کانال (broadcast) باشد، نه گروه")

    me = await client.get_me()
    try:
        await client(GetParticipantRequest(entity, me))
    except UserNotParticipantError:
        # Public channel: try join; private without invite already failed above
        if getattr(entity, "username", None):
            try:
                await client(JoinChannelRequest(entity))
            except UserAlreadyParticipantError:
                pass
            except RPCError as exc:
                raise ValueError(f"عضو کانال منبع نیستی ({exc.__class__.__name__})") from exc
        else:
            raise ValueError("عضو کانال منبع نیستی — لینک دعوت بده") from None
    except ChannelPrivateError as exc:
        raise ValueError("کانال خصوصی است و دسترسی نداری") from exc
    except RPCError:
        logger.debug("source participant check soft-failed", exc_info=True)

    return entity, _stable_label(entity, ref)


async def ensure_promo_group(client: TelegramClient, ref: Any) -> tuple[Any, str, int]:
    entity = await resolve_entity(client, ref)
    label = _stable_label(entity, ref)

    if isinstance(entity, Channel):
        if bool(getattr(entity, "broadcast", False)):
            raise ValueError(f"{label} کانال است — فقط گروه/سوپرگروه مجاز است")
        me = await client.get_me()
        try:
            await client(GetParticipantRequest(entity, me))
        except UserNotParticipantError as exc:
            raise ValueError(f"عضو {label} نیستی — لینک دعوت معتبر بده یا دستی جوین شو") from exc
        except RPCError as exc:
            raise ValueError(f"بررسی عضویت {label} شکست: {exc.__class__.__name__}") from exc
        return entity, label, int(entity.id)

    if isinstance(entity, Chat):
        return entity, label, int(entity.id)

    raise ValueError(f"{label} گروه معتبر نیست")


def normalize_group_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = str(item).strip()
        if not text:
            continue
        # Keep invite URLs intact; otherwise normalize display form.
        if invite_hash(text) or "t.me/" in text or "telegram.me/" in text:
            shown = text
        else:
            shown = display_ref(text)
        if shown and shown not in out:
            out.append(shown)
    return out
