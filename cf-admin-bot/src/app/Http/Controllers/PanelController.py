"""Status / Discovery / Promo panels — profile toggles + pool GHA ops."""
from __future__ import annotations

import json

from app.Models.User import User
from app.Models.UserState import UserState
from app.Services.AccountScaffoldService import validate_account_id
from app.Services.AccountService import AccountConflictError, AccountService
from app.Services.GitHubService import GitHubError
from app.Services.ProfileConfigService import ProfileConfigService
from app.Services.RunOrchestratorService import RunOrchestratorService
from app.Services.StatusService import StatusService
from app.Services.TelegramService import TelegramService
from app.Support.ErrorFormat import friendly_error
from app.Support.GithubFactory import make_github, make_scaffold
from app.Support.Lang import __
from app.Support.StatusFormat import format_live_metrics, format_run_line
from config.bot import BotConfig
from config.menus import (
    accounts_pick_keyboard,
    discovery_inspect_keyboard,
    discovery_linkdir_keyboard,
    discovery_menu_keyboard,
    discovery_pool_keyboard,
    main_keyboard,
    promo_menu_keyboard,
    promo_routes_keyboard,
    promo_safety_keyboard,
    status_menu_keyboard,
)

ST_DISC_SUB = "discovery_sub"          # which sub-menu is shown
ST_DISC_PICK = "discovery_pick"
ST_DISC_APPROVE = "discovery_approve_ref"
ST_DISC_REJECT = "discovery_reject_ref"
ST_DISC_BUDGET = "discovery_budget"
ST_DISC_DIR = "discovery_add_dir"
ST_DISC_DIR_REMOVE = "discovery_remove_dir"
ST_DISC_CATCHUP = "discovery_catchup"
ST_DISC_TO_PROMO_PICK = "discovery_to_promo_pick"
ST_DISC_TO_PROMO_SOURCE = "discovery_to_promo_source"
ST_DISC_TO_PROMO_REF = "discovery_to_promo_ref"
ST_PROMO_QUEUE_CLEAR_CONFIRM = "promo_queue_clear_confirm"
ST_PROMO_PICK = "promo_pick"
ST_PROMO_ROUTE_ADD = "promo_route_add"
ST_PROMO_ROUTE_SOURCE = "promo_route_source"
ST_PROMO_GROUP_ADD = "promo_group_add"
ST_PROMO_GROUP_REMOVE = "promo_group_remove"
ST_PROMO_ROUTE_MODE = "promo_route_mode"
ST_PROMO_GROUPS = "promo_groups"
ST_PROMO_SAFETY_CMD = "promo_safety_cmd"

DISCOVERY_PICK_ROLES = ("collector", "inspector", "linkdir", "full")
PROMO_PICK_ROLES = ("promo", "full")
LINKDIR_PICK_ROLES = ("linkdir", "full")
CANCEL_TEXTS = frozenset({"/cancel", "انصراف"})


class PanelController:
    def __init__(self, tg: TelegramService, config: BotConfig) -> None:
        self.tg = tg
        self.config = config
        self.db = config.db

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
            lines.append(
                __(
                    "status.line",
                    id=row.get("id"),
                    on=on,
                    role=row.get("role"),
                    status=row.get("status"),
                    run=run_bit,
                    live=live_bit,
                    url="",
                )
            )
        return "\n".join(lines)

    @staticmethod
    def _format_module_detail(desc: dict) -> str:
        module = str(desc.get("module") or "")
        if module == "link_harvest":
            dirs = ", ".join(desc.get("directories") or []) or "—"
            return (
                f"paused={desc.get('paused')} "
                f"catch_up={desc.get('catch_up_limit')}\n"
                f"dirs: {dirs}"
            )
        if module == "group_inspect":
            return (
                f"paused={desc.get('paused')} "
                f"dry_run={desc.get('dry_run')} "
                f"budget={desc.get('daily_join_budget')}"
            )
        if module == "linkdir_collect":
            return (
                f"enabled={desc.get('enabled')} "
                f"paused={desc.get('paused')} "
                f"steps={desc.get('steps')}"
            )
        return json.dumps(desc, ensure_ascii=False)[:300]

    @staticmethod
    def _format_routes(routes: list) -> str:
        lines: list[str] = []
        for route in routes:
            if not isinstance(route, dict):
                continue
            src = route.get("source") or "?"
            groups = ", ".join(route.get("groups") or []) or "—"
            mode = route.get("mode") or "default"
            flags: list[str] = []
            if route.get("paused"):
                flags.append("paused")
            if not route.get("enabled", True):
                flags.append("off")
            suffix = f" [{','.join(flags)}]" if flags else ""
            lines.append(f"• {src} ({mode}): {groups}{suffix}")
        return "\n".join(lines) if lines else "—"

    @staticmethod
    def _parse_route_line(text: str) -> tuple[str, str]:
        parts = (text or "").strip().split(None, 1)
        if len(parts) < 2:
            raise GitHubError("need source and groups")
        return parts[0], parts[1]

    @staticmethod
    def _parse_group_line(text: str) -> tuple[str, str]:
        parts = (text or "").strip().split(None, 1)
        if len(parts) < 2:
            raise GitHubError("need source and group")
        return parts[0], parts[1]

    async def _show_live_queue_if_fresh(
        self, chat_id: int, user: User, account_id: str, queue_name: str
    ) -> bool:
        tid = int(user.get("telegram_id"))
        snap = await self._status().promo_snapshot(tid)
        for row in snap.get("accounts") or []:
            if str(row.get("id") or "") != account_id:
                continue
            if row.get("heartbeat_stale"):
                return False
            pending = row.get("promo_queue_pending")
            if pending is None:
                return False
            await self.tg.send_message(
                chat_id,
                __("cache.queue_status", account_id=account_id, queue=queue_name, pending=pending, url=""),
                reply_markup=promo_menu_keyboard(),
            )
            return True
        return False

    @staticmethod
    def _is_bad_ref(text: str) -> bool:
        t = (text or "").strip()
        return (
            not t
            or t.startswith("/")
            or t in {__("accounts.btn_cancel"), __("accounts.btn_back")}
        )

    async def show_status(self, chat_id: int, user: User) -> None:
        tid = int(user.get("telegram_id"))
        snap = await self._status().snapshot(tid)
        body = "\n".join(
            [
                __("status.header"),
                self._format_lines(snap, empty_key="accounts.list_empty"),
                __("status.footer"),
            ]
        )
        await self.tg.send_message(
            chat_id, body, reply_markup=status_menu_keyboard()
        )

    async def show_discovery(self, chat_id: int, user: User) -> None:
        tid = int(user.get("telegram_id"))
        await UserState.clear(self.db, tid)
        snap = await self._status().discovery_snapshot(tid)
        counts_line = ""
        try:
            from app.Services.LinkDirCatalogService import LinkDirCatalogService

            counts = await LinkDirCatalogService(self.db).counts()
            counts_line = __(
                "discovery.linkdir_counts",
                total=counts.get("total", 0),
                promo_ready=counts.get("promo_ready", 0),
                keep=counts.get("keep", 0),
                review=counts.get("review", 0),
                junk=counts.get("junk", 0),
                active=counts.get("active", 0),
                stale=counts.get("stale", 0),
            )
        except Exception:
            counts_line = ""
        parts = [
            __("discovery.header"),
            self._format_lines(snap, empty_key="discovery.empty"),
        ]
        if counts_line:
            parts.extend(["", counts_line])
        parts.append(__("discovery.help"))
        await self.tg.send_message(
            chat_id, "\n".join(parts), reply_markup=discovery_menu_keyboard()
        )

    async def show_promo(self, chat_id: int, user: User) -> None:
        tid = int(user.get("telegram_id"))
        await UserState.clear(self.db, tid)
        snap = await self._status().promo_snapshot(tid)
        body = "\n".join(
            [
                __("promo.header"),
                self._format_lines(snap, empty_key="promo.empty"),
                __("promo.help"),
            ]
        )
        await self.tg.send_message(
            chat_id, body, reply_markup=promo_menu_keyboard()
        )

    async def handle(self, chat_id: int, user: User, text: str) -> bool:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        t = (text or "").strip()
        current = str(state.get("state") or "")

        cancel_set = CANCEL_TEXTS | {__("accounts.btn_cancel")}
        if t in cancel_set and current.startswith(("discovery_", "promo_")):
            await UserState.clear(self.db, tid)
            await self.tg.send_message(
                chat_id, __("panel.cancelled"), reply_markup=main_keyboard()
            )
            return True

        if current == ST_PROMO_QUEUE_CLEAR_CONFIRM:
            await self._finish_promo_queue_clear_confirm(chat_id, user, t)
            return True
        if current == ST_DISC_PICK:
            await self._finish_disc_pick(chat_id, user, t)
            return True
        if current == ST_DISC_APPROVE:
            await self._pool_mutate(chat_id, user, t, action="approve")
            return True
        if current == ST_DISC_REJECT:
            await self._pool_mutate(chat_id, user, t, action="reject")
            return True
        if current == ST_DISC_BUDGET:
            await self._set_budget(chat_id, user, t)
            return True
        if current == ST_DISC_DIR:
            await self._add_dir(chat_id, user, t)
            return True
        if current == ST_DISC_DIR_REMOVE:
            await self._remove_dir(chat_id, user, t)
            return True
        if current == ST_DISC_CATCHUP:
            await self._set_catchup(chat_id, user, t)
            return True
        if current == ST_DISC_TO_PROMO_PICK:
            await self._finish_to_promo_pick(chat_id, user, t)
            return True
        if current == ST_DISC_TO_PROMO_SOURCE:
            await self._finish_to_promo_source(chat_id, user, t)
            return True
        if current == ST_DISC_TO_PROMO_REF:
            await self._finish_to_promo_ref(chat_id, user, t)
            return True
        if current == ST_PROMO_PICK:
            await self._finish_promo_pick(chat_id, user, t)
            return True
        if current == ST_PROMO_ROUTE_ADD:
            await self._finish_route_add(chat_id, user, t)
            return True
        if current == ST_PROMO_ROUTE_SOURCE:
            await self._finish_route_source(chat_id, user, t)
            return True
        if current == ST_PROMO_GROUP_ADD:
            await self._finish_group_add(chat_id, user, t)
            return True
        if current == ST_PROMO_GROUP_REMOVE:
            await self._finish_group_remove(chat_id, user, t)
            return True
        if current == ST_PROMO_ROUTE_MODE:
            await self._finish_route_mode(chat_id, user, t)
            return True
        if current == ST_PROMO_GROUPS:
            await self._finish_groups_list(chat_id, user, t)
            return True
        if current == ST_PROMO_SAFETY_CMD:
            await self._finish_safety_cmd(chat_id, user, t)
            return True

        if t in {__("menu.btn_status"), "وضعیت", "📊 وضعیت", __("status.btn_refresh")}:
            await self.show_status(chat_id, user)
            return True
        if t in {
            __("menu.btn_discovery"),
            "کشف",
            "🧺 کشف",
            "🔍 گروه‌یابی",
            __("discovery.btn_refresh"),
        }:
            await self.show_discovery(chat_id, user)
            return True

        # Discovery sub-menus
        if t == __("discovery.btn_sub_pool"):
            await self.tg.send_message(
                chat_id, __("discovery.pool_header"), reply_markup=discovery_pool_keyboard()
            )
            return True
        if t == __("discovery.btn_sub_inspect"):
            await self.tg.send_message(
                chat_id, __("discovery.inspect_header"), reply_markup=discovery_inspect_keyboard()
            )
            return True
        if t == __("discovery.btn_sub_linkdir"):
            await self.tg.send_message(
                chat_id, __("discovery.linkdir_header"), reply_markup=discovery_linkdir_keyboard()
            )
            return True
        if t in {__("menu.btn_promo"), "تبلیغ", "📣 تبلیغ", __("promo.btn_refresh")}:
            await self.show_promo(chat_id, user)
            return True

        # Promo sub-menus
        if t == __("promo.btn_sub_routes"):
            await self.tg.send_message(
                chat_id, __("promo.routes_header"), reply_markup=promo_routes_keyboard()
            )
            return True
        if t == __("promo.btn_sub_safety"):
            await self.tg.send_message(
                chat_id, __("promo.safety_header"), reply_markup=promo_safety_keyboard()
            )
            return True

        # Back from sub-menus → parent menu
        if t == __("nav.btn_back"):
            # Return to the most relevant parent based on context
            if current.startswith("discovery_"):
                await self.show_discovery(chat_id, user)
            elif current.startswith("promo_"):
                await self.show_promo(chat_id, user)
            else:
                await self.tg.send_message(
                    chat_id, __("panel.cancelled"), reply_markup=main_keyboard()
                )
            return True

        # Discovery pool
        if t == __("discovery.btn_pool_status"):
            await self._dispatch_pool(chat_id, user, action="status")
            return True
        if t == __("discovery.btn_pool_list"):
            await self._dispatch_pool(
                chat_id, user, action="list", status_filter="raw"
            )
            return True
        if t == __("discovery.btn_pool_list_ok"):
            await self._dispatch_pool(
                chat_id, user, action="list", status_filter="inspected_ok"
            )
            return True
        if t == __("discovery.btn_pool_list_approved"):
            await self._dispatch_pool(
                chat_id, user, action="list", status_filter="approved"
            )
            return True
        if t == __("discovery.btn_pool_approve"):
            await UserState.set_state(self.db, tid, ST_DISC_APPROVE, {})
            await self.tg.send_message(
                chat_id,
                __("pool.ask_ref_approve"),
                reply_markup=discovery_menu_keyboard(),
            )
            return True
        if t == __("discovery.btn_pool_reject"):
            await UserState.set_state(self.db, tid, ST_DISC_REJECT, {})
            await self.tg.send_message(
                chat_id,
                __("pool.ask_ref_reject"),
                reply_markup=discovery_menu_keyboard(),
            )
            return True
        if t == __("discovery.btn_to_promo"):
            await self._start_to_promo(chat_id, user)
            return True

        # Discovery profile
        if t == __("discovery.btn_profile_status"):
            await self._start_disc_pick(
                chat_id, user, roles=DISCOVERY_PICK_ROLES, intent="profile_status"
            )
            return True
        if t == __("discovery.btn_inspect_dry"):
            await self._start_disc_pick(
                chat_id, user, roles=("inspector", "full"), intent="inspect_dry"
            )
            return True
        if t == __("discovery.btn_inspect_pause"):
            await self._start_disc_pick(
                chat_id, user, roles=("inspector", "full"), intent="inspect_pause"
            )
            return True
        if t == __("discovery.btn_inspect_resume"):
            await self._start_disc_pick(
                chat_id, user, roles=("inspector", "full"), intent="inspect_resume"
            )
            return True
        if t == __("discovery.btn_inspect_budget"):
            await self._start_disc_pick(
                chat_id, user, roles=("inspector", "full"), intent="inspect_budget"
            )
            return True
        if t == __("discovery.btn_inspect_dump"):
            await self._start_disc_pick(
                chat_id, user, roles=("inspector", "full"), intent="inspect_dump"
            )
            return True
        if t == __("discovery.btn_harvest_pause"):
            await self._start_disc_pick(
                chat_id, user, roles=("collector", "full"), intent="harvest_pause"
            )
            return True
        if t == __("discovery.btn_harvest_resume"):
            await self._start_disc_pick(
                chat_id, user, roles=("collector", "full"), intent="harvest_resume"
            )
            return True
        if t == __("discovery.btn_harvest_add"):
            await self._start_disc_pick(
                chat_id, user, roles=("collector", "full"), intent="harvest_add"
            )
            return True
        if t == __("discovery.btn_harvest_remove"):
            await self._start_disc_pick(
                chat_id, user, roles=("collector", "full"), intent="harvest_remove"
            )
            return True
        if t == __("discovery.btn_harvest_catchup"):
            await self._start_disc_pick(
                chat_id, user, roles=("collector", "full"), intent="harvest_catchup"
            )
            return True
        if t == __("discovery.btn_linkdir_counts"):
            await self._show_linkdir_counts(chat_id)
            return True
        if t == __("discovery.btn_linkdir_run"):
            await self._start_disc_pick(
                chat_id, user, roles=LINKDIR_PICK_ROLES, intent="linkdir_run"
            )
            return True
        if t == __("discovery.btn_linkdir_pause"):
            await self._start_disc_pick(
                chat_id, user, roles=LINKDIR_PICK_ROLES, intent="linkdir_pause"
            )
            return True
        if t == __("discovery.btn_linkdir_resume"):
            await self._start_disc_pick(
                chat_id, user, roles=LINKDIR_PICK_ROLES, intent="linkdir_resume"
            )
            return True

        # Promo profile
        if t == __("promo.btn_profile_status"):
            await self._start_promo_pick(chat_id, user, intent="profile_status")
            return True
        if t == __("promo.btn_dry"):
            await self._start_promo_pick(chat_id, user, intent="promo_dry")
            return True
        if t == __("promo.btn_pause"):
            await self._start_promo_pick(chat_id, user, intent="promo_pause")
            return True
        if t == __("promo.btn_resume"):
            await self._start_promo_pick(chat_id, user, intent="promo_resume")
            return True
        if t == __("promo.btn_mode_forward"):
            await self._start_promo_pick(chat_id, user, intent="promo_mode_forward")
            return True
        if t == __("promo.btn_mode_copy"):
            await self._start_promo_pick(chat_id, user, intent="promo_mode_copy")
            return True
        if t == __("promo.btn_route_add"):
            await self._start_promo_pick(chat_id, user, intent="route_add")
            return True
        if t == __("promo.btn_route_remove"):
            await self._start_promo_pick(chat_id, user, intent="route_remove")
            return True
        if t == __("promo.btn_group_add"):
            await self._start_promo_pick(chat_id, user, intent="group_add")
            return True
        if t == __("promo.btn_route_pause"):
            await self._start_promo_pick(chat_id, user, intent="route_pause")
            return True
        if t == __("promo.btn_route_resume"):
            await self._start_promo_pick(chat_id, user, intent="route_resume")
            return True
        if t == __("promo.btn_route_mode"):
            await self._start_promo_pick(chat_id, user, intent="route_mode")
            return True
        if t == __("promo.btn_group_remove"):
            await self._start_promo_pick(chat_id, user, intent="group_remove")
            return True
        if t == __("promo.btn_groups"):
            await self._start_promo_pick(chat_id, user, intent="groups")
            return True
        if t == __("promo.btn_safety_view"):
            await self._start_promo_pick(chat_id, user, intent="safety_view")
            return True
        if t == __("promo.btn_safety_delay"):
            await self._start_promo_pick(chat_id, user, intent="safety_delay")
            return True
        if t == __("promo.btn_safety_budget"):
            await self._start_promo_pick(chat_id, user, intent="safety_budget")
            return True
        if t == __("promo.btn_safety_windows"):
            await self._start_promo_pick(chat_id, user, intent="safety_windows")
            return True
        if t == __("promo.btn_safety_cooldown"):
            await self._start_promo_pick(chat_id, user, intent="safety_cooldown")
            return True
        if t == __("promo.btn_safety_tz"):
            await self._start_promo_pick(chat_id, user, intent="safety_tz")
            return True
        if t == __("promo.btn_queue_status"):
            await self._start_promo_pick(chat_id, user, intent="promo_queue_status")
            return True
        if t == __("promo.btn_queue_clear"):
            await self._start_promo_pick(chat_id, user, intent="promo_queue_clear_ask")
            return True
        if t == __("promo.btn_safety_dump"):
            await self._start_promo_pick(chat_id, user, intent="promo_safety_dump")
            return True

        return False

    async def _ids_for_roles(self, tid: int, roles: tuple[str, ...]) -> list[str]:
        rows = await AccountService(self.db).list_for_user(tid)
        want = {r.lower() for r in roles}
        return [
            str(r.get("id"))
            for r in rows
            if str(r.get("role") or "").lower() in want and r.get("id")
        ]

    async def _start_disc_pick(
        self,
        chat_id: int,
        user: User,
        *,
        roles: tuple[str, ...],
        intent: str,
    ) -> None:
        tid = int(user.get("telegram_id"))
        if not self.config.github_ready():
            await self.tg.send_message(
                chat_id,
                __("accounts.missing_github"),
                reply_markup=discovery_menu_keyboard(),
            )
            return
        ids = await self._ids_for_roles(tid, roles)
        if not ids:
            await self.tg.send_message(
                chat_id,
                __("discovery.no_role_account"),
                reply_markup=discovery_menu_keyboard(),
            )
            return
        await UserState.set_state(
            self.db, tid, ST_DISC_PICK, {"intent": intent, "roles": list(roles)}
        )
        await self.tg.send_message(
            chat_id,
            __("panel.pick_account"),
            reply_markup=accounts_pick_keyboard(ids),
        )

    async def _start_promo_pick(self, chat_id: int, user: User, *, intent: str) -> None:
        tid = int(user.get("telegram_id"))
        if not self.config.github_ready():
            await self.tg.send_message(
                chat_id,
                __("accounts.missing_github"),
                reply_markup=promo_menu_keyboard(),
            )
            return
        ids = await self._ids_for_roles(tid, PROMO_PICK_ROLES)
        if not ids:
            await self.tg.send_message(
                chat_id, __("promo.empty"), reply_markup=promo_menu_keyboard()
            )
            return
        await UserState.set_state(self.db, tid, ST_PROMO_PICK, {"intent": intent})
        await self.tg.send_message(
            chat_id,
            __("panel.pick_account"),
            reply_markup=accounts_pick_keyboard(ids),
        )

    async def _start_to_promo(self, chat_id: int, user: User) -> None:
        tid = int(user.get("telegram_id"))
        if not self.config.github_ready():
            await self.tg.send_message(
                chat_id,
                __("accounts.missing_github"),
                reply_markup=discovery_menu_keyboard(),
            )
            return
        ids = await self._ids_for_roles(tid, PROMO_PICK_ROLES)
        if not ids:
            await self.tg.send_message(
                chat_id, __("promo.empty"), reply_markup=discovery_menu_keyboard()
            )
            return
        await UserState.set_state(self.db, tid, ST_DISC_TO_PROMO_PICK, {})
        await self.tg.send_message(
            chat_id,
            __("panel.pick_account"),
            reply_markup=accounts_pick_keyboard(ids),
        )

    async def _finish_disc_pick(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        intent = str(state.context.get("intent") or "")
        aid = validate_account_id(t)
        if not aid:
            await self.tg.send_message(chat_id, __("accounts.invalid_id"))
            return

        if intent == "profile_status":
            await UserState.clear(self.db, tid)
            await self._show_discovery_profile(chat_id, user, aid)
            return
        if intent == "inspect_dump":
            await UserState.clear(self.db, tid)
            await self._dispatch_cache(
                chat_id, user, aid, "inspect_state_dump", panel="discovery"
            )
            return
        if intent == "inspect_budget":
            await UserState.set_state(
                self.db, tid, ST_DISC_BUDGET, {"account_id": aid}
            )
            await self.tg.send_message(chat_id, __("discovery.ask_budget"))
            return
        if intent == "harvest_add":
            await UserState.set_state(
                self.db, tid, ST_DISC_DIR, {"account_id": aid}
            )
            await self.tg.send_message(chat_id, __("discovery.ask_directory"))
            return
        if intent == "harvest_remove":
            await UserState.set_state(
                self.db, tid, ST_DISC_DIR_REMOVE, {"account_id": aid}
            )
            await self.tg.send_message(chat_id, __("discovery.ask_directory"))
            return
        if intent == "harvest_catchup":
            await UserState.set_state(
                self.db, tid, ST_DISC_CATCHUP, {"account_id": aid}
            )
            await self.tg.send_message(chat_id, __("discovery.ask_catchup"))
            return
        if intent == "linkdir_run":
            await UserState.clear(self.db, tid)
            await self._dispatch_linkdir_run(chat_id, user, aid)
            return

        await self._apply_profile_intent(chat_id, user, aid, intent)
        await UserState.clear(self.db, tid)

    async def _finish_promo_pick(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        intent = str(state.context.get("intent") or "")
        aid = validate_account_id(t)
        if not aid:
            await self.tg.send_message(chat_id, __("accounts.invalid_id"))
            return

        if intent == "profile_status":
            await UserState.clear(self.db, tid)
            await self._show_promo_profile(chat_id, user, aid)
            return
        if intent == "route_add":
            await UserState.set_state(
                self.db, tid, ST_PROMO_ROUTE_ADD, {"account_id": aid}
            )
            await self.tg.send_message(
                chat_id,
                __("promo.ask_route_add"),
                reply_markup=promo_menu_keyboard(),
            )
            return
        if intent in {"route_remove", "route_pause", "route_resume"}:
            await UserState.set_state(
                self.db,
                tid,
                ST_PROMO_ROUTE_SOURCE,
                {"account_id": aid, "intent": intent},
            )
            await self.tg.send_message(
                chat_id,
                __("promo.ask_route_source"),
                reply_markup=promo_menu_keyboard(),
            )
            return
        if intent == "route_mode":
            await UserState.set_state(
                self.db, tid, ST_PROMO_ROUTE_MODE, {"account_id": aid}
            )
            await self.tg.send_message(
                chat_id,
                __("promo.ask_route_mode"),
                reply_markup=promo_menu_keyboard(),
            )
            return
        if intent == "group_remove":
            await UserState.set_state(
                self.db, tid, ST_PROMO_GROUP_REMOVE, {"account_id": aid}
            )
            await self.tg.send_message(
                chat_id,
                __("promo.ask_group_remove"),
                reply_markup=promo_menu_keyboard(),
            )
            return
        if intent == "groups":
            await UserState.set_state(
                self.db, tid, ST_PROMO_GROUPS, {"account_id": aid}
            )
            await self.tg.send_message(
                chat_id,
                __("promo.ask_groups"),
                reply_markup=promo_menu_keyboard(),
            )
            return
        if intent == "safety_view":
            await UserState.clear(self.db, tid)
            await self._show_safety_config(chat_id, user, aid)
            return
        safety_wizards = {
            "safety_delay": "promo.ask_safety_delay",
            "safety_budget": "promo.ask_safety_budget",
            "safety_windows": "promo.ask_safety_windows",
            "safety_cooldown": "promo.ask_safety_cooldown",
            "safety_tz": "promo.ask_safety_tz",
        }
        if intent in safety_wizards:
            await UserState.set_state(
                self.db, tid, ST_PROMO_SAFETY_CMD, {"account_id": aid, "intent": intent}
            )
            await self.tg.send_message(
                chat_id,
                __(safety_wizards[intent]),
                reply_markup=promo_menu_keyboard(),
            )
            return
        if intent == "group_add":
            await UserState.set_state(
                self.db, tid, ST_PROMO_GROUP_ADD, {"account_id": aid}
            )
            await self.tg.send_message(
                chat_id,
                __("promo.ask_group_add"),
                reply_markup=promo_menu_keyboard(),
            )
            return
        if intent == "promo_queue_status":
            await UserState.clear(self.db, tid)
            if not await self._show_live_queue_if_fresh(chat_id, user, aid, "promo"):
                await self._dispatch_cache(
                    chat_id, user, aid, "promo_queue_status", panel="promo"
                )
            return
        if intent == "promo_queue_clear_ask":
            # Store account_id and ask for confirmation before clearing
            await UserState.set_state(
                self.db, tid, ST_PROMO_QUEUE_CLEAR_CONFIRM, {"account_id": aid}
            )
            from config.menus import queue_clear_confirm_keyboard
            await self.tg.send_message(
                chat_id,
                __("cache.queue_clear_confirm", account_id=aid),
                reply_markup=queue_clear_confirm_keyboard(),
            )
            return
        if intent == "promo_queue_clear":
            await UserState.clear(self.db, tid)
            await self._dispatch_cache(
                chat_id, user, aid, "promo_queue_clear", panel="promo"
            )
            return
        if intent == "promo_safety_dump":
            await UserState.clear(self.db, tid)
            await self._dispatch_cache(
                chat_id, user, aid, "promo_safety_dump", panel="promo"
            )
            return

        await self._apply_profile_intent(chat_id, user, aid, intent)
        await UserState.clear(self.db, tid)

    async def _finish_to_promo_pick(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        aid = validate_account_id(t)
        if not aid:
            await self.tg.send_message(chat_id, __("accounts.invalid_id"))
            return
        try:
            await AccountService(self.db).require_owned(tid, aid)
        except AccountConflictError as exc:
            await self.tg.send_message(
                chat_id,
                __("accounts.not_owned", account_id=exc.account_id or aid),
            )
            return
        await UserState.set_state(
            self.db, tid, ST_DISC_TO_PROMO_SOURCE, {"promo_account_id": aid}
        )
        await self.tg.send_message(
            chat_id,
            __("discovery.ask_to_promo_source"),
            reply_markup=discovery_menu_keyboard(),
        )

    async def _finish_to_promo_source(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        if self._is_bad_ref(t):
            await self.tg.send_message(chat_id, __("pool.invalid_ref"))
            return
        state = await UserState.get_or_idle(self.db, tid)
        await UserState.set_state(
            self.db,
            tid,
            ST_DISC_TO_PROMO_REF,
            {
                "promo_account_id": state.context.get("promo_account_id"),
                "source_channel": t.strip(),
            },
        )
        await self.tg.send_message(
            chat_id,
            __("discovery.ask_to_promo_ref"),
            reply_markup=discovery_menu_keyboard(),
        )

    async def _finish_to_promo_ref(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        if self._is_bad_ref(t):
            await self.tg.send_message(chat_id, __("pool.invalid_ref"))
            return
        state = await UserState.get_or_idle(self.db, tid)
        ctx = state.context
        promo_id = str(ctx.get("promo_account_id") or "")
        source = str(ctx.get("source_channel") or "")
        ref = t.strip()
        await UserState.clear(self.db, tid)
        await self._dispatch_pool(
            chat_id,
            user,
            action="get",
            ref=ref,
            intent="to_promo",
            promo_account_id=promo_id,
            source_channel=source,
        )

    async def _finish_route_add(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        try:
            source, groups = self._parse_route_line(t)
            result = await prof.promo_add_route(tid, aid, source, groups)
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        route = result.get("route") or {}
        await self.tg.send_message(
            chat_id,
            __(
                "profile.patch_done",
                account_id=aid,
                module="promo_spread",
                detail=str(route)[:300],
            ),
            reply_markup=promo_menu_keyboard(),
        )

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
                result = await prof.promo_remove_route(tid, aid, source)
            elif intent == "route_pause":
                result = await prof.promo_set_route_paused(
                    tid, aid, source, paused=True
                )
            elif intent == "route_resume":
                result = await prof.promo_set_route_paused(
                    tid, aid, source, paused=False
                )
            else:
                await self.tg.send_message(chat_id, __("menu.unknown"))
                return
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        await self.tg.send_message(
            chat_id,
            __(
                "profile.patch_done",
                account_id=aid,
                module="promo_spread",
                detail=str(result.get("merged") or "")[:300],
            ),
            reply_markup=promo_menu_keyboard(),
        )

    async def _finish_group_add(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        try:
            source, group = self._parse_group_line(t)
            result = await prof.promo_group_add(tid, aid, source, group)
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        route = result.get("route") or {}
        await self.tg.send_message(
            chat_id,
            __(
                "profile.patch_done",
                account_id=aid,
                module="promo_spread",
                detail=str(route)[:300],
            ),
            reply_markup=promo_menu_keyboard(),
        )

    async def _finish_route_mode(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        try:
            parts = (t or "").strip().split(None, 1)
            if len(parts) < 2:
                raise GitHubError("need source and mode")
            source, mode = parts[0], parts[1].strip().lower()
            if mode not in {"forward", "copy"}:
                raise GitHubError("mode must be forward|copy")
            result = await prof.promo_set_route_mode(tid, aid, source, mode)
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        route = result.get("route") or {}
        await self.tg.send_message(
            chat_id,
            __(
                "profile.patch_done",
                account_id=aid,
                module="promo_spread",
                detail=str(route)[:300],
            ),
            reply_markup=promo_menu_keyboard(),
        )

    async def _finish_group_remove(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        try:
            source, group = self._parse_group_line(t)
            result = await prof.promo_group_remove(tid, aid, source, group)
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        route = result.get("route") or {}
        await self.tg.send_message(
            chat_id,
            __(
                "profile.patch_done",
                account_id=aid,
                module="promo_spread",
                detail=str(route)[:300],
            ),
            reply_markup=promo_menu_keyboard(),
        )

    async def _finish_groups_list(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        source = (t or "").strip()
        if source in {__("promo.btn_groups_all"), "همه", "all", "*"}:
            source = None
        elif self._is_bad_ref(source):
            await self.tg.send_message(chat_id, __("pool.invalid_ref"))
            return
        try:
            info = await prof.promo_route_groups(tid, aid, source)
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        lines = "\n".join(info.get("lines") or ["—"])
        if source:
            body = __("promo.groups_one", source=info.get("source"), lines=lines)
        else:
            body = __(
                "promo.groups_all",
                count=info.get("route_count", 0),
                lines=lines,
            )
        await self.tg.send_message(
            chat_id, body, reply_markup=promo_menu_keyboard()
        )

    async def _finish_safety_cmd(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        intent = str(state.context.get("intent") or "")
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        cmd_map = {
            "safety_delay": lambda text: f"delay {text.strip()}",
            "safety_budget": lambda text: f"budget {text.strip()}",
            "safety_windows": lambda text: f"windows {text.strip()}",
            "safety_cooldown": lambda text: f"cooldown {text.strip()}",
            "safety_tz": lambda text: f"tz {text.strip()}",
        }
        builder = cmd_map.get(intent)
        if not builder:
            await UserState.clear(self.db, tid)
            await self.tg.send_message(chat_id, __("menu.unknown"))
            return
        try:
            result = await prof.promo_safety_command(tid, aid, builder(t))
        except (AccountConflictError, GitHubError, ValueError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        lines = "\n".join(result.get("summary") or ["—"])
        await self.tg.send_message(
            chat_id,
            __("promo.safety_done", account_id=aid, lines=lines),
            reply_markup=promo_menu_keyboard(),
        )

    async def _show_safety_config(
        self, chat_id: int, user: User, account_id: str
    ) -> None:
        prof = self._profile()
        if not prof:
            await self.tg.send_message(
                chat_id,
                __("accounts.missing_github"),
                reply_markup=promo_menu_keyboard(),
            )
            return
        tid = int(user.get("telegram_id"))
        try:
            info = await prof.promo_safety_config(tid, account_id)
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        lines = "\n".join(info.get("summary") or ["—"])
        await self.tg.send_message(
            chat_id,
            __("promo.safety_config", account_id=account_id, lines=lines),
            reply_markup=promo_menu_keyboard(),
        )

    async def _show_discovery_profile(
        self, chat_id: int, user: User, account_id: str
    ) -> None:
        prof = self._profile()
        if not prof:
            await self.tg.send_message(
                chat_id,
                __("accounts.missing_github"),
                reply_markup=discovery_menu_keyboard(),
            )
            return
        tid = int(user.get("telegram_id"))
        try:
            row = await AccountService(self.db).require_owned(tid, account_id)
        except AccountConflictError as exc:
            await self.tg.send_message(
                chat_id,
                __("accounts.not_owned", account_id=exc.account_id or account_id),
            )
            return

        role = str(row.get("role") or "").lower()
        modules = {
            "collector": ["link_harvest"],
            "inspector": ["group_inspect"],
            "linkdir": ["linkdir_collect"],
        }.get(role, ["link_harvest", "group_inspect", "linkdir_collect"])

        parts: list[str] = []
        try:
            for module in modules:
                desc = await prof.describe_module(tid, account_id, module)
                parts.append(
                    __(
                        "discovery.profile_status",
                        account_id=account_id,
                        module=module,
                        detail=self._format_module_detail(desc),
                    )
                )
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return

        await self.tg.send_message(
            chat_id,
            "\n\n".join(parts),
            reply_markup=discovery_menu_keyboard(),
        )

    async def _show_promo_profile(
        self, chat_id: int, user: User, account_id: str
    ) -> None:
        prof = self._profile()
        if not prof:
            await self.tg.send_message(
                chat_id,
                __("accounts.missing_github"),
                reply_markup=promo_menu_keyboard(),
            )
            return
        tid = int(user.get("telegram_id"))
        try:
            desc = await prof.describe_module(tid, account_id, "promo_spread")
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await self.tg.send_message(
            chat_id,
            __(
                "promo.profile_status",
                account_id=account_id,
                dry_run=desc.get("dry_run"),
                paused=desc.get("paused"),
                mode=desc.get("mode"),
                route_count=desc.get("route_count", 0),
                routes=self._format_routes(desc.get("routes") or []),
            ),
            reply_markup=promo_menu_keyboard(),
        )

    async def _apply_profile_intent(
        self, chat_id: int, user: User, account_id: str, intent: str
    ) -> None:
        prof = self._profile()
        if not prof:
            await self.tg.send_message(
                chat_id, __("accounts.missing_github"), reply_markup=main_keyboard()
            )
            return
        tid = int(user.get("telegram_id"))
        discovery = intent.startswith(("inspect", "harvest", "linkdir"))
        kb = discovery_menu_keyboard() if discovery else promo_menu_keyboard()
        try:
            if intent == "inspect_dry":
                result = await prof.toggle_bool(
                    tid, account_id, "group_inspect", "dry_run"
                )
            elif intent == "inspect_pause":
                result = await prof.patch(
                    tid, account_id, "group_inspect", {"paused": True}
                )
            elif intent == "inspect_resume":
                result = await prof.patch(
                    tid, account_id, "group_inspect", {"paused": False}
                )
            elif intent == "harvest_pause":
                result = await prof.patch(
                    tid, account_id, "link_harvest", {"paused": True}
                )
            elif intent == "harvest_resume":
                result = await prof.patch(
                    tid, account_id, "link_harvest", {"paused": False}
                )
            elif intent == "linkdir_pause":
                result = await prof.patch(
                    tid, account_id, "linkdir_collect", {"paused": True}
                )
            elif intent == "linkdir_resume":
                result = await prof.patch(
                    tid, account_id, "linkdir_collect", {"paused": False}
                )
            elif intent == "promo_dry":
                result = await prof.toggle_bool(
                    tid, account_id, "promo_spread", "dry_run"
                )
            elif intent == "promo_pause":
                result = await prof.patch(
                    tid, account_id, "promo_spread", {"paused": True}
                )
            elif intent == "promo_resume":
                result = await prof.patch(
                    tid, account_id, "promo_spread", {"paused": False}
                )
            elif intent == "promo_mode_forward":
                result = await prof.patch(
                    tid, account_id, "promo_spread", {"mode": "forward"}
                )
            elif intent == "promo_mode_copy":
                result = await prof.patch(
                    tid, account_id, "promo_spread", {"mode": "copy"}
                )
            else:
                await self.tg.send_message(chat_id, __("menu.unknown"))
                return
        except AccountConflictError as exc:
            await self.tg.send_message(
                chat_id,
                __("accounts.not_owned", account_id=exc.account_id or account_id),
            )
            return
        except GitHubError as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return

        merged = result.get("merged") or {}
        await self.tg.send_message(
            chat_id,
            __(
                "profile.patch_done",
                account_id=account_id,
                module=result.get("module"),
                detail=str(merged)[:300],
            ),
            reply_markup=kb,
        )

    async def _set_budget(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        try:
            n = int(t.strip())
        except ValueError:
            await self.tg.send_message(chat_id, __("discovery.invalid_budget"))
            return
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        try:
            result = await prof.set_budget(tid, aid, n)
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        await self.tg.send_message(
            chat_id,
            __(
                "profile.patch_done",
                account_id=aid,
                module="group_inspect",
                detail=str(result.get("merged") or "")[:300],
            ),
            reply_markup=discovery_menu_keyboard(),
        )

    async def _set_catchup(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        try:
            n = int(t.strip())
        except ValueError:
            await self.tg.send_message(
                chat_id,
                __("accounts.error", error="catch_up: 0-200"),
            )
            return
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        try:
            result = await prof.set_catchup(tid, aid, n)
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        await self.tg.send_message(
            chat_id,
            __(
                "profile.patch_done",
                account_id=aid,
                module="link_harvest",
                detail=str(result.get("merged") or "")[:300],
            ),
            reply_markup=discovery_menu_keyboard(),
        )

    async def _add_dir(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        try:
            result = await prof.add_directory(tid, aid, t)
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        await self.tg.send_message(
            chat_id,
            __(
                "profile.patch_done",
                account_id=aid,
                module="link_harvest",
                detail=str(result.get("merged") or "")[:300],
            ),
            reply_markup=discovery_menu_keyboard(),
        )

    async def _remove_dir(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        prof = self._profile()
        if not prof:
            await self.tg.send_message(chat_id, __("accounts.missing_github"))
            return
        try:
            result = await prof.remove_directory(tid, aid, t)
        except (AccountConflictError, GitHubError) as exc:
            await self.tg.send_message(
                chat_id, __("accounts.error", error=friendly_error(exc))
            )
            return
        await UserState.clear(self.db, tid)
        await self.tg.send_message(
            chat_id,
            __(
                "profile.patch_done",
                account_id=aid,
                module="link_harvest",
                detail=str(result.get("merged") or "")[:300],
            ),
            reply_markup=discovery_menu_keyboard(),
        )

    async def _show_linkdir_counts(self, chat_id: int) -> None:
        try:
            from app.Services.LinkDirCatalogService import LinkDirCatalogService

            counts = await LinkDirCatalogService(self.db).counts()
            body = __(
                "discovery.linkdir_counts",
                total=counts.get("total", 0),
                promo_ready=counts.get("promo_ready", 0),
                keep=counts.get("keep", 0),
                review=counts.get("review", 0),
                junk=counts.get("junk", 0),
                active=counts.get("active", 0),
                stale=counts.get("stale", 0),
            )
        except Exception as exc:
            body = __("accounts.error", error=friendly_error(exc))
        await self.tg.send_message(
            chat_id, body, reply_markup=discovery_menu_keyboard()
        )

    async def _dispatch_linkdir_run(self, chat_id: int, user: User, account_id: str) -> None:
        runner = self._runner()
        if not runner:
            await self.tg.send_message(
                chat_id,
                __("accounts.missing_github"),
                reply_markup=discovery_menu_keyboard(),
            )
            return
        tid = int(user.get("telegram_id"))
        try:
            info = await runner.dispatch(tid, account_id)
        except AccountConflictError as exc:
            await self.tg.send_message(
                chat_id,
                __("accounts.not_owned", account_id=exc.account_id or account_id),
                reply_markup=discovery_menu_keyboard(),
            )
            return
        except GitHubError as exc:
            await self.tg.send_message(
                chat_id,
                __("accounts.error", error=friendly_error(exc)),
                reply_markup=discovery_menu_keyboard(),
            )
            return
        await self.tg.send_message(
            chat_id,
            __(
                "discovery.linkdir_run_done",
                account_id=account_id,
                run_id=info.get("run_id") or "-",
                status=info.get("status") or "-",
                url=info.get("html_url") or "",
            ),
            reply_markup=discovery_menu_keyboard(),
        )

    async def _dispatch_pool(
        self,
        chat_id: int,
        user: User,
        *,
        action: str,
        status_filter: str = "",
        ref: str = "",
        intent: str = "",
        promo_account_id: str = "",
        source_channel: str = "",
    ) -> None:
        runner = self._runner()
        if not runner:
            await self.tg.send_message(
                chat_id,
                __("accounts.missing_github"),
                reply_markup=discovery_menu_keyboard(),
            )
            return
        tid = int(user.get("telegram_id"))
        await self.tg.send_message(chat_id, __("pool.working", action=action))
        try:
            info = await runner.pool_admin(
                action=action,
                notify_user_id=tid,
                notify_chat_id=chat_id,
                status_filter=status_filter,
                ref=ref,
                intent=intent,
                promo_account_id=promo_account_id,
                source_channel=source_channel,
            )
        except GitHubError as exc:
            await self.tg.send_message(
                chat_id,
                __("accounts.error", error=friendly_error(exc)),
                reply_markup=discovery_menu_keyboard(),
            )
            return
        await self.tg.send_message(
            chat_id,
            __(
                "pool.dispatched",
                action=action,
                run_id=info.get("run_id") or "-",
                url=info.get("html_url") or "",
            ),
            reply_markup=discovery_menu_keyboard(),
        )

    async def _dispatch_cache(
        self,
        chat_id: int,
        user: User,
        account_id: str,
        action: str,
        *,
        panel: str,
    ) -> None:
        runner = self._runner()
        kb = (
            discovery_menu_keyboard()
            if panel == "discovery"
            else promo_menu_keyboard()
        )
        if not runner:
            await self.tg.send_message(
                chat_id, __("accounts.missing_github"), reply_markup=kb
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
                reply_markup=kb,
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
            reply_markup=kb,
        )

    async def _finish_promo_queue_clear_confirm(
        self, chat_id: int, user: User, t: str
    ) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str((state.context or {}).get("account_id") or "")
        await UserState.clear(self.db, tid)
        if t != __("cache.queue_clear_btn_confirm"):
            await self.tg.send_message(
                chat_id, __("panel.cancelled"), reply_markup=promo_menu_keyboard()
            )
            return
        await self._dispatch_cache(chat_id, user, aid, "promo_queue_clear", panel="promo")

    async def _pool_mutate(
        self, chat_id: int, user: User, t: str, *, action: str
    ) -> None:
        tid = int(user.get("telegram_id"))
        if self._is_bad_ref(t):
            await self.tg.send_message(chat_id, __("pool.invalid_ref"))
            return
        await UserState.clear(self.db, tid)
        await self._dispatch_pool(chat_id, user, action=action, ref=t.strip())
