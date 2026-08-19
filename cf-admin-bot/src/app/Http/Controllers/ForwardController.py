"""Forward panel — channel_forward profile + queue ops + quick-setup wizard."""
from __future__ import annotations

from app.Models.User import User
from app.Models.UserState import UserState
from app.Services.AccountScaffoldService import validate_account_id
from app.Services.AccountService import AccountConflictError, AccountService
from app.Services.ForwardJobService import ForwardJobService
from app.Services.GitHubService import GitHubError
from app.Services.ProfileConfigService import ProfileConfigService
from app.Services.RunOrchestratorService import RunOrchestratorService
from app.Services.StatusService import StatusService
from app.Services.TelegramService import TelegramService
from app.Support.GithubFactory import make_github, make_scaffold
from app.Support.Lang import __
from config.bot import BotConfig
from app.Support.ErrorFormat import friendly_error
from app.Support.StatusFormat import format_live_metrics, format_run_line
from config.menus import (
    accounts_pick_keyboard,
    forward_advanced_keyboard,
    forward_filter_keyboard,
    forward_menu_keyboard,
    forward_routes_keyboard,
    forward_schedule_keyboard,
    forward_setup_keyboard,
    main_keyboard,
    queue_clear_confirm_keyboard,
)

FORWARD_PICK_ROLES = ("forward", "full")
CANCEL_TEXTS = frozenset({"/cancel", "انصراف"})

ST_FWD_SETUP = "forward_setup"
ST_FWD_QUEUE_CLEAR_CONFIRM = "forward_queue_clear_confirm"
ST_FWD_PICK = "forward_pick"
ST_FWD_ROUTE_ADD = "forward_route_add"
ST_FWD_ROUTE_SET = "forward_route_set"
ST_FWD_ROUTE_SOURCE = "forward_route_source"
ST_FWD_ROUTE_MODE = "forward_route_mode"
ST_FWD_ROUTE_VISIBILITY = "forward_route_visibility"
ST_FWD_DEST_ADD = "forward_dest_add"
ST_FWD_DEST_REMOVE = "forward_dest_remove"
ST_FWD_FILTER_CMD = "forward_filter_cmd"
ST_FWD_SCHEDULE_CMD = "forward_schedule_cmd"
ST_FWD_MEDIA_CMD = "forward_media_cmd"
ST_FWD_DEDUP_CMD = "forward_dedup_cmd"
ST_FWD_DELIVERY_CMD = "forward_delivery_cmd"
ST_FWD_IMPORT = "forward_import"


class ForwardController:
    def __init__(self, tg: TelegramService, config: BotConfig) -> None:
        self.tg = tg
        self.config = config
        self.db = config.db

    def _jobs(self) -> ForwardJobService:
        return ForwardJobService(self.db)

    def _status(self) -> StatusService:
        return StatusService(self.db, make_github(self.config))

    def _profile(self) -> ProfileConfigService | None:
        scaffold = make_scaffold(self.config)
        if not scaffold:
            return None
        return ProfileConfigService(self.db, scaffold)

    def _runner(self) -> RunOrchestratorService | None:
        gh = make_github(self.config)
        if not gh:
            return None
        return RunOrchestratorService(self.db, gh)

    @staticmethod
    def _is_bad_ref(text: str) -> bool:
        t = (text or "").strip()
        return (
            not t
            or t.startswith("/")
            or t in {__("accounts.btn_cancel"), __("accounts.btn_back")}
        )

    @staticmethod
    def _parse_source_dest(text: str) -> tuple[str, str]:
        parts = (text or "").strip().split(None, 1)
        if len(parts) < 2:
            raise GitHubError("need source and dest")
        return parts[0], parts[1]

    @staticmethod
    def _parse_source_mode(text: str) -> tuple[str, str]:
        parts = (text or "").strip().split(None, 1)
        if len(parts) < 2:
            raise GitHubError("need source and mode")
        mode = parts[1].strip().lower()
        if mode not in {"forward", "copy"}:
            raise GitHubError("mode must be forward|copy")
        return parts[0], mode

    @staticmethod
    def _parse_source_visibility(text: str) -> tuple[str, str]:
        parts = (text or "").strip().split(None, 1)
        if len(parts) < 2:
            raise GitHubError("need source and visibility")
        vis = parts[1].strip().lower()
        if vis not in {"public", "private", "pub", "عمومی"}:
            raise GitHubError("visibility must be public|private")
        return parts[0], vis

    @staticmethod
    def _parse_import_line(text: str) -> tuple[str, str]:
        parts = (text or "").strip().rsplit(None, 1)
        if len(parts) < 2:
            raise GitHubError("need sources and dest")
        return parts[0], parts[1]

    async def show_forward(self, chat_id: int, user: User) -> None:
        tid = int(user.get("telegram_id"))
        await UserState.clear(self.db, tid)
        snap = await self._status().forward_snapshot(tid)
        body = "\n".join(
            [
                __("forward.header"),
                self._format_lines(snap, empty_key="forward.empty"),
                __("forward.help"),
            ]
        )
        await self.tg.send_message(
            chat_id, body, reply_markup=forward_menu_keyboard()
        )

    @staticmethod
    def _format_lines(snap: dict, *, empty_key: str) -> str:
        accounts = snap.get("accounts") or []
        if not accounts:
            return __(empty_key)
        lines = []
        for row in accounts:
            on = "✅ فعال" if row.get("enabled") else "⏸ غیرفعال"
            run_bit = format_run_line(
                row.get("run_id"),
                row.get("run_status"),
                row.get("run_conclusion"),
                row.get("run_url"),
            )
            live_bit = format_live_metrics(row)
            url = row.get("run_url") or ""
            lines.append(
                __(
                    "status.line",
                    id=row.get("id"),
                    on=on,
                    role=row.get("role"),
                    status=row.get("status"),
                    live=live_bit,
                    run=run_bit,
                    url=url,
                )
            )
        return "\n".join(lines)

    async def _show_live_queue_if_fresh(
        self, chat_id: int, user: User, account_id: str, queue_name: str
    ) -> bool:
        tid = int(user.get("telegram_id"))
        snap = await self._status().forward_snapshot(tid)
        for row in snap.get("accounts") or []:
            if str(row.get("id") or "") != account_id:
                continue
            if row.get("heartbeat_stale"):
                return False
            pending = row.get("forward_queue_pending")
            if pending is None:
                return False
            await self.tg.send_message(
                chat_id,
                __("cache.queue_status", account_id=account_id, queue=queue_name, pending=pending, url=""),
                reply_markup=forward_menu_keyboard(),
            )
            return True
        return False

    async def handle(self, chat_id: int, user: User, text: str) -> bool:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        t = (text or "").strip()
        current = str(state.get("state") or "")

        cancel_set = CANCEL_TEXTS | {__("accounts.btn_cancel")}
        if t in cancel_set and current.startswith("forward_"):
            await UserState.clear(self.db, tid)
            await self.tg.send_message(
                chat_id, __("panel.cancelled"), reply_markup=main_keyboard()
            )
            return True

        if current == ST_FWD_SETUP:
            await self._handle_setup(chat_id, user, t)
            return True
        if current == ST_FWD_QUEUE_CLEAR_CONFIRM:
            await self._finish_fwd_queue_clear_confirm(chat_id, user, t)
            return True
        if current == ST_FWD_PICK:
            await self._finish_pick(chat_id, user, t)
            return True
        if current == ST_FWD_ROUTE_ADD:
            await self._finish_route_add(chat_id, user, t)
            return True
        if current == ST_FWD_ROUTE_SET:
            await self._finish_route_set(chat_id, user, t)
            return True
        if current == ST_FWD_ROUTE_SOURCE:
            await self._finish_route_source(chat_id, user, t)
            return True
        if current == ST_FWD_ROUTE_MODE:
            await self._finish_route_mode(chat_id, user, t)
            return True
        if current == ST_FWD_ROUTE_VISIBILITY:
            await self._finish_route_visibility(chat_id, user, t)
            return True
        if current == ST_FWD_DEST_ADD:
            await self._finish_dest_add(chat_id, user, t)
            return True
        if current == ST_FWD_DEST_REMOVE:
            await self._finish_dest_remove(chat_id, user, t)
            return True
        if current == ST_FWD_FILTER_CMD:
            await self._finish_filter_cmd(chat_id, user, t)
            return True
        if current == ST_FWD_SCHEDULE_CMD:
            await self._finish_schedule_cmd(chat_id, user, t)
            return True
        if current == ST_FWD_MEDIA_CMD:
            await self._finish_media_cmd(chat_id, user, t)
            return True
        if current == ST_FWD_DEDUP_CMD:
            await self._finish_dedup_cmd(chat_id, user, t)
            return True
        if current == ST_FWD_DELIVERY_CMD:
            await self._finish_delivery_cmd(chat_id, user, t)
            return True
        if current == ST_FWD_IMPORT:
            await self._finish_import(chat_id, user, t)
            return True

        if t in {
            __("menu.btn_forward"),
            "فوروارد",
            "📨 فوروارد",
            __("forward.btn_refresh"),
        }:
            await self.show_forward(chat_id, user)
            return True

        if t == __("forward.btn_setup"):
            await self._start_setup(chat_id, user)
            return True
        if t == __("forward.btn_jobs"):
            await self._show_jobs(chat_id, user)
            return True

        # Sub-menu entry buttons
        if t == __("forward.btn_sub_routes"):
            await self.tg.send_message(
                chat_id, __("forward.routes_header"), reply_markup=forward_routes_keyboard()
            )
            return True
        if t == __("forward.btn_sub_filter"):
            await self.tg.send_message(
                chat_id, __("forward.filter_header"), reply_markup=forward_filter_keyboard()
            )
            return True
        if t == __("forward.btn_sub_schedule"):
            await self.tg.send_message(
                chat_id, __("forward.schedule_header"), reply_markup=forward_schedule_keyboard()
            )
            return True
        if t == __("forward.btn_sub_advanced"):
            await self.tg.send_message(
                chat_id, __("forward.advanced_header"), reply_markup=forward_advanced_keyboard()
            )
            return True

        # Back from sub-menus
        if t == __("nav.btn_back"):
            await self.show_forward(chat_id, user)
            return True

        btn_map = {
            __("forward.btn_profile_status"): "profile_status",
            __("forward.btn_dry"): "fwd_dry",
            __("forward.btn_pause"): "fwd_pause",
            __("forward.btn_resume"): "fwd_resume",
            __("forward.btn_auto_join_on"): "fwd_auto_join_on",
            __("forward.btn_auto_join_off"): "fwd_auto_join_off",
            __("forward.btn_route_add"): "route_add",
            __("forward.btn_route_remove"): "route_remove",
            __("forward.btn_route_set"): "route_set",
            __("forward.btn_route_pause"): "route_pause",
            __("forward.btn_route_resume"): "route_resume",
            __("forward.btn_route_mode"): "route_mode",
            __("forward.btn_visibility"): "route_visibility",
            __("forward.btn_claim"): "route_claim",
            __("forward.btn_dest_add"): "dest_add",
            __("forward.btn_dest_remove"): "dest_remove",
            __("forward.btn_filter_view"): "filter_view",
            __("forward.btn_filter_on"): "filter_on",
            __("forward.btn_filter_off"): "filter_off",
            __("forward.btn_filter_links"): "filter_links",
            __("forward.btn_filter_mentions"): "filter_mentions",
            __("forward.btn_filter_hashtags"): "filter_hashtags",
            __("forward.btn_filter_prefix"): "filter_prefix",
            __("forward.btn_filter_suffix"): "filter_suffix",
            __("forward.btn_filter_block"): "filter_block",
            __("forward.btn_filter_allow"): "filter_allow",
            __("forward.btn_filter_regex"): "filter_regex",
            __("forward.btn_filter_clear"): "filter_clear",
            __("forward.btn_schedule_view"): "schedule_view",
            __("forward.btn_schedule_on"): "schedule_on",
            __("forward.btn_schedule_off"): "schedule_off",
            __("forward.btn_schedule_tz"): "schedule_tz",
            __("forward.btn_schedule_days"): "schedule_days",
            __("forward.btn_schedule_hours"): "schedule_hours",
            __("forward.btn_schedule_clear"): "schedule_clear",
            __("forward.btn_media"): "media",
            __("forward.btn_dedup"): "dedup",
            __("forward.btn_delivery"): "delivery",
            __("forward.btn_import"): "import",
            __("forward.btn_queue_status"): "forward_queue_status",
            __("forward.btn_queue_clear"): "forward_queue_clear_ask",
        }
        if t in btn_map:
            await self._start_pick(chat_id, user, intent=btn_map[t])
            return True

        return False

    async def _ids_for_roles(self, tid: int) -> list[str]:
        rows = await AccountService(self.db).list_for_user(tid)
        want = {r.lower() for r in FORWARD_PICK_ROLES}
        return [
            str(r.get("id"))
            for r in rows
            if str(r.get("role") or "").lower() in want and r.get("id")
        ]

    async def _start_pick(self, chat_id: int, user: User, *, intent: str) -> None:
        tid = int(user.get("telegram_id"))
        if not self.config.github_ready():
            await self.tg.send_message(
                chat_id,
                __("accounts.missing_github"),
                reply_markup=forward_menu_keyboard(),
            )
            return
        ids = await self._ids_for_roles(tid)
        if not ids:
            await self.tg.send_message(
                chat_id, __("forward.empty"), reply_markup=forward_menu_keyboard()
            )
            return
        await UserState.set_state(self.db, tid, ST_FWD_PICK, {"intent": intent})
        await self.tg.send_message(
            chat_id,
            __("panel.pick_account"),
            reply_markup=accounts_pick_keyboard(ids),
        )

    async def _finish_pick(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        intent = str(state.context.get("intent") or "")
        aid = validate_account_id(t)
        if not aid:
            await self.tg.send_message(chat_id, __("accounts.invalid_id"))
            return

        if intent == "profile_status":
            await UserState.clear(self.db, tid)
            await self._show_profile(chat_id, user, aid)
            return

        if intent == "forward_queue_status":
            await UserState.clear(self.db, tid)
            if not await self._show_live_queue_if_fresh(chat_id, user, aid, "forward"):
                await self._dispatch_cache(chat_id, user, aid, "forward_queue_status")
            return
        if intent == "forward_queue_clear_ask":
            await UserState.set_state(
                self.db, tid, ST_FWD_QUEUE_CLEAR_CONFIRM, {"account_id": aid}
            )
            await self.tg.send_message(
                chat_id,
                __("cache.queue_clear_confirm", account_id=aid),
                reply_markup=queue_clear_confirm_keyboard(),
            )
            return
        if intent == "forward_queue_clear":
            await UserState.clear(self.db, tid)
            await self._dispatch_cache(chat_id, user, aid, "forward_queue_clear")
            return

        if intent == "route_add":
            await UserState.set_state(
                self.db, tid, ST_FWD_ROUTE_ADD, {"account_id": aid}
            )
            await self.tg.send_message(chat_id, __("forward.ask_route_add"))
            return

        if intent == "route_set":
            await UserState.set_state(
                self.db, tid, ST_FWD_ROUTE_SET, {"account_id": aid}
            )
            await self.tg.send_message(chat_id, __("forward.ask_route_set"))
            return

        if intent == "route_mode":
            await UserState.set_state(
                self.db, tid, ST_FWD_ROUTE_MODE, {"account_id": aid}
            )
            await self.tg.send_message(chat_id, __("forward.ask_route_mode"))
            return

        if intent == "route_visibility":
            await UserState.set_state(
                self.db, tid, ST_FWD_ROUTE_VISIBILITY, {"account_id": aid}
            )
            await self.tg.send_message(chat_id, __("forward.ask_route_visibility"))
            return

        if intent == "import":
            await UserState.set_state(
                self.db, tid, ST_FWD_IMPORT, {"account_id": aid}
            )
            await self.tg.send_message(chat_id, __("forward.ask_import"))
            return

        source_intents = {
            "route_remove",
            "route_pause",
            "route_resume",
            "route_claim",
            "filter_view",
            "filter_on",
            "filter_off",
            "filter_links",
            "filter_mentions",
            "filter_hashtags",
            "filter_clear",
            "schedule_view",
            "schedule_on",
            "schedule_off",
            "schedule_clear",
            "media",
            "dedup",
            "delivery",
        }
        if intent in source_intents:
            await UserState.set_state(
                self.db,
                tid,
                ST_FWD_ROUTE_SOURCE,
                {"account_id": aid, "intent": intent},
            )
            await self.tg.send_message(chat_id, __("forward.ask_route_source"))
            return

        cmd_intents = {
            "dest_add": (ST_FWD_DEST_ADD, "forward.ask_dest_add"),
            "dest_remove": (ST_FWD_DEST_REMOVE, "forward.ask_dest_remove"),
            "filter_prefix": (ST_FWD_FILTER_CMD, "forward.ask_filter_prefix"),
            "filter_suffix": (ST_FWD_FILTER_CMD, "forward.ask_filter_suffix"),
            "filter_block": (ST_FWD_FILTER_CMD, "forward.ask_filter_block"),
            "filter_allow": (ST_FWD_FILTER_CMD, "forward.ask_filter_allow"),
            "filter_regex": (ST_FWD_FILTER_CMD, "forward.ask_filter_regex"),
            "schedule_tz": (ST_FWD_SCHEDULE_CMD, "forward.ask_schedule_tz"),
            "schedule_days": (ST_FWD_SCHEDULE_CMD, "forward.ask_schedule_days"),
            "schedule_hours": (ST_FWD_SCHEDULE_CMD, "forward.ask_schedule_hours"),
        }
        if intent in cmd_intents:
            st, msg_key = cmd_intents[intent]
            await UserState.set_state(
                self.db, tid, st, {"account_id": aid, "intent": intent}
            )
            await self.tg.send_message(chat_id, __(msg_key))
            return

        await self._apply_module_intent(chat_id, user, aid, intent)
        await UserState.clear(self.db, tid)

    async def _finish_route_source(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        if self._is_bad_ref(t):
            await self.tg.send_message(chat_id, __("pool.invalid_ref"))
            return
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        intent = str(state.context.get("intent") or "")
        source = t.strip()
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return

        try:
            if intent == "route_remove":
                result = await prof.forward_remove_route(tid, aid, source)
                await UserState.clear(self.db, tid)
                await self._patch_done(chat_id, aid, result)
                return
            if intent == "route_pause":
                result = await prof.forward_set_route_paused(
                    tid, aid, source, paused=True
                )
                await UserState.clear(self.db, tid)
                await self._patch_done(chat_id, aid, result)
                return
            if intent == "route_resume":
                result = await prof.forward_set_route_paused(
                    tid, aid, source, paused=False
                )
                await UserState.clear(self.db, tid)
                await self._patch_done(chat_id, aid, result)
                return
            if intent == "route_claim":
                result = await prof.forward_claim_route(tid, aid, source)
                await UserState.clear(self.db, tid)
                await self._patch_done(chat_id, aid, result)
                return
            if intent in {"filter_view", "filter_on", "filter_off", "filter_clear"}:
                cmd = {
                    "filter_view": "",
                    "filter_on": "on",
                    "filter_off": "off",
                    "filter_clear": "clear",
                }[intent]
                result = await prof.forward_filter_command(tid, aid, source, cmd)
                await UserState.clear(self.db, tid)
                await self._summary_done(chat_id, aid, "filter", result)
                return
            if intent in {"filter_links", "filter_mentions", "filter_hashtags"}:
                key = intent.replace("filter_", "")
                result = await prof.forward_toggle_filter_bool(
                    tid, aid, source, key
                )
                await UserState.clear(self.db, tid)
                await self._patch_done(chat_id, aid, result)
                return
            if intent in {"schedule_view", "schedule_on", "schedule_off", "schedule_clear"}:
                cmd = {
                    "schedule_view": "",
                    "schedule_on": "on",
                    "schedule_off": "off",
                    "schedule_clear": "clear",
                }[intent]
                result = await prof.forward_schedule_command(tid, aid, source, cmd)
                await UserState.clear(self.db, tid)
                await self._summary_done(chat_id, aid, "schedule", result)
                return
            if intent == "media":
                result = await prof.forward_media_command(tid, aid, source, "")
                await UserState.set_state(
                    self.db,
                    tid,
                    ST_FWD_MEDIA_CMD,
                    {"account_id": aid, "source": source},
                )
                lines = result.get("summary") or []
                await self.tg.send_message(
                    chat_id,
                    __("forward.media_status", lines="\n".join(lines)),
                )
                await self.tg.send_message(chat_id, __("forward.ask_media"))
                return
            if intent == "dedup":
                result = await prof.forward_dedup_command(tid, aid, source, "")
                await UserState.set_state(
                    self.db,
                    tid,
                    ST_FWD_DEDUP_CMD,
                    {"account_id": aid, "source": source},
                )
                lines = result.get("summary") or []
                await self.tg.send_message(
                    chat_id,
                    __("forward.dedup_status", lines="\n".join(lines)),
                )
                await self.tg.send_message(chat_id, __("forward.ask_dedup"))
                return
            if intent == "delivery":
                result = await prof.forward_delivery_command(tid, aid, source, "")
                await UserState.set_state(
                    self.db,
                    tid,
                    ST_FWD_DELIVERY_CMD,
                    {"account_id": aid, "source": source},
                )
                lines = result.get("summary") or []
                await self.tg.send_message(
                    chat_id,
                    __("forward.delivery_status", lines="\n".join(lines)),
                )
                await self.tg.send_message(chat_id, __("forward.ask_delivery"))
                return
        except (AccountConflictError, GitHubError, ValueError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return

        await UserState.clear(self.db, tid)
        await self.tg.send_message(chat_id, __("menu.unknown"))

    async def _finish_route_add(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        try:
            source, dest = self._parse_source_dest(t)
            result = await prof.forward_add_route(tid, aid, source, dest)
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        await self._patch_done(chat_id, aid, result, route=result.get("route"))

    async def _finish_route_set(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        try:
            source, dest = self._parse_source_dest(t)
            result = await prof.forward_set_destination(tid, aid, source, dest)
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        await self._patch_done(chat_id, aid, result, route=result.get("route"))

    async def _finish_route_mode(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        try:
            source, mode = self._parse_source_mode(t)
            result = await prof.forward_set_route_mode(tid, aid, source, mode)
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        await self._patch_done(chat_id, aid, result)

    async def _finish_route_visibility(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        try:
            source, vis = self._parse_source_visibility(t)
            result = await prof.forward_set_visibility(tid, aid, source, vis)
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        await self._patch_done(chat_id, aid, result)

    async def _finish_dest_add(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        try:
            source, dest = self._parse_source_dest(t)
            result = await prof.forward_dest_add(tid, aid, source, dest)
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        await self._patch_done(chat_id, aid, result)

    async def _finish_dest_remove(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        try:
            source, dest = self._parse_source_dest(t)
            result = await prof.forward_dest_remove(tid, aid, source, dest)
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        await self._patch_done(chat_id, aid, result)

    async def _finish_filter_cmd(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        intent = str(state.context.get("intent") or "")
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        try:
            if intent in {"filter_prefix", "filter_suffix", "filter_block", "filter_allow", "filter_regex"}:
                parts = t.strip().split(None, 1)
                if len(parts) < 2:
                    raise GitHubError("need source and command")
                source, cmd_tail = parts[0], parts[1]
                cmd = {
                    "filter_prefix": f"prefix {cmd_tail}",
                    "filter_suffix": f"suffix {cmd_tail}",
                    "filter_block": f"block {cmd_tail}",
                    "filter_allow": f"allow {cmd_tail}",
                    "filter_regex": f"regex {cmd_tail}",
                }[intent]
            else:
                raise GitHubError("bad filter intent")
            result = await prof.forward_filter_command(tid, aid, source, cmd)
        except (AccountConflictError, GitHubError, ValueError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        await self._summary_done(chat_id, aid, "filter", result)

    async def _finish_schedule_cmd(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        intent = str(state.context.get("intent") or "")
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        try:
            parts = t.strip().split(None, 1)
            if len(parts) < 2:
                raise GitHubError("need source and schedule command")
            source, tail = parts[0], parts[1]
            cmd = {
                "schedule_tz": f"tz {tail}",
                "schedule_days": f"days {tail}",
                "schedule_hours": f"hours {tail}",
            }[intent]
            result = await prof.forward_schedule_command(tid, aid, source, cmd)
        except (AccountConflictError, GitHubError, ValueError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        await self._summary_done(chat_id, aid, "schedule", result)

    async def _finish_media_cmd(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        source = str(state.context.get("source") or "")
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        try:
            result = await prof.forward_media_command(tid, aid, source, t.strip())
        except (AccountConflictError, GitHubError, ValueError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        await self._summary_done(chat_id, aid, "media", result)

    async def _finish_dedup_cmd(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        source = str(state.context.get("source") or "")
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        try:
            result = await prof.forward_dedup_command(tid, aid, source, t.strip())
        except (AccountConflictError, GitHubError, ValueError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        await self._summary_done(chat_id, aid, "dedup", result)

    async def _finish_delivery_cmd(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        source = str(state.context.get("source") or "")
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        try:
            result = await prof.forward_delivery_command(tid, aid, source, t.strip())
        except (AccountConflictError, GitHubError, ValueError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        await self._summary_done(chat_id, aid, "delivery", result)

    async def _finish_import(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        try:
            sources_csv, dest = self._parse_import_line(t)
            result = await prof.forward_import_routes(tid, aid, sources_csv, dest)
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        await self.tg.send_message(
            chat_id,
            __(
                "forward.import_done",
                account_id=aid,
                added=result.get("added", 0),
            ),
            reply_markup=forward_menu_keyboard(),
        )

    async def _show_profile(self, chat_id: int, user: User, account_id: str) -> None:
        prof = self._profile()
        if not prof:
            await self.tg.send_message(
                chat_id,
                __("accounts.missing_github"),
                reply_markup=forward_menu_keyboard(),
            )
            return
        tid = int(user.get("telegram_id"))
        try:
            desc = await prof.describe_module(tid, account_id, "channel_forward")
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await self.tg.send_message(
            chat_id,
            __(
                "forward.profile_status",
                account_id=account_id,
                enabled=desc.get("enabled"),
                paused=desc.get("paused"),
                dry_run=desc.get("dry_run"),
                auto_join=desc.get("auto_join"),
                route_count=desc.get("route_count", 0),
                routes=desc.get("routes_text") or "—",
            ),
            reply_markup=forward_menu_keyboard(),
        )

    async def _apply_module_intent(
        self, chat_id: int, user: User, account_id: str, intent: str
    ) -> None:
        prof = self._profile()
        if not prof:
            await self.tg.send_message(
                chat_id, __("accounts.missing_github"), reply_markup=main_keyboard()
            )
            return
        tid = int(user.get("telegram_id"))
        try:
            if intent == "fwd_dry":
                result = await prof.toggle_bool(
                    tid, account_id, "channel_forward", "dry_run"
                )
            elif intent == "fwd_pause":
                result = await prof.patch(
                    tid, account_id, "channel_forward", {"paused": True}
                )
            elif intent == "fwd_resume":
                result = await prof.patch(
                    tid, account_id, "channel_forward", {"paused": False}
                )
            elif intent == "fwd_auto_join_on":
                result = await prof.patch(
                    tid, account_id, "channel_forward", {"auto_join": True}
                )
            elif intent == "fwd_auto_join_off":
                result = await prof.patch(
                    tid, account_id, "channel_forward", {"auto_join": False}
                )
            else:
                await self.tg.send_message(chat_id, __("menu.unknown"))
                return
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return

        await self._patch_done(chat_id, account_id, result)

    async def _patch_done(
        self,
        chat_id: int,
        account_id: str,
        result: dict,
        *,
        route: dict | None = None,
    ) -> None:
        detail = str(route or result.get("merged") or "")[:300]
        await self.tg.send_message(
            chat_id,
            __(
                "profile.patch_done",
                account_id=account_id,
                module="channel_forward",
                detail=detail,
            ),
            reply_markup=forward_menu_keyboard(),
        )

    async def _summary_done(
        self, chat_id: int, account_id: str, kind: str, result: dict
    ) -> None:
        lines = result.get("summary") or []
        body = "\n".join(str(x) for x in lines) or "—"
        await self.tg.send_message(
            chat_id,
            __(
                "forward.summary_done",
                account_id=account_id,
                kind=kind,
                lines=body,
            ),
            reply_markup=forward_menu_keyboard(),
        )

    async def _dispatch_cache(
        self, chat_id: int, user: User, account_id: str, action: str
    ) -> None:
        runner = self._runner()
        if not runner:
            await self.tg.send_message(
                chat_id,
                __("accounts.missing_github"),
                reply_markup=forward_menu_keyboard(),
            )
            return
        tid = int(user.get("telegram_id"))
        await self.tg.send_message(chat_id, __("cache.working", action=action))
        try:
            info = await runner.account_cache_admin(
                tid,
                account_id,
                action=action,
                notify_chat_id=chat_id,
            )
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id,
                __("accounts.error", error=friendly_error(exc)),
                reply_markup=forward_menu_keyboard(),
            )
            return
        await self.tg.send_message(
            chat_id,
            __(
                "cache.dispatched",
                action=action,
                account_id=account_id,
                run_id=info.get("run_id") or "-",
                url=info.get("html_url") or "",
            ),
            reply_markup=forward_menu_keyboard(),
        )

    async def _finish_fwd_queue_clear_confirm(
        self, chat_id: int, user: User, t: str
    ) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str((state.context or {}).get("account_id") or "")
        await UserState.clear(self.db, tid)
        if t != __("cache.queue_clear_btn_confirm"):
            await self.tg.send_message(
                chat_id, __("panel.cancelled"), reply_markup=forward_menu_keyboard()
            )
            return
        await self._dispatch_cache(chat_id, user, aid, "forward_queue_clear")

    # ──────────────────────────────────────────────────────────────────
    # Quick-setup wizard
    # ──────────────────────────────────────────────────────────────────

    async def _start_setup(self, chat_id: int, user: User) -> None:
        tid = int(user.get("telegram_id"))
        ids = await self._ids_for_roles(tid)
        await UserState.set_state(self.db, tid, ST_FWD_SETUP, {"step": "account"})
        if ids:
            await self.tg.send_message(
                chat_id,
                __("forward.setup_step1"),
                reply_markup=accounts_pick_keyboard(ids),
            )
        else:
            await self.tg.send_message(
                chat_id,
                __("forward.setup_step1"),
                reply_markup=forward_menu_keyboard(),
            )

    async def _handle_setup(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        cancel_set = CANCEL_TEXTS | {__("accounts.btn_cancel"), __("accounts.btn_back")}
        if t in cancel_set:
            await UserState.clear(self.db, tid)
            await self.tg.send_message(
                chat_id, __("panel.cancelled"), reply_markup=forward_menu_keyboard()
            )
            return

        state = await UserState.get_or_idle(self.db, tid)
        ctx: dict = dict(state.context or {})
        step = ctx.get("step", "account")

        if step == "account":
            aid = validate_account_id(t)
            if not aid:
                await self.tg.send_message(chat_id, __("accounts.invalid_id"))
                return
            ctx["account_id"] = aid
            ctx["step"] = "source"
            await UserState.set_state(self.db, tid, ST_FWD_SETUP, ctx)
            await self.tg.send_message(
                chat_id,
                __("forward.setup_step2", account_id=aid),
                reply_markup=forward_setup_keyboard(),
            )
            return

        if step == "source":
            src = t.strip()
            if not src:
                return
            ctx["source"] = src
            ctx["step"] = "dest"
            await UserState.set_state(self.db, tid, ST_FWD_SETUP, ctx)
            await self.tg.send_message(
                chat_id,
                __("forward.setup_step3", source=src),
                reply_markup=forward_setup_keyboard(),
            )
            return

        if step == "dest":
            dst = t.strip()
            if not dst:
                return
            ctx["destination"] = dst
            ctx["step"] = "filter"
            await UserState.set_state(self.db, tid, ST_FWD_SETUP, ctx)
            await self.tg.send_message(
                chat_id,
                __("forward.setup_step4_filter", destination=dst),
                reply_markup=forward_setup_keyboard(),
            )
            return

        if step == "filter":
            yes_btn = __("forward.setup_btn_yes_filter")
            filter_links = t == yes_btn
            await self._finish_setup(chat_id, user, ctx, filter_links)
            return

        # Unknown step — restart
        await UserState.clear(self.db, tid)
        await self._start_setup(chat_id, user)

    async def _finish_setup(
        self,
        chat_id: int,
        user: User,
        ctx: dict,
        filter_links: bool,
    ) -> None:
        tid = int(user.get("telegram_id"))
        aid = str(ctx.get("account_id") or "")
        source = str(ctx.get("source") or "")
        destination = str(ctx.get("destination") or "")

        await UserState.clear(self.db, tid)
        await self.tg.send_message(chat_id, __("forward.setup_saving"))

        # 1. Persist job in D1
        job_svc = self._jobs()
        job_id = await job_svc.create_job(
            account_id=aid,
            owner_id=tid,
            source=source,
            destination=destination,
            auto_join=True,
            filter_remove_links=filter_links,
        )

        # 2. Sync all enabled jobs for this account → GitHub profile
        jobs = await job_svc.list_for_account(aid)
        enabled_jobs = [j for j in jobs if j.get("enabled")]
        patch = ForwardJobService.build_module_patch(enabled_jobs, auto_join=True)

        profile_svc = self._profile()
        if not profile_svc:
            await self.tg.send_message(
                chat_id,
                __("accounts.missing_github"),
                reply_markup=forward_menu_keyboard(),
            )
            return
        try:
            await profile_svc.scaffold.patch_profile_modules(aid, "channel_forward", patch)
        except Exception as exc:
            await self.tg.send_message(
                chat_id,
                __("accounts.error", error=friendly_error(exc)),
                reply_markup=forward_menu_keyboard(),
            )
            return

        # 3. Trigger workflow immediately
        runner = self._runner()
        run_info: dict = {}
        dispatch_ok = False
        if runner:
            try:
                run_info = await runner.dispatch(tid, aid)
                dispatch_ok = True
                await job_svc.mark_dispatched(
                    job_id,
                    run_id=run_info.get("run_id"),
                    run_status=run_info.get("status") or "queued",
                )
            except Exception as exc:
                err = friendly_error(exc)
                await self.tg.send_message(
                    chat_id,
                    __("forward.setup_dispatch_fail", error=err, job_id=job_id),
                    reply_markup=forward_menu_keyboard(),
                )
                return

        if not runner:
            await self.tg.send_message(
                chat_id,
                __("accounts.missing_github"),
                reply_markup=forward_menu_keyboard(),
            )
            return

        await self.tg.send_message(
            chat_id,
            __(
                "forward.setup_done",
                account_id=aid,
                source=source,
                destination=destination,
                filter_links="✅ روشن" if filter_links else "❌ خاموش",
                job_id=job_id,
            ),
            reply_markup=forward_menu_keyboard(),
        )

    # ──────────────────────────────────────────────────────────────────
    # Jobs dashboard
    # ──────────────────────────────────────────────────────────────────

    async def _show_jobs(self, chat_id: int, user: User) -> None:
        tid = int(user.get("telegram_id"))
        jobs = await self._jobs().list_for_owner(tid)
        lines = [__("forward.jobs_header")]
        if not jobs:
            lines.append(__("forward.jobs_empty"))
        else:
            for j in jobs[:20]:
                last_run = str(j.get("last_run_status") or j.get("last_dispatched_at") or "—")
                status_emoji = "✅" if j.get("enabled") else "⏸"
                lines.append(
                    __(
                        "forward.jobs_line",
                        job_id=j.get("id"),
                        account_id=j.get("account_id"),
                        source=j.get("source"),
                        destination=j.get("destination"),
                        status=f"{status_emoji} {j.get('last_run_status') or '—'}",
                        last_run=last_run,
                    )
                )
        await self.tg.send_message(
            chat_id, "\n".join(lines), reply_markup=forward_menu_keyboard()
        )
