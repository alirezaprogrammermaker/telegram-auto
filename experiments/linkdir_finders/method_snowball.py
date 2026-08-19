"""Deep snowball discovery — multi-hop, anti-ban safe.

Safety rules (hard):
- Never ImportChatInvite / JoinChannel unless config explicitly allows joins
  (default: joins disabled, daily_joins=0)
- Invite links are only *peeked* via CheckChatInviteRequest
- Hard daily budgets + jitter delays + FloodWait/PeerFlood circuit
- Prefer reading seed_only / promo_ready chats already resolvable by username

Not wired into production promo modules.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
from typing import Any

from telethon.errors import (
    FloodWaitError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    PeerFloodError,
    RPCError,
)
from telethon.tl.functions.messages import CheckChatInviteRequest
from telethon.tl.types import ChatInvite, ChatInviteAlready, ChatInvitePeek

from modules.channel_forward.refs import invite_hash
from modules.group_pool.pool import extract_links_from_text, normalize_group_ref
from experiments.linkdir_finders.blocklist import blocklist_from_config, is_blocked, normalize_username
from experiments.linkdir_finders.catalog import LinkDirCatalog
from experiments.linkdir_finders.enrich import resolve_and_profile
from experiments.linkdir_finders.safety_guard import SafetyGuard
from experiments.linkdir_finders.scoring import rank_candidate
from experiments.linkdir_finders.settings import load_config
from experiments.linkdir_finders.tg import (
    connect_client,
    safe_disconnect,
    setup_logging,
    setup_stdio,
)

logger = logging.getLogger("linkdir_finders.snowball")

_INVITE_RE = re.compile(
    r"(?i)(?:https?://)?(?:t\.me|telegram\.me)/(?:joinchat/|\+)([A-Za-z0-9_-]+)"
)


def _split_links(links: list[str], *, exclude: set[str]) -> tuple[list[str], list[str]]:
    """Return (username_refs, invite_urls) not already known."""
    usernames: list[str] = []
    invites: list[str] = []
    seen: set[str] = set()
    for raw in links:
        text = (raw or "").strip()
        if not text:
            continue
        inv = invite_hash(text)
        if inv:
            key = f"invite:{inv.lower()}"
            if key in exclude or key in seen:
                continue
            seen.add(key)
            # keep canonical form
            invites.append(f"https://t.me/+{inv}")
            continue
        ref = normalize_group_ref(text) or text
        if not ref.startswith("@"):
            continue
        key = ref.lower()
        if key in exclude or key in seen:
            continue
        seen.add(key)
        usernames.append(ref)
    return usernames, invites


def _message_text_blob(messages: list[Any]) -> str:
    text_blob = ""
    for msg in messages or []:
        text_blob += "\n" + (getattr(msg, "message", None) or "")
        buttons = getattr(msg, "buttons", None) or []
        for row in buttons:
            for btn in row:
                url = getattr(btn, "url", None)
                if url:
                    text_blob += f"\n{url}"
    return text_blob


def _invite_row_from_peek(
    invite_url: str,
    peeked: Any,
    *,
    parent: str,
) -> dict[str, Any]:
    """Build a catalog row from CheckChatInvite without joining."""
    title = getattr(peeked, "title", None)
    participants = getattr(peeked, "participants_count", None)
    broadcast = bool(getattr(peeked, "broadcast", False))
    megagroup = bool(getattr(peeked, "megagroup", False))
    if broadcast and not megagroup:
        kind = "broadcast_channel"
        is_channel, is_group = True, False
        members_can_send = False
    else:
        kind = "megagroup" if megagroup else "unknown"
        is_channel, is_group = False, True
        # Without Join we cannot read default_banned_rights — unknown
        members_can_send = None

    about = getattr(peeked, "about", None)
    scored = rank_candidate(
        title=title,
        username=None,
        about=str(about) if about else None,
        participants=int(participants) if participants is not None else None,
        is_channel=is_channel,
        is_group=is_group,
        kind=kind,
        members_can_send=members_can_send,
        query=f"snowball_invite:{parent}",
        activity={"readable": False, "sample_size": 0},
    )
    inv = invite_hash(invite_url) or invite_url
    return {
        "query": f"snowball_invite:{parent}",
        "id": None,
        "title": title,
        "username": None,
        "ref": f"https://t.me/+{inv}" if not str(invite_url).startswith("http") else invite_url,
        "invite_hash": inv,
        "is_channel": is_channel,
        "is_group": is_group,
        "kind": kind,
        "broadcast": broadcast,
        "megagroup": megagroup,
        "gigagroup": False,
        "members_can_send": members_can_send,
        "postable": False if members_can_send is False else None,
        "participants": participants,
        "about": str(about) if about else None,
        "activity": {"readable": False, "sample_size": 0, "peek_only": True},
        "parent_seed": parent,
        "tl_type": type(peeked).__name__,
        **{k: scored[k] for k in (
            "identity_score",
            "quality_score",
            "rank_score",
            "score",
            "likely",
            "verdict",
            "promo_eligible",
            "reasons",
            "identity_reasons",
            "quality_reasons",
            "gates",
        )},
    }


async def _safe_call(guard: SafetyGuard, coro_factory, *, label: str):
    """Run an API coroutine; trip circuit on flood errors."""
    if guard.circuit_open():
        raise RuntimeError(f"circuit_open:{guard.snapshot().get('circuit_reason')}")
    try:
        return await coro_factory()
    except FloodWaitError as exc:
        logger.warning("%s FloodWait %ss — stopping this run", label, exc.seconds)
        guard.note_flood_wait(int(exc.seconds))
        raise
    except PeerFloodError:
        logger.warning("%s PeerFlood — opening long circuit", label)
        guard.note_peer_flood()
        raise


async def run_snowball(
    *,
    session: str | None = None,
    cfg: dict[str, Any] | None = None,
    client: Any | None = None,
    own_client: bool = True,
    collector_id: str | None = None,
) -> dict[str, Any]:
    config = cfg or load_config()
    sb = config.get("snowball") or {}
    safety_cfg = config.get("safety") or {}
    # snowball-specific safety overrides merge on top
    merged_safety = {**safety_cfg, **(sb.get("safety") or {})}
    pipe = config.get("pipeline") or {}
    catalog = LinkDirCatalog(collector_id=collector_id)
    guard = SafetyGuard(merged_safety, collector_id=collector_id)

    hops = max(1, min(3, int(sb.get("hops") or 2)))
    seed_limit = int(sb.get("seed_limit") or 10)
    min_rank = float(sb.get("min_seed_rank") or 55)
    min_next_identity = float(sb.get("min_next_hop_identity") or 58)
    messages_per_seed = int(sb.get("messages_per_seed") or 35)
    max_new = int(sb.get("max_new_per_run") or 25)
    max_resolve = int(sb.get("max_resolve_per_run") or 30)
    max_invite_peek = int(sb.get("max_invite_peek_per_run") or 12)
    enrich_sample = int(sb.get("enrich_sample") or 20)
    prefer_seed_only = bool(sb.get("prefer_seed_only", True))

    stats: dict[str, Any] = {
        "method": "snowball_deep",
        "hops": hops,
        "seeds": 0,
        "links_found": 0,
        "username_candidates": 0,
        "invite_candidates": 0,
        "resolved": 0,
        "invite_peeked": 0,
        "new_upserts": 0,
        "keep": 0,
        "review": 0,
        "junk": 0,
        "blocked_skipped": 0,
        "errors": 0,
        "stopped_reason": None,
        "safety": guard.snapshot(),
    }

    if guard.circuit_open():
        stats["stopped_reason"] = f"circuit:{guard.snapshot().get('circuit_reason')}"
        logger.warning("skip snowball — %s", stats["stopped_reason"])
        return stats

    raw_seeds = catalog.seeds_for_snowball(
        limit=seed_limit,
        min_rank=min_rank,
        prefer_seed_only=prefer_seed_only,
    )
    blocked_usernames = blocklist_from_config(config)
    bl_cfg = config.get("blocklist") or {}
    skip_junk = bool(bl_cfg.get("skip_junk_catalog", True))

    def _seed_blocked(seed: dict[str, Any]) -> bool:
        u = normalize_username(str(seed.get("username") or seed.get("ref") or ""))
        return bool(u and u in blocked_usernames)

    seeds = [s for s in raw_seeds if not _seed_blocked(s)]
    stats["blocked_skipped"] = len(raw_seeds) - len(seeds)
    if not seeds:
        stats["stopped_reason"] = "no_seeds"
        logger.warning("no seeds — run search/reclassify first")
        return stats

    created_client = False
    if client is None:
        client, _ = await connect_client(
            session=session or config.get("session_name"),
            retries=int(pipe.get("connect_retries") or 8),
            retry_sleep=float(pipe.get("retry_sleep") or 15),
        )
        created_client = True
        own_client = True

    known = catalog.known_refs()
    exclude = set(known)
    for u in blocked_usernames:
        exclude.add(f"@{u}")
    if skip_junk:
        for item in catalog.list_items(status="junk", limit=500):
            ref = str(item.get("ref") or "").lower()
            if ref:
                exclude.add(ref)
            uname = item.get("username")
            if uname:
                exclude.add(f"@{str(uname).lower()}")
    for s in seeds:
        if s.get("username"):
            exclude.add(f"@{str(s['username']).lower()}")

    # Working sets per hop
    seed_queue: list[dict[str, Any]] = list(seeds)
    stats["seeds"] = len(seed_queue)

    try:
        for hop in range(1, hops + 1):
            if guard.circuit_open():
                stats["stopped_reason"] = "circuit_mid_run"
                break
            if stats["new_upserts"] >= max_new:
                stats["stopped_reason"] = "max_new_reached"
                break

            logger.info("=== hop %s/%s seeds=%s ===", hop, hops, len(seed_queue))
            next_seeds: list[dict[str, Any]] = []
            username_candidates: list[tuple[str, str]] = []
            invite_candidates: list[tuple[str, str]] = []

            for i, seed in enumerate(seed_queue, 1):
                ok, why = guard.allow("seed_read")
                if not ok:
                    stats["stopped_reason"] = why
                    logger.warning("budget stop at seed_read: %s", why)
                    break
                ok2, why2 = guard.allow("message_fetch")
                if not ok2:
                    stats["stopped_reason"] = why2
                    break

                uname = seed.get("username")
                if not uname:
                    continue
                seed_ref = f"@{uname}"
                logger.info(
                    "[hop%s %s/%s] read %s seed_only=%s rank=%s",
                    hop,
                    i,
                    len(seed_queue),
                    seed_ref,
                    seed.get("seed_only"),
                    seed.get("rank_score"),
                )
                try:
                    entity = await _safe_call(
                        guard,
                        lambda u=uname: client.get_entity(u),
                        label=f"get_entity {seed_ref}",
                    )
                    guard.record("seed_read")
                    messages = await _safe_call(
                        guard,
                        lambda e=entity: client.get_messages(e, limit=messages_per_seed),
                        label=f"get_messages {seed_ref}",
                    )
                    guard.record("message_fetch")
                except (FloodWaitError, PeerFloodError, RuntimeError):
                    stats["stopped_reason"] = stats["stopped_reason"] or "flood_or_circuit"
                    break
                except Exception as exc:  # noqa: BLE001
                    logger.warning("seed failed %s: %s", seed_ref, type(exc).__name__)
                    stats["errors"] += 1
                    await guard.sleep("seed_read")
                    continue

                links = extract_links_from_text(
                    _message_text_blob(list(messages or [])),
                    exclude_usernames=exclude,
                )
                # also catch invite patterns extract_links might normalize oddly
                blob = _message_text_blob(list(messages or []))
                for m in _INVITE_RE.finditer(blob):
                    links.append(f"https://t.me/+{m.group(1)}")

                stats["links_found"] += len(links)
                users, invites = _split_links(links, exclude=exclude)
                for ref in users:
                    username_candidates.append((ref, seed_ref))
                    exclude.add(ref.lower())
                for inv in invites:
                    invite_candidates.append((inv, seed_ref))
                    h = invite_hash(inv)
                    if h:
                        exclude.add(f"invite:{h.lower()}")

                await guard.sleep("seed_read")

            stats["username_candidates"] += len(username_candidates)
            stats["invite_candidates"] += len(invite_candidates)
            # Prefer candidates harvested from stronger Persian / high-identity parents
            parent_weight = {
                f"@{str(s.get('username')).lower()}": (
                    float(s.get("identity_score") or 0),
                    1
                    if any(
                        t in str(s.get("title") or "")
                        or t in str(s.get("username") or "").lower()
                        for t in ("لینک", "doni", "گپ", "تبلیغ", "تبادل")
                    )
                    else 0,
                )
                for s in seed_queue
                if s.get("username")
            }

            def _cand_key(item: tuple[str, str]) -> tuple:
                _ref, parent = item
                w = parent_weight.get(parent.lower(), (0.0, 0))
                return (w[1], w[0])

            username_candidates.sort(key=_cand_key, reverse=True)
            invite_candidates.sort(key=_cand_key, reverse=True)
            logger.info(
                "hop%s candidates @=%s invites=%s",
                hop,
                len(username_candidates),
                len(invite_candidates),
            )

            # Resolve public usernames (no join)
            for ref, parent in username_candidates:
                if stats["new_upserts"] >= max_new or stats["resolved"] >= max_resolve:
                    break
                if is_blocked(ref, cfg=config):
                    stats["blocked_skipped"] += 1
                    continue
                ok, why = guard.allow("resolve_username")
                if not ok:
                    stats["stopped_reason"] = why
                    break
                ok2, why2 = guard.allow("profile_sample")
                if not ok2:
                    stats["stopped_reason"] = why2
                    break
                try:
                    row = await _safe_call(
                        guard,
                        lambda r=ref: resolve_and_profile(
                            client, r, sample=enrich_sample, query=f"snowball:{parent}"
                        ),
                        label=f"profile {ref}",
                    )
                except (FloodWaitError, PeerFloodError, RuntimeError):
                    stats["stopped_reason"] = stats["stopped_reason"] or "flood_or_circuit"
                    break
                except Exception as exc:  # noqa: BLE001
                    logger.warning("resolve failed %s: %s", ref, type(exc).__name__)
                    stats["errors"] += 1
                    await guard.sleep("resolve")
                    continue

                guard.record("resolve_username")
                guard.record("profile_sample")
                if not row:
                    stats["errors"] += 1
                    continue
                row["parent_seed"] = parent
                row["snowball_hop"] = hop
                stats["resolved"] += 1
                try:
                    before = ref.lower() in known
                    catalog.upsert_from_search(row, method="snowball_deep", save=False)
                    if not before:
                        stats["new_upserts"] += 1
                        known.add(ref.lower())
                    v = row.get("verdict")
                    if v in stats:
                        stats[v] += 1
                    # Feed next hop with promising seeds (keep/review with username)
                    if (
                        hop < hops
                        and row.get("username")
                        and v in {"keep", "review"}
                        and float(row.get("identity_score") or 0) >= min_next_identity
                        and not is_blocked(str(row.get("ref") or row.get("username")), cfg=config)
                    ):
                        next_seeds.append(row)
                    logger.info(
                        "  @ %s kind=%s post=%s v=%s rank=%s parent=%s",
                        row.get("ref"),
                        row.get("kind"),
                        row.get("members_can_send"),
                        row.get("verdict"),
                        row.get("rank_score"),
                        parent,
                    )
                except ValueError:
                    stats["errors"] += 1
                await guard.sleep("resolve")

            # Peek invites ONLY (never join unless explicitly enabled — still default off)
            peeked = 0
            for inv_url, parent in invite_candidates:
                if peeked >= max_invite_peek or stats["new_upserts"] >= max_new:
                    break
                ok, why = guard.allow("invite_peek")
                if not ok:
                    stats["stopped_reason"] = why
                    break
                h = invite_hash(inv_url)
                if not h:
                    continue
                try:
                    checked = await _safe_call(
                        guard,
                        lambda hh=h: client(CheckChatInviteRequest(hh)),
                        label=f"invite_peek {h[:8]}",
                    )
                except (InviteHashExpiredError, InviteHashInvalidError):
                    stats["errors"] += 1
                    await guard.sleep("invite_peek")
                    continue
                except (FloodWaitError, PeerFloodError, RuntimeError):
                    stats["stopped_reason"] = stats["stopped_reason"] or "flood_or_circuit"
                    break
                except RPCError as exc:
                    logger.debug("invite peek rpc %s: %s", type(exc).__name__, exc)
                    stats["errors"] += 1
                    await guard.sleep("invite_peek")
                    continue

                guard.record("invite_peek")
                peeked += 1
                stats["invite_peeked"] += 1

                row: dict[str, Any] | None = None
                if isinstance(checked, ChatInviteAlready):
                    # Already a member — safe to profile without joining
                    chat = getattr(checked, "chat", None)
                    uname = getattr(chat, "username", None)
                    if uname:
                        try:
                            row = await resolve_and_profile(
                                client,
                                f"@{uname}",
                                sample=enrich_sample,
                                query=f"snowball_invite_already:{parent}",
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.debug("already-member profile failed: %s", type(exc).__name__)
                    if row is None:
                        row = _invite_row_from_peek(inv_url, checked, parent=parent)
                        if chat is not None:
                            row["id"] = getattr(chat, "id", None)
                            row["username"] = getattr(chat, "username", None)
                            if row.get("username"):
                                row["ref"] = f"@{row['username']}"
                elif isinstance(checked, (ChatInvite, ChatInvitePeek)):
                    # Peek metadata only — DO NOT join
                    row = _invite_row_from_peek(inv_url, checked, parent=parent)
                    if guard.allow_joins():
                        logger.info(
                            "joins enabled in config but deep snowball still peeks only "
                            "(join path reserved for a dedicated inspector)"
                        )
                else:
                    await guard.sleep("invite_peek")
                    continue

                if row:
                    row["snowball_hop"] = hop
                    row["parent_seed"] = parent
                    try:
                        key_ref = str(row.get("ref") or "").lower()
                        before = key_ref in known
                        catalog.upsert_from_search(row, method="snowball_invite_peek", save=False)
                        if not before:
                            stats["new_upserts"] += 1
                            known.add(key_ref)
                        v = row.get("verdict")
                        if v in stats:
                            stats[v] += 1
                        logger.info(
                            "  + peek %s kind=%s v=%s rank=%s title=%s",
                            row.get("ref"),
                            row.get("kind"),
                            row.get("verdict"),
                            row.get("rank_score"),
                            row.get("title"),
                        )
                    except ValueError:
                        stats["errors"] += 1

                await guard.sleep("invite_peek")

            if hop < hops and next_seeds:
                # Dedupe next hop seeds
                seen_u: set[str] = set()
                uniq: list[dict[str, Any]] = []
                for s in next_seeds:
                    u = str(s.get("username") or "").lower()
                    if not u or u in seen_u:
                        continue
                    seen_u.add(u)
                    uniq.append(s)
                seed_queue = uniq[:seed_limit]
                await guard.sleep("hop")
            else:
                break

        catalog.save()
        cat_cfg = config.get("catalog") or {}
        catalog.export_promo_ready(limit=int(cat_cfg.get("promo_limit") or 200))
        stats["safety"] = guard.snapshot()
        stats["catalog_counts"] = catalog.counts()
        return stats
    finally:
        if created_client and own_client:
            await safe_disconnect(client)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Deep safe snowball لینکدونی discovery")
    p.add_argument("--session", default=None)
    p.add_argument("--verbose", action="store_true")
    return p


def main() -> None:
    setup_stdio()
    args = build_parser().parse_args()
    setup_logging(verbose=args.verbose)
    stats = asyncio.run(run_snowball(session=args.session))
    import json

    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
