"""Shared enrich + rank helpers for search / snowball / rerank."""
from __future__ import annotations

from typing import Any

from experiments.linkdir_finders.scoring import rank_candidate, summarize_message_activity


def classify_chat(chat: Any) -> dict[str, Any]:
    """Accurate Telegram chat classification.

    Important: a megagroup/gigagroup can still be *non-postable* for members
    (default_banned_rights.send_messages=True) and feel like a channel in the app.
    """
    class_name = type(chat).__name__
    broadcast = bool(getattr(chat, "broadcast", False))
    megagroup = bool(getattr(chat, "megagroup", False))
    gigagroup = bool(getattr(chat, "gigagroup", False))

    if class_name == "Chat":
        kind = "basic_group"
        is_channel, is_group = False, True
    elif broadcast and not megagroup:
        kind = "broadcast_channel"
        is_channel, is_group = True, False
    elif gigagroup or megagroup:
        kind = "gigagroup" if gigagroup else "megagroup"
        is_channel, is_group = False, True
    elif "Channel" in class_name:
        # Fallback Channel without clear flags
        kind = "broadcast_channel" if broadcast else "megagroup"
        is_channel, is_group = broadcast and not megagroup, not (broadcast and not megagroup)
    else:
        kind = "unknown"
        is_channel, is_group = False, False

    members_can_send: bool | None = None
    dbr = getattr(chat, "default_banned_rights", None)
    if broadcast and not megagroup:
        # Broadcast channels: only admins/posters can post
        members_can_send = False
    elif dbr is not None:
        # In Telethon ChatBannedRights: True means the action is FORBIDDEN
        banned_send = bool(getattr(dbr, "send_messages", False))
        members_can_send = not banned_send
    elif is_group:
        # No default ban object often means defaults allow sending
        members_can_send = True

    return {
        "kind": kind,
        "is_channel": is_channel,
        "is_group": is_group,
        "broadcast": broadcast,
        "megagroup": megagroup,
        "gigagroup": gigagroup,
        "members_can_send": members_can_send,
        "postable": members_can_send is True,
        "tl_type": class_name,
    }


# Backward-compatible wrapper
def chat_kind(chat: Any) -> tuple[bool, bool]:
    info = classify_chat(chat)
    return bool(info["is_channel"]), bool(info["is_group"])


def apply_rank(row: dict[str, Any]) -> None:
    about = row.get("about")
    if about and str(about).startswith("<"):
        about = None
    scored = rank_candidate(
        title=row.get("title"),
        username=row.get("username"),
        about=about,
        participants=int(row["participants"])
        if row.get("participants") is not None
        else None,
        is_channel=bool(row.get("is_channel")),
        is_group=bool(row.get("is_group")),
        kind=row.get("kind"),
        members_can_send=row.get("members_can_send"),
        query=row.get("query"),
        activity=row.get("activity"),
    )
    row.update(
        {
            "identity_score": scored["identity_score"],
            "quality_score": scored["quality_score"],
            "rank_score": scored["rank_score"],
            "score": scored["rank_score"],
            "likely": scored["likely"],
            "verdict": scored["verdict"],
            "reasons": scored["reasons"],
            "identity_reasons": scored["identity_reasons"],
            "quality_reasons": scored["quality_reasons"],
            "gates": scored["gates"],
            "promo_eligible": scored.get("promo_eligible"),
        }
    )


async def enrich_profile(client: Any, chat: Any) -> dict[str, Any]:
    """about + participants + classification (+ linked discussion if any)."""
    info = classify_chat(chat)
    about = None
    participants = getattr(chat, "participants_count", None)
    linked_chat_id = None
    try:
        from telethon.tl.functions.channels import GetFullChannelRequest
        from telethon.tl.types import Channel

        if isinstance(chat, Channel):
            full = await client(GetFullChannelRequest(chat))
            fc = getattr(full, "full_chat", None)
            about = getattr(fc, "about", None)
            participants = getattr(fc, "participants_count", None) or participants
            linked_chat_id = getattr(fc, "linked_chat_id", None)
            # Re-read rights from entity (may be fresher on full fetch path)
            info = classify_chat(chat)
    except Exception as exc:  # noqa: BLE001
        about = f"<enrich_failed:{type(exc).__name__}>"

    return {
        **info,
        "about": str(about) if about else None,
        "participants": int(participants) if participants is not None else None,
        "linked_chat_id": linked_chat_id,
    }


async def enrich_about(client: Any, chat: Any) -> tuple[str | None, int | None]:
    """Backward-compatible thin wrapper."""
    profile = await enrich_profile(client, chat)
    return profile.get("about"), profile.get("participants")


async def sample_activity(client: Any, entity: Any, *, sample: int) -> dict[str, Any]:
    if sample <= 0:
        return {"readable": None, "sample_size": 0}
    try:
        messages = await client.get_messages(entity, limit=sample)
        return summarize_message_activity(list(messages or []))
    except Exception as exc:  # noqa: BLE001
        return {
            "readable": False,
            "error": type(exc).__name__,
            "sample_size": 0,
            "messages_with_text": 0,
            "link_messages": 0,
            "link_count": 0,
            "unique_senders": 0,
            "last_message_age_hours": None,
            "sample_span_hours": None,
        }


async def resolve_and_profile(
    client: Any,
    ref: str,
    *,
    sample: int,
    query: str | None = None,
) -> dict[str, Any] | None:
    """Resolve a @user / entity and build a ranked catalog row."""
    try:
        entity = await client.get_entity(ref)
    except Exception as exc:  # noqa: BLE001
        return {
            "ref": ref,
            "username": ref.lstrip("@") if ref.startswith("@") else None,
            "title": None,
            "id": None,
            "resolve_error": type(exc).__name__,
            "activity": {"readable": False, "error": type(exc).__name__},
            "verdict": "junk",
            "rank_score": 0,
            "identity_score": 0,
            "quality_score": 0,
            "members_can_send": None,
            "postable": False,
            "kind": "unknown",
            "query": query,
        }

    title = getattr(entity, "title", None) or getattr(entity, "first_name", None)
    username = getattr(entity, "username", None)
    profile = await enrich_profile(client, entity)
    activity = await sample_activity(client, entity, sample=sample)
    row: dict[str, Any] = {
        "query": query,
        "id": getattr(entity, "id", None),
        "title": title,
        "username": username,
        "ref": f"@{username}" if username else ref,
        "is_channel": profile["is_channel"],
        "is_group": profile["is_group"],
        "kind": profile["kind"],
        "broadcast": profile["broadcast"],
        "megagroup": profile["megagroup"],
        "gigagroup": profile["gigagroup"],
        "members_can_send": profile["members_can_send"],
        "postable": profile["postable"],
        "linked_chat_id": profile.get("linked_chat_id"),
        "participants": profile.get("participants"),
        "about": profile.get("about"),
        "activity": activity,
        "tl_type": profile.get("tl_type") or type(entity).__name__,
    }
    apply_rank(row)
    return row
