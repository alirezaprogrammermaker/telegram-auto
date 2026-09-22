"""Limited experimental joins to resolve unknown postable flags.

Picks high-signal catalog rows where ``members_can_send`` is unknown, joins
briefly, re-profiles rights, updates the catalog, then leaves (by default).
Hard-capped by ``safety.daily_joins`` via SafetyGuard.
"""
from __future__ import annotations

import logging
from typing import Any

from telethon.errors import (
    FloodWaitError,
    PeerFloodError,
    RPCError,
    UserAlreadyParticipantError,
)
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
from telethon.tl.types import Channel

from experiments.linkdir_finders.catalog import LinkDirCatalog
from experiments.linkdir_finders.enrich import apply_rank, enrich_profile, sample_activity
from experiments.linkdir_finders.safety_guard import SafetyGuard
from experiments.linkdir_finders.settings import load_config
from experiments.linkdir_finders.tg import safe_disconnect

logger = logging.getLogger("linkdir_finders.verify_postable")


def select_verify_candidates(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    min_rank: float,
    min_identity: float,
) -> list[dict[str, Any]]:
    """Pick public groups with unknown send rights that look worth verifying."""
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("members_can_send") is not None:
            continue
        if str(row.get("verdict") or "").lower() == "junk":
            continue
        if str(row.get("status") or "").lower() == "junk":
            continue
        username = str(row.get("username") or "").strip().lstrip("@")
        if not username:
            continue
        kind = str(row.get("kind") or "").lower()
        if kind in {"broadcast_channel"}:
            continue
        # Prefer real groups when ranking ties — channels rarely become postable.
        kind_bonus = 0.0
        if kind in {"megagroup", "gigagroup"} or row.get("megagroup") or row.get("is_group"):
            kind_bonus = 5.0
        try:
            rank = float(row.get("rank_score") or 0)
        except (TypeError, ValueError):
            rank = 0.0
        try:
            identity = float(row.get("identity_score") or 0)
        except (TypeError, ValueError):
            identity = 0.0
        if rank < min_rank or identity < min_identity:
            continue
        scored.append((rank + identity / 100.0 + kind_bonus, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [row for _score, row in scored[: max(0, limit)]]


def _load_verify_pool(catalog: LinkDirCatalog, *, pool_limit: int) -> list[dict[str, Any]]:
    """Merge review-first rows so unknown-postable groups are actually reachable."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    batches = (
        catalog.list_items(status="review", limit=pool_limit),
        # Legacy promo_ready rows often lack members_can_send; they never sit in review.
        catalog.list_items(promo_ready=True, limit=pool_limit),
        catalog.list_items(limit=pool_limit),
    )
    try:
        local_extra = catalog._local_list_items(limit=max(pool_limit, 100))
    except Exception:  # noqa: BLE001
        local_extra = []
    for batch in (*batches, local_extra):
        for row in batch or []:
            if not isinstance(row, dict):
                continue
            key = str(row.get("username") or row.get("ref") or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows


async def _leave_quietly(client: Any, entity: Any) -> None:
    try:
        await client(LeaveChannelRequest(entity))
    except Exception as exc:  # noqa: BLE001
        logger.debug("leave after verify failed: %s", type(exc).__name__)


async def run_verify_postable(
    *,
    session: str | None = None,
    cfg: dict[str, Any] | None = None,
    client: Any | None = None,
    own_client: bool = True,
    collector_id: str | None = None,
) -> dict[str, Any]:
    config = cfg or load_config()
    safety = config.get("safety") or {}
    vcfg = config.get("verify_postable") or {}
    guard = SafetyGuard(safety, collector_id=collector_id)
    catalog = LinkDirCatalog(collector_id=collector_id)

    stats: dict[str, Any] = {
        "method": "verify_postable_join",
        "enabled": guard.allow_joins(),
        "candidates": 0,
        "joined": 0,
        "already_member": 0,
        "verified_true": 0,
        "verified_false": 0,
        "still_unknown": 0,
        "left": 0,
        "upserted": 0,
        "errors": 0,
        "skipped_reason": None,
        "safety": guard.snapshot(),
    }

    if not guard.allow_joins():
        stats["skipped_reason"] = "joins_disabled"
        logger.info("verify_postable skipped: allow_joins/daily_joins disabled")
        return stats

    experiment_until = str(vcfg.get("experiment_until") or "").strip()
    if experiment_until:
        from datetime import date

        try:
            until = date.fromisoformat(experiment_until[:10])
            if date.today() > until:
                stats["skipped_reason"] = f"experiment_ended:{experiment_until}"
                logger.info(
                    "verify_postable skipped: experiment ended on %s", experiment_until
                )
                return stats
        except ValueError:
            pass

    limit = max(1, min(20, int(vcfg.get("per_run_limit") or 6)))
    min_rank = float(vcfg.get("min_rank") or 50)
    min_identity = float(vcfg.get("min_identity") or 35)
    sample_n = max(0, int(vcfg.get("sample") or 15))
    leave_after = bool(vcfg.get("leave_after", True))
    pool_limit = max(limit * 20, 80)

    # Top-N list_items prefers promo_ready keeps (already known postable). Unknown
    # send-rights were demoted to status=review — pull that queue first or we
    # burn the experiment join budget on empty candidate sets.
    rows = _load_verify_pool(catalog, pool_limit=pool_limit)
    candidates = select_verify_candidates(
        rows,
        limit=limit,
        min_rank=min_rank,
        min_identity=min_identity,
    )
    stats["candidates"] = len(candidates)
    if not candidates:
        stats["skipped_reason"] = "no_candidates"
        logger.info("verify_postable: no candidates")
        return stats

    created_client = client is None
    if client is None:
        from experiments.linkdir_finders.tg import connect_client

        client, _app = await connect_client(session=session)

    try:
        for row in candidates:
            ok_budget, why = guard.allow("join")
            if not ok_budget:
                logger.info("verify_postable stop: %s", why)
                stats["skipped_reason"] = why
                break

            username = str(row.get("username") or "").strip().lstrip("@")
            ref = f"@{username}"
            try:
                entity = await client.get_entity(username)
            except Exception as exc:  # noqa: BLE001
                logger.warning("verify resolve failed %s: %s", ref, type(exc).__name__)
                stats["errors"] += 1
                await guard.sleep("resolve")
                continue

            if not isinstance(entity, Channel):
                logger.info("verify skip %s: not a channel/supergroup", ref)
                continue

            joined_now = False
            try:
                await client(JoinChannelRequest(entity))
                joined_now = True
                stats["joined"] += 1
                guard.record("join")
            except UserAlreadyParticipantError:
                stats["already_member"] += 1
                guard.record("join")
            except FloodWaitError as exc:
                guard.note_flood_wait(int(exc.seconds))
                stats["errors"] += 1
                logger.warning("verify FloodWait %ss — circuit open", exc.seconds)
                break
            except PeerFloodError:
                guard.note_peer_flood()
                stats["errors"] += 1
                logger.warning("verify PeerFlood — circuit open")
                break
            except RPCError as exc:
                logger.warning("verify join failed %s: %s", ref, type(exc).__name__)
                stats["errors"] += 1
                await guard.sleep("resolve")
                continue

            try:
                # Refresh entity after join so banned_rights are complete.
                entity = await client.get_entity(username)
                profile = await enrich_profile(client, entity)
                activity = await sample_activity(client, entity, sample=sample_n)
                updated = dict(row)
                updated.update(
                    {
                        "ref": ref,
                        "username": username,
                        "title": getattr(entity, "title", None) or row.get("title"),
                        "id": getattr(entity, "id", None) or row.get("id"),
                        "kind": profile.get("kind"),
                        "is_channel": profile.get("is_channel"),
                        "is_group": profile.get("is_group"),
                        "broadcast": profile.get("broadcast"),
                        "megagroup": profile.get("megagroup"),
                        "gigagroup": profile.get("gigagroup"),
                        "members_can_send": profile.get("members_can_send"),
                        "postable": profile.get("postable"),
                        "participants": profile.get("participants") or row.get("participants"),
                        "about": profile.get("about") or row.get("about"),
                        "activity": activity,
                        "verified_postable_via": "join",
                    }
                )
                apply_rank(updated)
                catalog.upsert_from_search(
                    updated, method="verify_postable_join", save=False
                )
                stats["upserted"] += 1
                mcs = updated.get("members_can_send")
                if mcs is True:
                    stats["verified_true"] += 1
                elif mcs is False:
                    stats["verified_false"] += 1
                else:
                    stats["still_unknown"] += 1
                logger.info(
                    "verify %s postable=%s verdict=%s rank=%s joined_now=%s",
                    ref,
                    mcs,
                    updated.get("verdict"),
                    updated.get("rank_score"),
                    joined_now,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("verify profile failed %s: %s", ref, type(exc).__name__)
                stats["errors"] += 1
            finally:
                if leave_after and joined_now:
                    await _leave_quietly(client, entity)
                    stats["left"] += 1

            await guard.sleep("resolve")

        catalog.save()
        cat_cfg = config.get("catalog") or {}
        catalog.export_promo_ready(limit=int(cat_cfg.get("promo_limit") or 200))
        stats["safety"] = guard.snapshot()
        stats["catalog_counts"] = catalog.counts()
        try:
            from datetime import datetime, timezone

            from app.paths import ensure_pool_dir, pool_path
            from app.storage import save_json

            ensure_pool_dir()
            save_json(
                pool_path("linkdir_verify_last.json"),
                {
                    "at": datetime.now(timezone.utc)
                    .replace(microsecond=0)
                    .isoformat(),
                    **stats,
                },
            )
        except Exception:  # noqa: BLE001
            logger.debug("verify last-run snapshot failed", exc_info=True)
        return stats
    finally:
        if created_client and own_client:
            await safe_disconnect(client)
