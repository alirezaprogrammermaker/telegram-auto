"""Slow inspector: join → check antispam bots → leave. Hard daily caps."""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    PeerFloodError,
    RPCError,
    UserAlreadyParticipantError,
)
from telethon.tl.functions.channels import (
    GetFullChannelRequest,
    GetParticipantsRequest,
    LeaveChannelRequest,
)
from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest
from telethon.tl.types import (
    Channel,
    ChannelParticipantsAdmins,
    ChatInvite,
    ChatInviteAlready,
    ChatInvitePeek,
    User,
)

from app.base import BaseModule
from app.metrics_catalog import Discovery
from app.paths import account_id, data_path
from app.storage import load_json, save_json
from app.telemetry import incr
from modules.channel_forward.refs import invite_hash
from modules.group_pool.pool import (
    GroupPool,
    looks_like_antispam,
    normalize_group_ref,
    utc_now,
)

logger = logging.getLogger(__name__)


class GroupInspectModule(BaseModule):
    name = "group_inspect"

    def __init__(self, client: TelegramClient, config: dict[str, Any]) -> None:
        super().__init__(client, config)
        self.dry_run = bool(config.get("dry_run", True))
        self.paused = bool(config.get("paused", False))
        self.daily_join_budget = max(1, min(12, int(config.get("daily_join_budget") or 4)))
        self.delay_min_seconds = float(config.get("delay_min_seconds") or 1800)  # 30m
        self.delay_max_seconds = float(config.get("delay_max_seconds") or 10800)  # 3h
        if self.delay_max_seconds < self.delay_min_seconds:
            self.delay_max_seconds = self.delay_min_seconds
        self.timezone = str(config.get("timezone") or "Asia/Tehran")
        self.leave_after = bool(config.get("leave_after", True))
        self.pool = GroupPool()
        self._state_path = data_path("inspect_safety.json")
        self._state = load_json(
            self._state_path,
            {
                "joins": [],
                "paused_until": None,
                "pause_reason": None,
                "skip_keys": [],
            },
        )
        self._worker: asyncio.Task[None] | None = None
        self._stopping = False
        self._dry_seen: set[str] = set()

    async def start(self) -> None:
        self._stopping = False
        self._worker = asyncio.create_task(self._loop())
        logger.info(
            "group_inspect started dry_run=%s budget=%s/day delay=%s-%ss paused=%s",
            self.dry_run,
            self.daily_join_budget,
            int(self.delay_min_seconds),
            int(self.delay_max_seconds),
            self.paused,
        )

    async def stop(self) -> None:
        self._stopping = True
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None

    def _save_state(self) -> None:
        save_json(self._state_path, self._state)

    def _tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except Exception:
            return ZoneInfo("UTC")

    def _paused_until(self) -> datetime | None:
        raw = self._state.get("paused_until")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except Exception:
            return None

    def _joins_today(self) -> int:
        today = datetime.now(self._tz()).date().isoformat()
        count = 0
        for row in self._state.get("joins") or []:
            if not isinstance(row, dict):
                continue
            at = str(row.get("at") or "")
            try:
                dt = datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(self._tz())
            except Exception:
                continue
            if dt.date().isoformat() == today:
                count += 1
        return count

    def _note_join(self, ref: str, result: str) -> None:
        joins = self._state.setdefault("joins", [])
        if not isinstance(joins, list):
            joins = []
            self._state["joins"] = joins
        joins.append({"at": utc_now(), "ref": ref, "result": result})
        self._state["joins"] = joins[-200:]
        self._save_state()
        incr(Discovery.JOINED if result == "done" else Discovery.JOIN_FAILED)
        incr(Discovery.INSPECTED)

    def _open_circuit(self, hours: float, reason: str) -> None:
        until = datetime.now(timezone.utc) + timedelta(hours=hours)
        self._state["paused_until"] = until.isoformat()
        self._state["pause_reason"] = reason
        self._save_state()
        logger.warning("group_inspect circuit open until %s (%s)", until.isoformat(), reason)
        try:
            from app.control_plane_alert import post_admin_bot_alert

            post_admin_bot_alert(
                account_id=account_id(),
                message=f"inspect circuit OPEN until {until.isoformat()}: {reason}",
                severity="critical",
            )
        except Exception:
            logger.debug("control-plane alert skipped", exc_info=True)

    async def _loop(self) -> None:
        # Stagger start so many inspectors don't sync
        await asyncio.sleep(random.uniform(15, 90))
        while not self._stopping:
            try:
                wait = await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("group_inspect tick failed")
                wait = 300.0
            await asyncio.sleep(max(30.0, wait))

    async def _tick(self) -> float:
        if self.paused:
            return 120.0
        until = self._paused_until()
        if until and datetime.now(timezone.utc) < until.astimezone(timezone.utc):
            return 180.0
        if self._joins_today() >= self.daily_join_budget:
            return 600.0

        skip = set(self._state.get("skip_keys") or []) | self._dry_seen
        item = self.pool.next_raw(exclude_keys=skip)
        if not item:
            return 300.0

        ref = str(item.get("ref") or "")
        key = str(item.get("key") or "")
        delay = random.uniform(self.delay_min_seconds, self.delay_max_seconds)
        logger.info(
            "group_inspect next=%s dry_run=%s sleep=%.0fs budget=%s/%s",
            ref,
            self.dry_run,
            delay,
            self._joins_today(),
            self.daily_join_budget,
        )
        await asyncio.sleep(delay)
        if self._stopping or self.paused:
            return 60.0

        if self.dry_run:
            if key:
                self._dry_seen.add(key)
            logger.info("group_inspect DRY-RUN would inspect %s (no join, status unchanged)", ref)
            return random.uniform(60, 180)

        try:
            result = await self._inspect_one(ref)
        except FloodWaitError as exc:
            self._open_circuit(max(8.0, exc.seconds / 3600.0), f"FloodWait {exc.seconds}s")
            self._note_join(ref, "flood_wait")
            return 300.0
        except PeerFloodError:
            self._open_circuit(48.0, "PeerFlood")
            self._note_join(ref, "peer_flood")
            return 300.0
        except Exception as exc:
            logger.error("group_inspect failed %s: %s", ref, exc)
            self.pool.set_status(
                ref,
                "rejected",
                inspect={
                    "at": utc_now(),
                    "account": account_id(),
                    "reason": f"error:{type(exc).__name__}",
                    "detail": str(exc)[:200],
                },
            )
            self._note_join(ref, "error")
            if key:
                skips = list(self._state.get("skip_keys") or [])
                if key not in skips:
                    skips.append(key)
                self._state["skip_keys"] = skips[-500:]
                self._save_state()
            return random.uniform(120, 300)

        self._note_join(ref, result.get("status", "done"))
        return random.uniform(90, 240)

    async def _inspect_one(self, ref: str) -> dict[str, Any]:
        entity = None
        joined = False
        title = None
        bots_hit: list[str] = []

        inv = invite_hash(ref)
        if inv:
            try:
                checked = await self.client(CheckChatInviteRequest(inv))
            except (InviteHashExpiredError, InviteHashInvalidError) as exc:
                self.pool.set_status(
                    ref,
                    "rejected",
                    inspect={
                        "at": utc_now(),
                        "account": account_id(),
                        "reason": type(exc).__name__,
                    },
                )
                return {"status": "rejected"}
            except RPCError:
                checked = None

            if isinstance(checked, ChatInviteAlready):
                entity = checked.chat
            elif isinstance(checked, (ChatInvite, ChatInvitePeek)):
                title = getattr(checked, "title", None)
                # Prefer join only when we must scan members
                try:
                    updates = await self.client(ImportChatInviteRequest(inv))
                    joined = True
                    chats = getattr(updates, "chats", None) or []
                    entity = chats[0] if chats else None
                except UserAlreadyParticipantError:
                    entity = await self.client.get_entity(ref)
                except Exception:
                    raise
            else:
                entity = await self.client.get_entity(ref)
        else:
            norm = normalize_group_ref(ref) or ref
            entity = await self.client.get_entity(norm)
            # Public groups: join if not member so we can scan admins
            try:
                from telethon.tl.functions.channels import JoinChannelRequest

                if isinstance(entity, Channel):
                    await self.client(JoinChannelRequest(entity))
                    joined = True
            except UserAlreadyParticipantError:
                pass
            except Exception:
                # May already be member or join forbidden — continue with what we have
                pass

        if entity is None:
            self.pool.set_status(
                ref,
                "rejected",
                inspect={
                    "at": utc_now(),
                    "account": account_id(),
                    "reason": "unresolved",
                },
            )
            return {"status": "rejected"}

        title = title or getattr(entity, "title", None)
        if isinstance(entity, Channel) and getattr(entity, "broadcast", False):
            status = "rejected"
            reason = "is_channel_not_group"
        else:
            bots_hit = await self._scan_antispam(entity)
            if bots_hit:
                status = "rejected"
                reason = "antispam_bots"
            else:
                status = "inspected_ok"
                reason = "no_known_antispam"

        self.pool.set_status(
            ref,
            status,
            title=str(title) if title else None,
            inspect={
                "at": utc_now(),
                "account": account_id(),
                "reason": reason,
                "bots": bots_hit,
                "joined": joined,
            },
        )

        if self.leave_after and joined and isinstance(entity, Channel):
            try:
                await self.client(LeaveChannelRequest(entity))
            except Exception as exc:
                logger.debug("leave failed %s: %s", ref, exc)

        return {"status": status, "bots": bots_hit}

    async def _scan_antispam(self, entity: Any) -> list[str]:
        hits: list[str] = []
        try:
            result = await self.client(
                GetParticipantsRequest(
                    entity,
                    ChannelParticipantsAdmins(),
                    offset=0,
                    limit=50,
                    hash=0,
                )
            )
        except Exception as exc:
            logger.debug("admin scan failed: %s", exc)
            result = None

        users = getattr(result, "users", None) or []
        for user in users:
            if not isinstance(user, User):
                continue
            if not getattr(user, "bot", False):
                # Still check names of non-bots that look like antispam titles
                if looks_like_antispam(user.username, f"{user.first_name or ''} {user.last_name or ''}"):
                    hits.append(user.username or str(user.id))
                continue
            if looks_like_antispam(user.username, f"{user.first_name or ''} {user.last_name or ''}"):
                hits.append(user.username or str(user.id))

        # Full channel about text sometimes mentions protectors
        try:
            if isinstance(entity, Channel):
                full = await self.client(GetFullChannelRequest(entity))
                about = getattr(getattr(full, "full_chat", None), "about", "") or ""
                if looks_like_antispam(None, about):
                    hits.append("about_text")
        except Exception:
            pass

        # Dedupe
        out: list[str] = []
        seen: set[str] = set()
        for h in hits:
            if h in seen:
                continue
            seen.add(h)
            out.append(h)
        return out
