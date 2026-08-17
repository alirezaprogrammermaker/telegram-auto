"""Channel reference normalization and join helpers."""
from __future__ import annotations

from typing import Any

from telethon import TelegramClient
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
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import (
    Channel,
    ChannelParticipantAdmin,
    ChannelParticipantCreator,
)

from app.progress import ProgressMessenger


def normalize_ref(value: Any) -> str | int:
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        raise ValueError("empty channel reference")
    if text.startswith("https://t.me/") or text.startswith("http://t.me/"):
        text = text.split("t.me/", 1)[1]
    text = text.split("?")[0].strip("/")
    if text.startswith("@"):
        text = text[1:]
    if text.lstrip("-").isdigit():
        return int(text)
    return text


def display_ref(value: Any) -> str:
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    if not text:
        return text
    if text.startswith("@") or text.lstrip("-").isdigit() or "t.me/" in text:
        return text if text.startswith("@") or "t.me/" in text or text.startswith("-") else f"@{text}"
    return f"@{text}"


def route_key(source: Any, destination: Any) -> str:
    return f"{display_ref(source)}->{display_ref(destination)}"


def invite_hash(value: Any) -> str | None:
    text = str(value).strip()
    if "joinchat/" in text:
        return text.split("joinchat/", 1)[1].split("?")[0].strip("/")
    if "/+" in text:
        return text.split("/+", 1)[1].split("?")[0].strip("/")
    if text.startswith("+"):
        return text[1:]
    return None


async def can_post_to_channel(client: TelegramClient, channel: Any) -> tuple[bool, str]:
    if not isinstance(channel, Channel):
        return False, "مقصد کانال/سوپرگروه نیست"

    if getattr(channel, "creator", False):
        return True, "owner"

    me = await client.get_me()
    try:
        result = await client(GetParticipantRequest(channel, me))
    except UserNotParticipantError:
        return False, "عضو کانال مقصد نیستی"
    except RPCError as exc:
        return False, f"خطا در بررسی دسترسی: {exc.__class__.__name__}"

    participant = result.participant
    is_broadcast = bool(getattr(channel, "broadcast", False))

    if isinstance(participant, ChannelParticipantCreator):
        return True, "owner"

    if isinstance(participant, ChannelParticipantAdmin):
        rights = participant.admin_rights
        if not is_broadcast:
            return True, "group-admin"
        if rights is None:
            return False, "ادمین هستی ولی حق ارسال مشخص نیست"
        if getattr(rights, "post_messages", False):
            return True, "admin:post_messages"
        return False, "ادمین هستی ولی حق Post Messages نداری"

    if not is_broadcast:
        return True, "group-member"
    return False, "فقط عضو عادی هستی؛ برای ارسال باید ادمین با حق پست باشی"


async def ensure_joined(
    client: TelegramClient,
    ref: Any,
    progress: ProgressMessenger | None = None,
    *,
    label: str = "کانال",
    auto_join: bool = True,
) -> tuple[Any, str]:
    """Resolve channel entity; optionally join if not a member.

    auto_join=False is safer for production accounts that should not
    silently join channels present in a shared modules.json.
    """
    shown = display_ref(ref)
    if progress:
        await progress.step(f"بررسی عضویت {label}: `{shown}`")

    invite = invite_hash(ref)
    if invite:
        if not auto_join:
            # Still allow resolving if already a member via CheckChatInvite
            from telethon.tl.functions.messages import CheckChatInviteRequest
            from telethon.tl.types import ChatInviteAlready

            try:
                checked = await client(CheckChatInviteRequest(invite))
            except Exception as exc:
                raise ValueError(
                    f"عضو `{shown}` نیستی و auto_join خاموش است"
                ) from exc
            if isinstance(checked, ChatInviteAlready):
                if progress:
                    await progress.step(f"از قبل عضو {label}: `{shown}`")
                return checked.chat, "already"
            raise ValueError(
                f"عضو `{shown}` نیستی و auto_join خاموش است — دستی جوین کن یا از چت /forward add بزن"
            )

        if progress:
            await progress.step(f"لینک دعوت تشخیص داده شد — تلاش برای جوین `{shown}`")
        try:
            updates = await client(ImportChatInviteRequest(invite))
            entity = None
            chats = getattr(updates, "chats", None) or []
            if chats:
                entity = chats[0]
            if entity is None:
                entity = await client.get_entity(normalize_ref(ref))
            if progress:
                await progress.step(f"جوین شدم به {label}: `{shown}`")
            return entity, "joined_invite"
        except UserAlreadyParticipantError:
            entity = await client.get_entity(normalize_ref(ref))
            if progress:
                await progress.step(f"از قبل عضو {label} بودم: `{shown}`")
            return entity, "already"
        except (InviteHashInvalidError, InviteHashExpiredError) as exc:
            raise ValueError(f"لینک دعوت نامعتبر/منقضی است: `{shown}`") from exc
        except FloodWaitError:
            raise
        except RPCError as exc:
            raise ValueError(f"جوین با دعوت ناموفق: {exc.__class__.__name__}") from exc

    try:
        entity = await client.get_entity(normalize_ref(ref))
    except (ValueError, ChannelPrivateError) as exc:
        raise ValueError(
            f"کانال `{shown}` پیدا نشد یا خصوصی است. اگر خصوصی است لینک دعوت بده."
        ) from exc

    if not isinstance(entity, Channel):
        raise ValueError(f"`{shown}` کانال نیست")

    me = await client.get_me()
    try:
        await client(GetParticipantRequest(entity, me))
        if progress:
            await progress.step(f"از قبل عضو {label} هستم: `{shown}`")
        return entity, "already"
    except UserNotParticipantError:
        pass
    except RPCError:
        pass

    if not auto_join:
        raise ValueError(
            f"عضو `{shown}` نیستی و auto_join خاموش است — "
            "دستی جوین کن یا موقتاً auto_join را روشن کن"
        )

    if progress:
        await progress.step(f"عضو نیستم — جوین به {label}: `{shown}`")

    try:
        await client(JoinChannelRequest(entity))
    except UserAlreadyParticipantError:
        if progress:
            await progress.step(f"از قبل عضو {label} بودم: `{shown}`")
        return entity, "already"
    except ChannelPrivateError as exc:
        raise ValueError(
            f"کانال `{shown}` خصوصی است و بدون دعوت نمی‌شود جوین شد."
        ) from exc
    except FloodWaitError:
        raise
    except RPCError as exc:
        raise ValueError(
            f"نتوانستم به `{shown}` جوین شوم: {exc.__class__.__name__}"
        ) from exc

    if progress:
        await progress.step(f"جوین شدم به {label}: `{shown}`")
    return entity, "joined"


async def ensure_can_post(
    client: TelegramClient,
    dest_ref: Any,
    progress: ProgressMessenger | None = None,
    *,
    auto_join: bool = True,
) -> tuple[Any, str]:
    if progress:
        await progress.step(f"بررسی کانال مقصد: `{display_ref(dest_ref)}`")

    entity, _join_status = await ensure_joined(
        client,
        dest_ref,
        progress,
        label="مقصد",
        auto_join=auto_join,
    )

    if progress:
        await progress.step("بررسی حق ارسال پست در مقصد")

    ok, reason = await can_post_to_channel(client, entity)
    if not ok:
        raise ValueError(
            f"در مقصد `{display_ref(dest_ref)}` نمی‌توانی پست بگذاری ({reason}). "
            "اکانت را ادمین کانال مقصد کن و حق Post Messages را بده."
        )
    if progress:
        await progress.step(f"حق پست تأیید شد ({reason})")
    return entity, reason


def entity_label(entity: Any) -> str:
    from telethon import utils

    username = getattr(entity, "username", None)
    title = getattr(entity, "title", None)
    if username:
        return f"@{username}"
    if title:
        return str(title)
    return str(utils.get_peer_id(entity))
