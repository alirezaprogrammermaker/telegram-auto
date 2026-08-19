"""Remote command control panel — send instant commands to live userbot accounts.

Admin flow:
  "کنترل زنده" button → pick account → pick command → (optional payload) → confirm → send
  The command is enqueued in D1 and the userbot picks it up within poll_interval seconds.
"""
from __future__ import annotations

import json

from app.Models.Command import VALID_TYPES, AccountHeartbeat, Command
from app.Models.User import User
from app.Models.UserState import UserState
from app.Services.AccountScaffoldService import validate_account_id
from app.Services.AccountService import AccountConflictError, AccountService
from app.Services.TelegramService import TelegramService
from app.Support.Lang import __
from app.Support.StatusFormat import format_live_metrics
from config.bot import BotConfig
from config.menus import accounts_pick_keyboard, main_keyboard

ST_CMD_MENU = "cmd_menu"
ST_CMD_PICK_ACCOUNT = "cmd_pick_account"
ST_CMD_PICK_TYPE = "cmd_pick_type"
ST_CMD_PAYLOAD = "cmd_payload"
ST_CMD_CONFIRM = "cmd_confirm"
ST_CMD_STATUS_PICK = "cmd_status_pick"

CANCEL_TEXTS = frozenset({"/cancel", "انصراف", __("accounts.btn_cancel") if False else "انصراف"})

# Human-readable labels for command types
CMD_LABELS: dict[str, str] = {
    "ping": "ping — تست اتصال",
    "module_on": "module_on — روشن کردن ماژول",
    "module_off": "module_off — خاموش کردن ماژول",
    "module_reload": "module_reload — ری‌لود ماژول",
    "config_patch": "config_patch — تغییر تنظیمات",
    "pause_route": "pause_route — توقف موقت مسیر",
    "resume_route": "resume_route — ادامه مسیر",
    "flush_queue": "flush_queue — پاک کردن صف",
    "heartbeat_request": "heartbeat — وضعیت زنده",
}

# Commands that need extra payload input
NEEDS_PAYLOAD: frozenset[str] = frozenset(
    {
        "module_on",
        "module_off",
        "module_reload",
        "config_patch",
        "pause_route",
        "resume_route",
        "flush_queue",
    }
)

PAYLOAD_HINTS: dict[str, str] = {
    "module_on": 'نام ماژول را بنویس (مثال: channel_forward)',
    "module_off": 'نام ماژول را بنویس (مثال: promo_spread)',
    "module_reload": 'نام ماژول را بنویس',
    "config_patch": 'JSON بده مثال:\n{"module":"channel_forward","patch":{"routes":[]},"reload":true}',
    "pause_route": 'مبدأ مسیر را بنویس (مثال: @channel_username)',
    "resume_route": 'مبدأ مسیر را بنویس',
    "flush_queue": '"forward" یا "promo" بنویس',
}


class CommandController:
    def __init__(self, tg: TelegramService, config: BotConfig) -> None:
        self.tg = tg
        self.config = config
        self.db = config.db

    async def open_menu(self, chat_id: int, user: User) -> None:
        tid = int(user.get("telegram_id"))
        await UserState.set_state(self.db, tid, ST_CMD_MENU, {})
        await self.tg.send_message(
            chat_id,
            __("cmd.menu"),
            reply_markup=_cmd_main_keyboard(),
        )

    async def handle(self, chat_id: int, user: User, text: str) -> bool:
        tid = int(user.get("telegram_id"))
        t = (text or "").strip()
        state = await UserState.get_or_idle(self.db, tid)
        current = str(state.get("state") or "")

        # Entry point
        if t in {__("cmd.btn_menu"), "کنترل زنده", "🎮 کنترل زنده"}:
            await self.open_menu(chat_id, user)
            return True

        if current not in {
            ST_CMD_MENU,
            ST_CMD_PICK_ACCOUNT,
            ST_CMD_PICK_TYPE,
            ST_CMD_PAYLOAD,
            ST_CMD_CONFIRM,
            ST_CMD_STATUS_PICK,
        }:
            return False

        # Navigate away
        if t in {__("accounts.btn_back"), "منوی اصلی"}:
            await UserState.clear(self.db, tid)
            await self.tg.send_message(
                chat_id,
                __("auth.welcome_admin", name=user.display_name),
                reply_markup=main_keyboard(),
            )
            return True

        if t in {"/cancel", __("accounts.btn_cancel"), "انصراف"}:
            await UserState.clear(self.db, tid)
            await self.tg.send_message(
                chat_id, __("cmd.cancelled"), reply_markup=main_keyboard()
            )
            return True

        if current == ST_CMD_MENU:
            return await self._handle_menu(chat_id, user, t)
        if current == ST_CMD_PICK_ACCOUNT:
            return await self._handle_pick_account(chat_id, user, t)
        if current == ST_CMD_PICK_TYPE:
            return await self._handle_pick_type(chat_id, user, t)
        if current == ST_CMD_PAYLOAD:
            return await self._handle_payload(chat_id, user, t)
        if current == ST_CMD_CONFIRM:
            return await self._handle_confirm(chat_id, user, t)
        if current == ST_CMD_STATUS_PICK:
            return await self._handle_status_pick(chat_id, user, t)
        return False

    async def _handle_menu(self, chat_id: int, user: User, t: str) -> bool:
        tid = int(user.get("telegram_id"))

        if t in {__("cmd.btn_send"), "ارسال دستور", "📤 ارسال دستور"}:
            rows = await AccountService(self.db).list_for_user(tid)
            ids = [str(r.get("id")) for r in rows if r.get("id")]
            if not ids:
                await self.tg.send_message(
                    chat_id, __("accounts.list_empty"), reply_markup=_cmd_main_keyboard()
                )
                return True
            await UserState.set_state(self.db, tid, ST_CMD_PICK_ACCOUNT, {"mode": "send"})
            await self.tg.send_message(
                chat_id, __("cmd.pick_account"), reply_markup=accounts_pick_keyboard(ids)
            )
            return True

        if t in {__("cmd.btn_status"), "وضعیت اکانت‌ها", "📡 وضعیت زنده"}:
            rows = await AccountService(self.db).list_for_user(tid)
            ids = [str(r.get("id")) for r in rows if r.get("id")]
            if not ids:
                await self.tg.send_message(
                    chat_id, __("accounts.list_empty"), reply_markup=_cmd_main_keyboard()
                )
                return True
            await UserState.set_state(self.db, tid, ST_CMD_STATUS_PICK, {})
            await self.tg.send_message(
                chat_id, __("cmd.pick_account_status"), reply_markup=accounts_pick_keyboard(ids)
            )
            return True

        await self.tg.send_message(
            chat_id, __("cmd.menu"), reply_markup=_cmd_main_keyboard()
        )
        return True

    async def _handle_pick_account(self, chat_id: int, user: User, t: str) -> bool:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        mode = str(state.context.get("mode") or "send")

        aid = validate_account_id(t)
        if not aid:
            await self.tg.send_message(chat_id, __("accounts.invalid_id"))
            return True
        try:
            await AccountService(self.db).require_owned(tid, aid)
        except AccountConflictError:
            await self.tg.send_message(
                chat_id, __("accounts.not_owned", account_id=t)
            )
            return True

        await UserState.set_state(
            self.db, tid, ST_CMD_PICK_TYPE, {"account_id": aid, "mode": mode}
        )
        await self.tg.send_message(
            chat_id,
            __("cmd.pick_type", account_id=aid),
            reply_markup=_cmd_type_keyboard(),
        )
        return True

    async def _handle_pick_type(self, chat_id: int, user: User, t: str) -> bool:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")

        # Match by label prefix (e.g. "ping — تست اتصال" → "ping")
        cmd_type = None
        for ct, label in CMD_LABELS.items():
            if t == label or t == ct or t.startswith(ct):
                cmd_type = ct
                break

        if not cmd_type or cmd_type not in VALID_TYPES:
            await self.tg.send_message(
                chat_id, __("cmd.invalid_type"), reply_markup=_cmd_type_keyboard()
            )
            return True

        if cmd_type in NEEDS_PAYLOAD:
            await UserState.set_state(
                self.db, tid, ST_CMD_PAYLOAD, {"account_id": aid, "cmd_type": cmd_type}
            )
            hint = PAYLOAD_HINTS.get(cmd_type, "مقدار لازم را بنویس")
            await self.tg.send_message(
                chat_id,
                __("cmd.ask_payload", cmd_type=cmd_type, hint=hint),
                reply_markup=_cancel_keyboard(),
            )
        else:
            # No payload needed — go straight to confirm
            await UserState.set_state(
                self.db, tid, ST_CMD_CONFIRM, {"account_id": aid, "cmd_type": cmd_type, "payload": {}}
            )
            await self.tg.send_message(
                chat_id,
                __("cmd.confirm", account_id=aid, cmd_type=cmd_type, payload="{}"),
                reply_markup=_confirm_keyboard(),
            )
        return True

    async def _handle_payload(self, chat_id: int, user: User, t: str) -> bool:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        cmd_type = str(state.context.get("cmd_type") or "")

        payload = _parse_payload(t, cmd_type)
        if payload is None:
            await self.tg.send_message(
                chat_id,
                __("cmd.invalid_payload", hint=PAYLOAD_HINTS.get(cmd_type, "")),
                reply_markup=_cancel_keyboard(),
            )
            return True

        await UserState.set_state(
            self.db, tid, ST_CMD_CONFIRM,
            {"account_id": aid, "cmd_type": cmd_type, "payload": payload}
        )
        await self.tg.send_message(
            chat_id,
            __("cmd.confirm", account_id=aid, cmd_type=cmd_type, payload=json.dumps(payload, ensure_ascii=False)),
            reply_markup=_confirm_keyboard(),
        )
        return True

    async def _handle_confirm(self, chat_id: int, user: User, t: str) -> bool:
        tid = int(user.get("telegram_id"))
        state = await UserState.get_or_idle(self.db, tid)
        aid = str(state.context.get("account_id") or "")
        cmd_type = str(state.context.get("cmd_type") or "")
        payload = state.context.get("payload") or {}

        if t not in {__("cmd.btn_confirm_send"), "تایید و ارسال", "✅ تایید و ارسال"}:
            await UserState.clear(self.db, tid)
            await self.tg.send_message(chat_id, __("cmd.cancelled"), reply_markup=main_keyboard())
            return True

        try:
            cmd = await Command.enqueue(
                self.db,
                account_id=aid,
                command_type=cmd_type,
                payload=payload,
                issued_by=str(tid),
            )
        except Exception as exc:
            await UserState.clear(self.db, tid)
            await self.tg.send_message(
                chat_id,
                __("cmd.enqueue_error", error=str(exc)[:200]),
                reply_markup=main_keyboard(),
            )
            return True

        await UserState.set_state(self.db, tid, ST_CMD_MENU, {})
        await self.tg.send_message(
            chat_id,
            __(
                "cmd.sent",
                cmd_id=str(cmd.get("id") or "")[:8],
                account_id=aid,
                cmd_type=cmd_type,
            ),
            reply_markup=_cmd_main_keyboard(),
        )
        return True

    async def _handle_status_pick(self, chat_id: int, user: User, t: str) -> bool:
        tid = int(user.get("telegram_id"))

        aid = validate_account_id(t)
        if not aid:
            await self.tg.send_message(chat_id, __("accounts.invalid_id"))
            return True
        try:
            await AccountService(self.db).require_owned(tid, aid)
        except AccountConflictError:
            await self.tg.send_message(
                chat_id, __("accounts.not_owned", account_id=t)
            )
            return True

        hb = await AccountHeartbeat.find(self.db, aid)
        recent = await Command.list_recent(self.db, aid, limit=5)

        lines = [f"📡 <b>وضعیت زنده: {aid}</b>", "────────────"]

        if hb:
            hb_view = hb.to_view()
            lines.append(f"وضعیت: <code>{hb_view['status']}</code>")
            lines.append(f"آخرین heartbeat: <code>{hb_view['updated_at']}</code>")
            meta = hb_view.get("meta") if isinstance(hb_view.get("meta"), dict) else {}
            metrics = meta.get("metrics") if isinstance(meta.get("metrics"), dict) else {}
            lines.append(
                format_live_metrics(
                    {
                        "heartbeat_stale": False,
                        "heartbeat_status": hb_view.get("status"),
                        "heartbeat_at": hb_view.get("updated_at"),
                        "stats_today": metrics.get("stats_today"),
                        "forward_queue_pending": metrics.get("forward_queue_pending"),
                        "promo_queue_pending": metrics.get("promo_queue_pending"),
                    }
                )
            )
            modules = hb_view.get("modules") or {}
            if modules:
                lines.append("ماژول‌ها:")
                for mod, st in modules.items():
                    icon = "🟢" if st == "running" else "⚪"
                    lines.append(f"  {icon} {mod}: {st}")
        else:
            lines.append("هنوز heartbeat دریافت نشده (ممکن است آفلاین باشد)")

        if recent:
            lines.append("────────────")
            lines.append("آخرین دستورات:")
            for c in recent:
                cv = c.to_view()
                status_icon = {"done": "✅", "failed": "❌", "pending": "⏳", "acked": "🔄"}.get(
                    str(cv["status"]), "❓"
                )
                lines.append(
                    f"  {status_icon} {cv['type']} [{cv['status']}] — {str(cv['id'])[:8]}…"
                )

        await UserState.set_state(self.db, tid, ST_CMD_MENU, {})
        await self.tg.send_message(
            chat_id, "\n".join(lines), reply_markup=_cmd_main_keyboard()
        )
        return True


# ---- keyboard helpers ----

def _cmd_main_keyboard() -> dict:
    return {
        "keyboard": [
            [{"text": __("cmd.btn_send")}, {"text": __("cmd.btn_status")}],
            [{"text": __("accounts.btn_back")}],
        ],
        "resize_keyboard": True,
    }


def _cmd_type_keyboard() -> dict:
    rows = []
    items = list(CMD_LABELS.values())
    for i in range(0, len(items), 2):
        row = [{"text": items[i]}]
        if i + 1 < len(items):
            row.append({"text": items[i + 1]})
        rows.append(row)
    rows.append([{"text": __("accounts.btn_cancel")}])
    return {"keyboard": rows, "resize_keyboard": True}


def _confirm_keyboard() -> dict:
    return {
        "keyboard": [
            [{"text": __("cmd.btn_confirm_send")}, {"text": __("accounts.btn_cancel")}]
        ],
        "resize_keyboard": True,
    }


def _cancel_keyboard() -> dict:
    return {
        "keyboard": [[{"text": __("accounts.btn_cancel")}]],
        "resize_keyboard": True,
    }


# ---- payload parsing ----

def _parse_payload(text: str, cmd_type: str) -> dict | None:
    """Convert user text input to a structured payload dict, or None if invalid."""
    t = text.strip()

    if cmd_type in {"module_on", "module_off", "module_reload"}:
        module = t.strip()
        if not module or " " in module:
            return None
        return {"module": module}

    if cmd_type in {"pause_route", "resume_route"}:
        source = t.strip()
        if not source:
            return None
        return {"source": source}

    if cmd_type == "flush_queue":
        q = t.strip().lower()
        if q not in {"forward", "promo"}:
            return None
        return {"queue": q}

    if cmd_type == "config_patch":
        try:
            data = json.loads(t)
            if not isinstance(data, dict):
                return None
            if "module" not in data or "patch" not in data:
                return None
            return data
        except (ValueError, TypeError):
            return None

    # Fallback: try JSON, else treat as string value
    try:
        data = json.loads(t)
        return data if isinstance(data, dict) else {"value": t}
    except (ValueError, TypeError):
        return {"value": t}
