"""Status / Discovery / Promo panels — profile toggles + pool GHA ops."""
from __future__ import annotations

from app.Models.User import User
from app.Models.UserState import UserState
from app.Services.AccountScaffoldService import validate_account_id
from app.Services.AccountService import AccountConflictError, AccountService
from app.Services.GitHubService import GitHubError
from app.Services.ProfileConfigService import ProfileConfigService
from app.Services.RunOrchestratorService import RunOrchestratorService
from app.Services.StatusService import StatusService
from app.Services.TelegramService import TelegramService
from app.Support.GithubFactory import make_github, make_scaffold
from app.Support.Lang import __
from config.bot import BotConfig
from config.menus import (
    accounts_pick_keyboard,
    discovery_menu_keyboard,
    main_keyboard,
    promo_menu_keyboard,
    status_menu_keyboard,
)

ST_DISC_PICK = "discovery_pick"
ST_DISC_APPROVE = "discovery_approve_ref"
ST_DISC_REJECT = "discovery_reject_ref"
ST_DISC_BUDGET = "discovery_budget"
ST_DISC_DIR = "discovery_add_dir"
ST_PROMO_PICK = "promo_pick"


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

    def _format_lines(self, snap: dict, *, empty_key: str) -> str:
        accounts = snap.get("accounts") or []
        if not accounts:
            return __(empty_key)
        lines = []
        for row in accounts:
            on = "ON" if row.get("enabled") else "OFF"
            run_bit = f"{row.get('run_status')}/{row.get('run_conclusion')}"
            if row.get("run_id"):
                run_bit = f"#{row.get('run_id')} {run_bit}"
            url = row.get("run_url") or ""
            lines.append(
                __(
                    "status.line",
                    id=row.get("id"),
                    on=on,
                    role=row.get("role"),
                    status=row.get("status"),
                    run=run_bit,
                    url=url,
                )
            )
        return "\n".join(lines)

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
        body = "\n".join(
            [
                __("discovery.header"),
                self._format_lines(snap, empty_key="discovery.empty"),
                __("discovery.help"),
            ]
        )
        await self.tg.send_message(
            chat_id, body, reply_markup=discovery_menu_keyboard()
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

        if t in {"/cancel", __("accounts.btn_cancel"), "انصراف"} and current.startswith(
            ("discovery_", "promo_")
        ):
            await UserState.clear(self.db, tid)
            await self.tg.send_message(
                chat_id, __("panel.cancelled"), reply_markup=main_keyboard()
            )
            return True

        if current == ST_DISC_PICK:
            await self._finish_pick(chat_id, user, t)
            return True
        if current == ST_PROMO_PICK:
            await self._finish_promo_pick(chat_id, user, t)
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

        if t in {__("menu.btn_status"), "وضعیت", "📊 وضعیت", __("status.btn_refresh")}:
            await self.show_status(chat_id, user)
            return True
        if t in {
            __("menu.btn_discovery"),
            "کشف",
            "🧺 کشف",
            __("discovery.btn_refresh"),
        }:
            await self.show_discovery(chat_id, user)
            return True
        if t in {__("menu.btn_promo"), "تبلیغ", "📣 تبلیغ", __("promo.btn_refresh")}:
            await self.show_promo(chat_id, user)
            return True

        if t == __("discovery.btn_help"):
            await self.tg.send_message(
                chat_id, __("discovery.help_full"), reply_markup=discovery_menu_keyboard()
            )
            return True
        if t == __("promo.btn_help"):
            await self.tg.send_message(
                chat_id, __("promo.help_full"), reply_markup=promo_menu_keyboard()
            )
            return True

        # Discovery pool ops
        if t == __("discovery.btn_pool_status"):
            await self._dispatch_pool(chat_id, user, action="status")
            return True
        if t == __("discovery.btn_pool_list"):
            await self._dispatch_pool(
                chat_id, user, action="list", status_filter="raw"
            )
            return True
        if t == __("discovery.btn_pool_approve"):
            await UserState.set_state(self.db, tid, ST_DISC_APPROVE, {})
            await self.tg.send_message(
                chat_id, __("pool.ask_ref_approve"), reply_markup=discovery_menu_keyboard()
            )
            return True
        if t == __("discovery.btn_pool_reject"):
            await UserState.set_state(self.db, tid, ST_DISC_REJECT, {})
            await self.tg.send_message(
                chat_id, __("pool.ask_ref_reject"), reply_markup=discovery_menu_keyboard()
            )
            return True

        # Discovery profile ops (need account pick)
        if t == __("discovery.btn_inspect_dry"):
            await self._start_pick(
                chat_id, user, roles=("inspector", "full"), intent="inspect_dry"
            )
            return True
        if t == __("discovery.btn_inspect_pause"):
            await self._start_pick(
                chat_id, user, roles=("inspector", "full"), intent="inspect_pause"
            )
            return True
        if t == __("discovery.btn_inspect_resume"):
            await self._start_pick(
                chat_id, user, roles=("inspector", "full"), intent="inspect_resume"
            )
            return True
        if t == __("discovery.btn_inspect_budget"):
            await self._start_pick(
                chat_id, user, roles=("inspector", "full"), intent="inspect_budget"
            )
            return True
        if t == __("discovery.btn_harvest_pause"):
            await self._start_pick(
                chat_id, user, roles=("collector", "full"), intent="harvest_pause"
            )
            return True
        if t == __("discovery.btn_harvest_resume"):
            await self._start_pick(
                chat_id, user, roles=("collector", "full"), intent="harvest_resume"
            )
            return True
        if t == __("discovery.btn_harvest_add"):
            await self._start_pick(
                chat_id, user, roles=("collector", "full"), intent="harvest_add"
            )
            return True

        # Promo profile ops
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

        return False

    async def _ids_for_roles(self, tid: int, roles: tuple[str, ...]) -> list[str]:
        rows = await AccountService(self.db).list_for_user(tid)
        return [
            str(r.get("id"))
            for r in rows
            if str(r.get("role") or "").lower() in roles and r.get("id")
        ]

    async def _start_pick(
        self, chat_id: int, user: User, *, roles: tuple[str, ...], intent: str
    ) -> None:
        tid = int(user.get("telegram_id"))
        if not self.config.github_ready():
            await self.tg.send_message(
                chat_id, __("accounts.missing_github"), reply_markup=discovery_menu_keyboard()
            )
            return
        ids = await self._ids_for_roles(tid, roles)
        if not ids:
            await self.tg.send_message(
                chat_id, __("discovery.no_role_account"), reply_markup=discovery_menu_keyboard()
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
                chat_id, __("accounts.missing_github"), reply_markup=promo_menu_keyboard()
            )
            return
        ids = await self._ids_for_roles(tid, ("promo", "full"))
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

    async def _finish_pick(self, chat_id: int, user: User, t: str) -> None:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        intent = str(state.context.get("intent") or "")
        aid = validate_account_id(t)
        if not aid:
            await self.tg.send_message(chat_id, __("accounts.invalid_id"))
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
        await self._apply_profile_intent(chat_id, user, aid, intent)
        await UserState.clear(self.db, tid)

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
                chat_id, __("accounts.error", error=str(exc)[:240])
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
            reply_markup=discovery_menu_keyboard()
            if intent.startswith(("inspect", "harvest"))
            else promo_menu_keyboard(),
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
                chat_id, __("accounts.error", error=str(exc)[:240])
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
                chat_id, __("accounts.error", error=str(exc)[:240])
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

    async def _dispatch_pool(
        self,
        chat_id: int,
        user: User,
        *,
        action: str,
        status_filter: str = "",
        ref: str = "",
    ) -> None:
        runner = self._runner()
        if not runner:
            await self.tg.send_message(
                chat_id, __("accounts.missing_github"), reply_markup=discovery_menu_keyboard()
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
            )
        except GitHubError as exc:
            await self.tg.send_message(
                chat_id,
                __("accounts.error", error=str(exc)[:240]),
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

    async def _pool_mutate(
        self, chat_id: int, user: User, t: str, *, action: str
    ) -> None:
        tid = int(user.get("telegram_id"))
        ref = (t or "").strip()
        if not ref or ref.startswith("/") or ref in {
            __("accounts.btn_cancel"),
            __("accounts.btn_back"),
        }:
            await self.tg.send_message(chat_id, __("pool.invalid_ref"))
            return
        await UserState.clear(self.db, tid)
        await self._dispatch_pool(chat_id, user, action=action, ref=ref)
