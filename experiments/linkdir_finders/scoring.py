"""Rank لینکدونی candidates so dead/junk groups sink.

Two axes:
  identity — does it LOOK like a link-directory?
  quality  — is it ALIVE and useful (members, freshness, link density)?

Final rank_score blends both. Experiment-only; not wired to production.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

STRONG_TOKENS = (
    "لینکدونی",
    "لینک دونی",
    "linkdoni",
    "linkdon",
    "لینک رایگان",
    "تبادل لینک",
    "گروه لینک",
    "کانال لینک",
    "لینک گروهی",
    "تبلیغ رایگان",
    "آگهی رایگان",
    "free ads",
    "freead",
    "link exchange",
    "linkdump",
    "link dump",
    "links directory",
    "ad directory",
)

SOFT_TOKENS = (
    "لینک",
    "links",
    "link",
    "تبلیغ",
    "ads",
    "advertise",
    "directory",
    "dir",
    "promo",
    "پرومو",
    "عضویت",
    "join",
    "invite",
    "چنل",
    "channel list",
    "گروه یاب",
    "کانال یاب",
)

NEGATIVE_TOKENS = (
    "official",
    "support",
    "helps",
    "help desk",
    "news",
    "اخبار",
    "combot",
    "missrose",
    "shieldy",
    "antispam",
    "anti spam",
    "ضد لینک",
    "ضدلینک",
    "ربات ضد",
    "anti link",
    "antilink",
    "canva",
    "کتاب",
    "book club",
    "دوست یابی",
    "دوستیابی",
    "dating",
    "pavel durov",
)

_LINK_RE = re.compile(
    r"(?i)\b(?:https?://)?(?:t\.me|telegram\.me)/(?:joinchat/|\+)?[A-Za-z0-9_/+-]+"
)
_AT_RE = re.compile(r"(?<!\w)@[A-Za-z][A-Za-z0-9_]{3,}")


def _blob(*parts: Any) -> str:
    return " ".join(str(p or "") for p in parts).lower()


def _clamp(n: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, n))


def count_telegram_links(text: str) -> int:
    if not text:
        return 0
    return len(_LINK_RE.findall(text)) + len(_AT_RE.findall(text))


def identity_score(
    *,
    title: str | None = None,
    username: str | None = None,
    about: str | None = None,
    is_channel: bool | None = None,
    is_group: bool | None = None,
    kind: str | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    """0–100: how much this looks like a لینکدونی (name/about only)."""
    text = _blob(title, username, about)
    reasons: list[str] = []
    score = 0.0

    for tok in STRONG_TOKENS:
        if tok in text:
            score += 34
            reasons.append(f"strong:{tok}")
            break

    soft_hits = [tok for tok in SOFT_TOKENS if tok in text]
    if soft_hits:
        score += min(26.0, 7.0 * len(soft_hits))
        reasons.append("soft:" + ",".join(soft_hits[:4]))

    neg_hits = [tok for tok in NEGATIVE_TOKENS if tok in text]
    if neg_hits:
        score -= 28
        reasons.append("neg:" + ",".join(neg_hits[:3]))

    if username:
        if re.search(r"(link|links|dir|ads|promo|لینک|doni)", username.lower()):
            score += 12
            reasons.append("username_hint")
    else:
        score -= 6
        reasons.append("no_username")

    kind_l = (kind or "").lower()
    if kind_l in {"megagroup", "basic_group"}:
        score += 8
        reasons.append(f"kind:{kind_l}")
    elif kind_l == "gigagroup":
        # Often admin-only posting; still a real link dump source for harvest
        score += 4
        reasons.append("kind:gigagroup")
    elif kind_l == "broadcast_channel" or is_channel:
        score += 3
        reasons.append("kind:broadcast_channel")
    elif is_group:
        score += 8
        reasons.append("group")

    if query:
        q = query.lower().strip()
        if q and q in text:
            score += 10
            reasons.append("query_match")

    score = _clamp(score)
    return {"score": round(score, 1), "reasons": reasons}


def quality_score(
    *,
    participants: int | None = None,
    last_message_age_hours: float | None = None,
    sample_size: int | None = None,
    messages_with_text: int | None = None,
    link_messages: int | None = None,
    link_count: int | None = None,
    unique_senders: int | None = None,
    sample_span_hours: float | None = None,
    readable: bool | None = None,
    members_can_send: bool | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """0–100: alive + useful for promo (members, freshness, link density, postable)."""
    reasons: list[str] = []
    score = 40.0  # neutral baseline before signals

    # --- can members post? (critical for promo destinations) ---
    if members_can_send is False:
        score -= 45
        reasons.append("members_cannot_send")
        if (kind or "") == "broadcast_channel":
            reasons.append("broadcast_channel_no_member_posts")
        else:
            reasons.append("locked_group_like_channel")
    elif members_can_send is True:
        score += 18
        reasons.append("members_can_send")
    else:
        reasons.append("members_can_send:unknown")

    # --- members ---
    if participants is None:
        reasons.append("members:unknown")
    else:
        p = int(participants)
        if p < 30:
            score -= 30
            reasons.append(f"members:dead_small:{p}")
        elif p < 100:
            score -= 12
            reasons.append(f"members:small:{p}")
        elif p < 300:
            score += 6
            reasons.append(f"members:ok_low:{p}")
        elif p <= 25_000:
            score += 18
            reasons.append(f"members:sweet:{p}")
        elif p <= 80_000:
            score += 8
            reasons.append(f"members:large:{p}")
        else:
            score -= 10
            reasons.append(f"members:bloated:{p}")

    # --- freshness of last message ---
    if last_message_age_hours is None:
        if readable is False:
            score -= 15
            reasons.append("activity:unreadable")
        else:
            reasons.append("activity:unknown")
    else:
        age = float(last_message_age_hours)
        if age <= 6:
            score += 22
            reasons.append(f"fresh:<6h:{age:.1f}")
        elif age <= 24:
            score += 16
            reasons.append(f"fresh:<1d:{age:.1f}")
        elif age <= 72:
            score += 8
            reasons.append(f"fresh:<3d:{age:.1f}")
        elif age <= 168:
            score -= 5
            reasons.append(f"stale:<7d:{age:.1f}")
        elif age <= 720:
            score -= 20
            reasons.append(f"stale:<30d:{age:.1f}")
        else:
            score -= 35
            reasons.append(f"dead:>30d:{age:.1f}")

    # --- message volume / density in sample ---
    if sample_size and sample_size > 0:
        text_n = int(messages_with_text or 0)
        link_msg_n = int(link_messages or 0)
        links = int(link_count or 0)
        text_ratio = text_n / sample_size
        link_msg_ratio = link_msg_n / sample_size
        links_per_msg = links / sample_size

        if text_ratio >= 0.5:
            score += 6
            reasons.append(f"text_ratio:{text_ratio:.2f}")
        elif text_ratio < 0.15:
            score -= 10
            reasons.append(f"emptyish:{text_ratio:.2f}")

        if link_msg_ratio >= 0.45 or links_per_msg >= 0.6:
            score += 20
            reasons.append(
                f"link_dense:msg={link_msg_ratio:.2f},lp={links_per_msg:.2f}"
            )
        elif link_msg_ratio >= 0.2 or links_per_msg >= 0.25:
            score += 10
            reasons.append(
                f"link_ok:msg={link_msg_ratio:.2f},lp={links_per_msg:.2f}"
            )
        elif link_msg_ratio < 0.05 and links_per_msg < 0.08:
            score -= 18
            reasons.append("link_sparse:probably_not_linkdir")

        if sample_span_hours and sample_span_hours > 0:
            mph = sample_size / max(sample_span_hours, 0.25)
            if mph >= 2:
                score += 12
                reasons.append(f"rate:hot:{mph:.1f}/h")
            elif mph >= 0.3:
                score += 6
                reasons.append(f"rate:ok:{mph:.1f}/h")
            elif mph < 0.05:
                score -= 12
                reasons.append(f"rate:dead:{mph:.2f}/h")
            else:
                reasons.append(f"rate:slow:{mph:.2f}/h")

        if unique_senders is not None:
            us = int(unique_senders)
            if us >= 8:
                score += 8
                reasons.append(f"senders:diverse:{us}")
            elif us <= 1 and sample_size >= 10:
                score -= 14
                reasons.append(f"senders:bot_or_dead:{us}")
            elif us <= 2 and sample_size >= 15:
                score -= 6
                reasons.append(f"senders:narrow:{us}")

    score = _clamp(score)
    return {"score": round(score, 1), "reasons": reasons}


def rank_candidate(
    *,
    title: str | None = None,
    username: str | None = None,
    about: str | None = None,
    participants: int | None = None,
    is_channel: bool | None = None,
    is_group: bool | None = None,
    kind: str | None = None,
    members_can_send: bool | None = None,
    query: str | None = None,
    activity: dict[str, Any] | None = None,
    identity_weight: float = 0.40,
    quality_weight: float = 0.60,
) -> dict[str, Any]:
    """Blend identity + quality into a final rank and keep/review/junk verdict."""
    act = activity or {}
    ident = identity_score(
        title=title,
        username=username,
        about=about,
        is_channel=is_channel,
        is_group=is_group,
        kind=kind,
        query=query,
    )
    qual = quality_score(
        participants=participants,
        last_message_age_hours=act.get("last_message_age_hours"),
        sample_size=act.get("sample_size"),
        messages_with_text=act.get("messages_with_text"),
        link_messages=act.get("link_messages"),
        link_count=act.get("link_count"),
        unique_senders=act.get("unique_senders"),
        sample_span_hours=act.get("sample_span_hours"),
        readable=act.get("readable"),
        members_can_send=members_can_send,
        kind=kind,
    )

    w_i = float(identity_weight)
    w_q = float(quality_weight)
    total_w = w_i + w_q
    rank = (ident["score"] * w_i + qual["score"] * w_q) / total_w

    gates: list[str] = []
    if participants is not None and participants < 30:
        rank = min(rank, 35)
        gates.append("gate:too_small")
    age = act.get("last_message_age_hours")
    if isinstance(age, (int, float)) and age > 720:
        rank = min(rank, 28)
        gates.append("gate:dead_30d")
    if act.get("readable") is False and not username:
        rank = min(rank, 30)
        gates.append("gate:unreadable_private")
    if ident["score"] < 25 and (act.get("link_count") or 0) < 2:
        rank = min(rank, 32)
        gates.append("gate:not_linkdir_signal")

    promo_eligible = members_can_send is True
    if members_can_send is False:
        rank = min(rank, 55)
        gates.append("gate:not_postable")
    elif members_can_send is None:
        gates.append("gate:postable_unknown")

    rank = _clamp(rank)

    link_ratio = 0.0
    sample_n = int(act.get("messages_with_text") or act.get("sample_size") or 0)
    link_msgs = int(act.get("link_messages") or 0)
    if sample_n > 0:
        link_ratio = link_msgs / max(1, sample_n)

    if (
        promo_eligible
        and rank >= 70
        and qual["score"] >= 50
        and ident["score"] >= 40
        and (link_ratio >= 0.25 or ident["score"] >= 60 or act.get("readable") is not True)
    ):
        # Require link density when we actually sampled messages; allow strong
        # identity titles through when activity sampling was skipped/failed.
        if act.get("readable") is True and link_ratio < 0.25 and ident["score"] < 60:
            verdict = "review"
            gates.append("gate:keep_needs_link_density")
        else:
            verdict = "keep"
    elif rank >= 50 and ident["score"] >= 35:
        verdict = "review"
    else:
        verdict = "junk"

    if verdict == "keep" and not promo_eligible:
        verdict = "review"
        gates.append("gate:keep_demoted_not_postable")

    # Locked channels/groups that clearly look like لینکدونی stay as seeds.
    if (
        members_can_send is False
        and verdict == "junk"
        and ident["score"] >= 55
    ):
        verdict = "review"
        gates.append("gate:seed_only_linkdir")

    return {
        "identity_score": ident["score"],
        "quality_score": qual["score"],
        "rank_score": round(rank, 1),
        "score": round(rank, 1),
        "likely": verdict in {"keep", "review"} and rank >= 50,
        "verdict": verdict,
        "promo_eligible": promo_eligible,
        "reasons": ident["reasons"] + qual["reasons"] + gates,
        "identity_reasons": ident["reasons"],
        "quality_reasons": qual["reasons"],
        "gates": gates,
    }


def summarize_message_activity(
    messages: list[Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Derive activity stats from a Telethon message sample (newest-first ok)."""
    now = now or datetime.now(timezone.utc)
    if not messages:
        return {
            "readable": True,
            "sample_size": 0,
            "messages_with_text": 0,
            "link_messages": 0,
            "link_count": 0,
            "unique_senders": 0,
            "last_message_age_hours": None,
            "sample_span_hours": None,
            "msgs_per_day_est": None,
        }

    dates: list[datetime] = []
    text_n = 0
    link_msg_n = 0
    link_total = 0
    senders: set[int] = set()

    for msg in messages:
        dt = getattr(msg, "date", None)
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dates.append(dt)

        text = (getattr(msg, "message", None) or "") or ""
        # button urls
        buttons = getattr(msg, "buttons", None) or []
        for row in buttons:
            for btn in row:
                url = getattr(btn, "url", None)
                if url:
                    text += f"\n{url}"

        if text.strip():
            text_n += 1
        n_links = count_telegram_links(text)
        if n_links:
            link_msg_n += 1
            link_total += n_links

        sender = getattr(msg, "sender_id", None)
        if sender is None:
            sender = getattr(msg, "from_id", None)
            sender = getattr(sender, "user_id", None) or getattr(sender, "channel_id", None)
        if isinstance(sender, int):
            senders.add(sender)

    dates.sort()
    newest = dates[-1] if dates else None
    oldest = dates[0] if dates else None
    age_h = None
    span_h = None
    if newest is not None:
        age_h = max(0.0, (now - newest).total_seconds() / 3600.0)
    if newest is not None and oldest is not None:
        span_h = max(0.0, (newest - oldest).total_seconds() / 3600.0)

    mph = None
    if span_h and span_h > 0:
        mph = len(messages) / span_h
    mpd = (mph * 24.0) if mph is not None else None

    return {
        "readable": True,
        "sample_size": len(messages),
        "messages_with_text": text_n,
        "link_messages": link_msg_n,
        "link_count": link_total,
        "unique_senders": len(senders),
        "last_message_age_hours": round(age_h, 2) if age_h is not None else None,
        "last_message_at": newest.isoformat() if newest else None,
        "sample_span_hours": round(span_h, 2) if span_h is not None else None,
        "msgs_per_hour_est": round(mph, 3) if mph is not None else None,
        "msgs_per_day_est": round(mpd, 2) if mpd is not None else None,
        "link_msg_ratio": round(link_msg_n / len(messages), 3),
        "links_per_msg": round(link_total / len(messages), 3),
    }


# Backward-compatible thin wrapper used by older call sites.
def score_link_directory(**kwargs: Any) -> dict[str, Any]:
    return rank_candidate(**kwargs)
