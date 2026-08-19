"""Smart Assignment Controller — Telegram UI for auto-assigning routes.

Flow overview
-------------
Entry: "🏭 تخصیص هوشمند" button

Main menu:
  ├─ "📨 فوروارد جدید"   → forward assignment wizard
  ├─ "📣 پرومو جدید"     → promo assignment wizard
  ├─ "📋 لیست تخصیص‌ها"  → view all active assignments
  └─ "🔍 پیش‌نمایش"      → dry-run: show which account would be chosen

Forward wizard:
  1. Ask: source channel
  2. Ask: destination channel
  3. Show preview card (engine ranking, score, reason)
  4. Confirm → assign + dispatch

Promo wizard:
  1. Ask: source channel
  2. Ask: groups (comma-separated)
  3. Show preview card
  4. Confirm → assign + dispatch

List view:
  - Shows all active assignments grouped by account
  - Each item shows: source → target / account / score
  - Offers "🗑 حذف" + assignment_id

Remove flow:
  - User sends: "حذف <assignment_id>"
  - Controller removes the D1 record (profile not touched automatically)
"""
from __future__ import annotations

import json
from typing import Any

from app.Models.User import User
from app.Models.UserState import UserState
from app.Services.AssignmentService import (
    AssignmentService,
    NoEligibleAccountError,
)
from app.Services.GitHubService import GitHubError
from app.Services.RunOrchestratorService import RunOrchestratorService
from app.Services.TelegramService import TelegramService
from app.Support.ErrorFormat import friendly_error
from app.Support.GithubFactory import make_scaffold
from app.Support.Lang import __
from config.bot import BotConfig
from config.menus import main_keyboard

# ------------------------------------------------------------------
# States
# ------------------------------------------------------------------

ST_ASSIGN_MENU = "assign_menu"
ST_ASSIGN_FWD_SOURCE = "assign_fwd_source"
ST_ASSIGN_FWD_DEST = "assign_fwd_dest"
ST_ASSIGN_FWD_CONFIRM = "assign_fwd_confirm"
ST_ASSIGN_PROMO_SOURCE = "assign_promo_source"
ST_ASSIGN_PROMO_GROUPS = "assign_promo_groups"
ST_ASSIGN_PROMO_CONFIRM = "assign_promo_confirm"
ST_ASSIGN_PREVIEW_TYPE = "assign_preview_type"
ST_ASSIGN_PREVIEW_SOURCE = "assign_preview_source"
ST_ASSIGN_REMOVE = "assign_remove"

_ALL_STATES = frozenset(
    {
        ST_ASSIGN_MENU,
        ST_ASSIGN_FWD_SOURCE,
        ST_ASSIGN_FWD_DEST,
        ST_ASSIGN_FWD_CONFIRM,
        ST_ASSIGN_PROMO_SOURCE,
        ST_ASSIGN_PROMO_GROUPS,
        ST_ASSIGN_PROMO_CONFIRM,
        ST_ASSIGN_PREVIEW_TYPE,
        ST_ASSIGN_PREVIEW_SOURCE,
        ST_ASSIGN_REMOVE,
    }
)


def _cancel_texts() -> frozenset[str]:
    return frozenset({"/cancel", __("accounts.btn_cancel"), "انصراف"})


def _back_texts() -> frozenset[str]:
    return frozenset({__("accounts.btn_back"), "بازگشت", "منوی اصلی"})


# ------------------------------------------------------------------
# Keyboard helpers
# ------------------------------------------------------------------


def _assign_main_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("assign.btn_forward")},
                {"text": __("assign.btn_promo")},
            ],
            [
                {"text": __("assign.btn_list")},
                {"text": __("assign.btn_preview")},
            ],
            [
                {"text": __("assign.btn_remove")},
                {"text": __("accounts.btn_back")},
            ],
        ],
        "resize_keyboard": True,
    }


def _confirm_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("assign.btn_confirm")},
                {"text": __("accounts.btn_cancel")},
            ]
        ],
        "resize_keyboard": True,
    }


def _preview_type_keyboard() -> dict:
    return {
        "keyboard": [
            [{"text": "forward"}, {"text": "promo"}],
            [{"text": __("accounts.btn_cancel")}],
        ],
        "resize_keyboard": True,
    }


# ------------------------------------------------------------------
# Controller
# ------------------------------------------------------------------


class AssignmentController:
    def __init__(self, tg: TelegramService, config: BotConfig) -> None:
        self.tg = tg
        self.config = config
        self.db = config.db

    def _make_service(self, *, with_runner: bool = True) -> AssignmentService | None:
        scaffold = make_scaffold(self.config)
        if not scaffold:
            return None
        runner: RunOrchestratorService | None = None
        if with_runner:
            from app.Support.GithubFactory import make_github
            gh = make_github(self.config)
            if gh:
                runner = RunOrchestratorService(self.db, gh)
        return AssignmentService(self.db, scaffold, runner)

    async def _no_github(self, chat_id: int) -> None:
        await self.tg.send_message(
            chat_id,
            __("accounts.missing_github"),
            reply_markup=main_keyboard(),
        )

    # ------------------------------------------------------------------
    # Entry + routing
    # ------------------------------------------------------------------

    async def open_menu(self, chat_id: int, user: User) -> None:
        tid = int(user.get("telegram_id"))
        await UserState.set_state(self.db, tid, ST_ASSIGN_MENU, {})
        await self.tg.send_message(
            chat_id,
            __("assign.menu"),
            reply_markup=_assign_main_keyboard(),
        )

    async def handle(self, chat_id: int, user: User, text: str) -> bool:
        t = (text or "").strip()
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        current = str(state.get("state") or "")

        # Entry
        if t in {__("assign.btn_menu"), "🏭 تخصیص هوشمند", "تخصیص هوشمند"}:
            await self.open_menu(chat_id, user)
            return True

        # Only handle when in one of our states OR when the entry texts match
        if current not in _ALL_STATES:
            return False

        # Global cancel/back
        if t in _cancel_texts():
            await UserState.clear(self.db, tid)
            await self.open_menu(chat_id, user)
            return True
        if t in _back_texts():
            await UserState.clear(self.db, tid)
            await self.open_menu(chat_id, user)
            return True

        ctx = state.context or {}

        # Dispatch by current state
        if current == ST_ASSIGN_MENU:
            return await self._handle_menu(chat_id, user, t, tid)

        if current == ST_ASSIGN_FWD_SOURCE:
            await self._fwd_got_source(chat_id, tid, t)
            return True
        if current == ST_ASSIGN_FWD_DEST:
            await self._fwd_got_dest(chat_id, tid, t, ctx)
            return True
        if current == ST_ASSIGN_FWD_CONFIRM:
            await self._fwd_confirm(chat_id, user, t, ctx)
            return True

        if current == ST_ASSIGN_PROMO_SOURCE:
            await self._promo_got_source(chat_id, tid, t)
            return True
        if current == ST_ASSIGN_PROMO_GROUPS:
            await self._promo_got_groups(chat_id, tid, t, ctx)
            return True
        if current == ST_ASSIGN_PROMO_CONFIRM:
            await self._promo_confirm(chat_id, user, t, ctx)
            return True

        if current == ST_ASSIGN_PREVIEW_TYPE:
            await self._preview_got_type(chat_id, tid, t)
            return True
        if current == ST_ASSIGN_PREVIEW_SOURCE:
            await self._preview_got_source(chat_id, user, t, ctx)
            return True

        if current == ST_ASSIGN_REMOVE:
            await self._remove_got_id(chat_id, user, t)
            return True

        return False

    async def _handle_menu(
        self, chat_id: int, user: User, t: str, tid: int
    ) -> bool:
        if t == __("assign.btn_forward"):
            await UserState.set_state(self.db, tid, ST_ASSIGN_FWD_SOURCE, {})
            await self.tg.send_message(
                chat_id,
                __("assign.ask_fwd_source"),
                reply_markup=_confirm_keyboard(),
            )
            return True
        if t == __("assign.btn_promo"):
            await UserState.set_state(self.db, tid, ST_ASSIGN_PROMO_SOURCE, {})
            await self.tg.send_message(
                chat_id,
                __("assign.ask_promo_source"),
                reply_markup=_confirm_keyboard(),
            )
            return True
        if t == __("assign.btn_list"):
            await self._show_list(chat_id, user)
            return True
        if t == __("assign.btn_preview"):
            await UserState.set_state(self.db, tid, ST_ASSIGN_PREVIEW_TYPE, {})
            await self.tg.send_message(
                chat_id,
                __("assign.ask_preview_type"),
                reply_markup=_preview_type_keyboard(),
            )
            return True
        if t == __("assign.btn_remove"):
            await UserState.set_state(self.db, tid, ST_ASSIGN_REMOVE, {})
            await self.tg.send_message(
                chat_id,
                __("assign.ask_remove_id"),
                reply_markup=_assign_main_keyboard(),
            )
            return True
        return False

    # ------------------------------------------------------------------
    # Forward wizard
    # ------------------------------------------------------------------

    async def _fwd_got_source(self, chat_id: int, tid: int, t: str) -> None:
        if not t.strip():
            await self.tg.send_message(chat_id, __("assign.bad_ref"))
            return
        await UserState.set_state(
            self.db, tid, ST_ASSIGN_FWD_DEST, {"source": t.strip()}
        )
        await self.tg.send_message(chat_id, __("assign.ask_fwd_dest"))

    async def _fwd_got_dest(
        self, chat_id: int, tid: int, t: str, ctx: dict
    ) -> None:
        if not t.strip():
            await self.tg.send_message(chat_id, __("assign.bad_ref"))
            return
        source = str(ctx.get("source") or "")
        dest = t.strip()
        await UserState.set_state(
            self.db, tid, ST_ASSIGN_FWD_CONFIRM, {"source": source, "dest": dest}
        )
        # Show preview
        await self._show_preview_and_confirm(
            chat_id, tid, "forward", source, dest=dest
        )

    async def _fwd_confirm(
        self, chat_id: int, user: User, t: str, ctx: dict
    ) -> None:
        tid = int(user.get("telegram_id"))
        if t != __("assign.btn_confirm"):
            await self.tg.send_message(chat_id, __("assign.cancelled"))
            await UserState.clear(self.db, tid)
            await self.open_menu(chat_id, user)
            return
        svc = self._make_service()
        if not svc:
            await self._no_github(chat_id)
            return
        source = str(ctx.get("source") or "")
        dest = str(ctx.get("dest") or "")
        await self.tg.send_message(chat_id, __("assign.working"))
        try:
            result = await svc.assign_forward(
                int(user.get("telegram_id")), source, dest, auto_dispatch=True
            )
        except NoEligibleAccountError as exc:
            await UserState.clear(self.db, tid)
            await self.tg.send_message(
                chat_id,
                __("assign.no_eligible", reason=exc.reason),
                reply_markup=_assign_main_keyboard(),
            )
            return
        except (GitHubError, ValueError, Exception) as exc:
            await UserState.clear(self.db, tid)
            await self.tg.send_message(
                chat_id,
                __("accounts.error", error=friendly_error(exc)),
                reply_markup=_assign_main_keyboard(),
            )
            return
        await UserState.clear(self.db, tid)
        await self.tg.send_message(
            chat_id,
            _format_result(result),
            reply_markup=_assign_main_keyboard(),
        )

    # ------------------------------------------------------------------
    # Promo wizard
    # ------------------------------------------------------------------

    async def _promo_got_source(self, chat_id: int, tid: int, t: str) -> None:
        if not t.strip():
            await self.tg.send_message(chat_id, __("assign.bad_ref"))
            return
        await UserState.set_state(
            self.db, tid, ST_ASSIGN_PROMO_GROUPS, {"source": t.strip()}
        )
        await self.tg.send_message(chat_id, __("assign.ask_promo_groups"))

    async def _promo_got_groups(
        self, chat_id: int, tid: int, t: str, ctx: dict
    ) -> None:
        if not t.strip():
            await self.tg.send_message(chat_id, __("assign.bad_ref"))
            return
        source = str(ctx.get("source") or "")
        groups_raw = t.strip()
        await UserState.set_state(
            self.db,
            tid,
            ST_ASSIGN_PROMO_CONFIRM,
            {"source": source, "groups": groups_raw},
        )
        await self._show_preview_and_confirm(
            chat_id, tid, "promo", source, groups_raw=groups_raw
        )

    async def _promo_confirm(
        self, chat_id: int, user: User, t: str, ctx: dict
    ) -> None:
        tid = int(user.get("telegram_id"))
        if t != __("assign.btn_confirm"):
            await self.tg.send_message(chat_id, __("assign.cancelled"))
            await UserState.clear(self.db, tid)
            await self.open_menu(chat_id, user)
            return
        svc = self._make_service()
        if not svc:
            await self._no_github(chat_id)
            return
        source = str(ctx.get("source") or "")
        groups_raw = str(ctx.get("groups") or "")
        groups = [
            g.strip()
            for g in groups_raw.replace("،", ",").split(",")
            if g.strip()
        ]
        await self.tg.send_message(chat_id, __("assign.working"))
        try:
            result = await svc.assign_promo(
                int(user.get("telegram_id")), source, groups, auto_dispatch=True
            )
        except NoEligibleAccountError as exc:
            await UserState.clear(self.db, tid)
            await self.tg.send_message(
                chat_id,
                __("assign.no_eligible", reason=exc.reason),
                reply_markup=_assign_main_keyboard(),
            )
            return
        except (GitHubError, ValueError, Exception) as exc:
            await UserState.clear(self.db, tid)
            await self.tg.send_message(
                chat_id,
                __("accounts.error", error=friendly_error(exc)),
                reply_markup=_assign_main_keyboard(),
            )
            return
        await UserState.clear(self.db, tid)
        await self.tg.send_message(
            chat_id,
            _format_result(result),
            reply_markup=_assign_main_keyboard(),
        )

    # ------------------------------------------------------------------
    # Preview (dry-run)
    # ------------------------------------------------------------------

    async def _preview_got_type(self, chat_id: int, tid: int, t: str) -> None:
        if t not in {"forward", "promo"}:
            await self.tg.send_message(chat_id, __("assign.bad_type"))
            return
        await UserState.set_state(
            self.db, tid, ST_ASSIGN_PREVIEW_SOURCE, {"task_type": t}
        )
        await self.tg.send_message(chat_id, __("assign.ask_preview_source"))

    async def _preview_got_source(
        self, chat_id: int, user: User, t: str, ctx: dict
    ) -> None:
        tid = int(user.get("telegram_id"))
        task_type = str(ctx.get("task_type") or "forward")
        source = t.strip()
        svc = self._make_service(with_runner=False)
        if not svc:
            await self._no_github(chat_id)
            return
        await UserState.clear(self.db, tid)
        try:
            ranked = await svc.preview(
                int(user.get("telegram_id")), task_type, source
            )
        except Exception as exc:
            await self.tg.send_message(
                chat_id,
                __("accounts.error", error=friendly_error(exc)),
                reply_markup=_assign_main_keyboard(),
            )
            return
        await self.tg.send_message(
            chat_id,
            _format_preview(ranked, task_type=task_type, source=source),
            reply_markup=_assign_main_keyboard(),
        )

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    async def _show_list(self, chat_id: int, user: User) -> None:
        svc = self._make_service(with_runner=False)
        if not svc:
            await self._no_github(chat_id)
            return
        tid = int(user.get("telegram_id"))
        rows = await svc.list(tid)
        load = await svc.get_account_load(tid)
        if not rows:
            await self.tg.send_message(
                chat_id,
                __("assign.list_empty"),
                reply_markup=_assign_main_keyboard(),
            )
            return
        await self.tg.send_message(
            chat_id,
            _format_list(rows, load),
            reply_markup=_assign_main_keyboard(),
        )

    # ------------------------------------------------------------------
    # Remove
    # ------------------------------------------------------------------

    async def _remove_got_id(
        self, chat_id: int, user: User, t: str
    ) -> None:
        tid = int(user.get("telegram_id"))
        assignment_id = t.strip().removeprefix("حذف").strip()
        if not assignment_id:
            await self.tg.send_message(chat_id, __("assign.bad_remove_id"))
            return
        svc = self._make_service(with_runner=False)
        if not svc:
            await self._no_github(chat_id)
            return
        try:
            await svc.remove(assignment_id, user_id=tid)
        except Exception as exc:
            await UserState.clear(self.db, tid)
            await self.tg.send_message(
                chat_id,
                __("accounts.error", error=friendly_error(exc)),
                reply_markup=_assign_main_keyboard(),
            )
            return
        await UserState.clear(self.db, tid)
        await self.tg.send_message(
            chat_id,
            __("assign.remove_done", assignment_id=assignment_id),
            reply_markup=_assign_main_keyboard(),
        )

    # ------------------------------------------------------------------
    # Preview card helper (used during confirm step)
    # ------------------------------------------------------------------

    async def _show_preview_and_confirm(
        self,
        chat_id: int,
        tid: int,
        task_type: str,
        source: str,
        *,
        dest: str | None = None,
        groups_raw: str | None = None,
    ) -> None:
        svc = self._make_service(with_runner=False)
        if not svc:
            await self._no_github(chat_id)
            return
        try:
            ranked = await svc.preview(tid, task_type, source)
        except Exception:
            ranked = []

        if not ranked:
            # No eligible account — inform now so user knows what confirm will do
            text = __("assign.preview_none", task_type=task_type, source=source)
        else:
            winner = ranked[0]
            lines = [
                __("assign.preview_header", task_type=task_type, source=source),
                "",
                __("assign.preview_winner",
                   account_id=winner.account_id,
                   score=round(winner.score, 3)),
            ]
            if dest:
                lines.append(__("assign.preview_dest", dest=dest))
            if groups_raw:
                lines.append(__("assign.preview_groups", groups=groups_raw))
            lines.append("")
            lines.append(__("assign.preview_breakdown"))
            for rule_name, s in winner.breakdown.items():
                lines.append(f"  • <code>{rule_name}</code>: {round(s, 3)}")
            if len(ranked) > 1:
                lines.append("")
                lines.append(__("assign.preview_runner_up",
                                account_id=ranked[1].account_id,
                                score=round(ranked[1].score, 3)))
            text = "\n".join(lines)

        await self.tg.send_message(
            chat_id, text, reply_markup=_confirm_keyboard()
        )


# ------------------------------------------------------------------
# Formatting helpers
# ------------------------------------------------------------------


def _format_result(result: Any) -> str:
    from app.Services.AssignmentService import AssignmentResult
    if not isinstance(result, AssignmentResult):
        return str(result)
    dispatch = result.dispatch_info or {}
    run_id = dispatch.get("run_id") or "—"
    dispatch_url = dispatch.get("html_url") or ""
    sticky_note = " ♻️" if result.was_sticky else ""
    lines = [
        __("assign.result_header"),
        "",
        __("assign.result_account",
           account_id=result.account_id,
           label=result.account_label) + sticky_note,
        __("assign.result_type", task_type=result.task_type),
        __("assign.result_source", source=result.source),
    ]
    if result.target:
        target_display = result.target
        try:
            groups = json.loads(result.target)
            if isinstance(groups, list):
                target_display = ", ".join(groups)
        except Exception:
            pass
        lines.append(__("assign.result_target", target=target_display))
    lines.append(__("assign.result_score", score=round(result.score, 3)))
    lines.append(__("assign.result_id", assignment_id=result.assignment_id))
    if run_id != "—":
        lines.append(__("assign.result_dispatch", run_id=run_id, url=dispatch_url))
    return "\n".join(lines)


def _format_preview(ranked: list, *, task_type: str, source: str) -> str:
    if not ranked:
        return __("assign.preview_none", task_type=task_type, source=source)
    lines = [
        __("assign.preview_header", task_type=task_type, source=source),
        "",
    ]
    for i, sa in enumerate(ranked[:5], 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        lines.append(
            f"{medal} <code>{sa.account_id}</code> — امتیاز: {round(sa.score, 3)}"
        )
        for rule_name, s in sa.breakdown.items():
            lines.append(f"    • {rule_name}: {round(s, 3)}")
    return "\n".join(lines)


def _format_list(rows: list[dict], load: dict) -> str:
    lines = [__("assign.list_header", count=len(rows)), ""]
    by_account: dict[str, list[dict]] = {}
    for r in rows:
        aid = str(r.get("account_id") or "?")
        by_account.setdefault(aid, []).append(r)

    for aid, items in by_account.items():
        acct_load = load.get(aid, {})
        lines.append(
            f"<b>{aid}</b> — fw:{acct_load.get('forward',0)} "
            f"promo:{acct_load.get('promo',0)}"
        )
        for item in items:
            tt = str(item.get("task_type") or "")
            src = str(item.get("source") or "")
            target_raw = str(item.get("target") or "")
            try:
                groups = json.loads(target_raw)
                target_display = ", ".join(groups) if isinstance(groups, list) else target_raw
            except Exception:
                target_display = target_raw
            aid_short = str(item.get("id") or "")[:8]
            lines.append(
                f"  [{tt}] {src} → {target_display[:30]}"
                f"\n        ID: <code>{aid_short}…</code>"
            )
        lines.append("")
    lines.append(__("assign.list_remove_hint"))
    return "\n".join(lines)
