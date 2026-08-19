"""GHA → Worker: pool-admin result (+ optional to_promo auto-patch)."""
from __future__ import annotations

import json

from app.Models.Assignment import Assignment
from app.Services.RunOrchestratorService import RunOrchestratorService
from app.Services.ProfileConfigService import ProfileConfigService
from app.Services.TelegramService import TelegramService
from app.Support.BridgeAuth import require_bridge_token
from app.Support.GithubFactory import make_github, make_scaffold
from app.Support.Lang import __
from config.bot import BotConfig
from workers import Response


class InternalPoolController:
    def __init__(self, env) -> None:
        self.config = BotConfig(env)

    async def handle(self, request) -> Response:
        denied = require_bridge_token(request, self.config)
        if denied is not None:
            return denied

        try:
            data = await request.json()
            if hasattr(data, "to_py"):
                data = data.to_py()
        except Exception:
            return Response.json({"ok": False, "error": "bad_json"}, status=400)

        if not isinstance(data, dict):
            return Response.json({"ok": False, "error": "bad_json"}, status=400)

        chat_raw = data.get("notify_chat_id") or data.get("notify_user_id")
        try:
            chat_id = int(chat_raw)
        except (TypeError, ValueError):
            return Response.json({"ok": False, "error": "missing_notify"}, status=400)

        tg = TelegramService(self.config.telegram_token)
        body = self._format(data)

        # Optional: auto attach approved pool item to promo route.
        extra = ""
        if str(data.get("intent") or "") == "to_promo":
            extra = await self._maybe_to_promo(data)

        try:
            await tg.send_message(chat_id, body + (("\n\n" + extra) if extra else ""))
        except Exception as exc:
            return Response.json(
                {"ok": False, "error": str(exc)[:200]}, status=502
            )
        return Response.json({"ok": True})

    async def _maybe_to_promo(self, data: dict) -> str:
        item = data.get("item") or {}
        if not data.get("found") or str(item.get("status") or "") != "approved":
            return __(
                "pool.to_promo_blocked",
                status=(item.get("status") if item else "missing"),
            )
        promo_id = str(data.get("promo_account_id") or "").strip()
        source = str(data.get("source_channel") or "").strip()
        ref = str(item.get("ref") or "").strip()
        user_id = int(data.get("notify_user_id") or 0)
        if not (promo_id and source and ref and user_id):
            return __("pool.to_promo_missing_fields")
        scaffold = make_scaffold(self.config)
        if not scaffold:
            return __("accounts.missing_github")
        try:
            profile = ProfileConfigService(self.config.db, scaffold)
            await profile.to_promo(
                user_id, promo_id, source, ref
            )
            try:
                await Assignment.create(
                    self.config.db,
                    user_id=user_id,
                    account_id=promo_id,
                    task_type="promo",
                    source=source,
                    target=json.dumps([ref], ensure_ascii=False),
                )
            except Exception:
                pass
            gh = make_github(self.config)
            if gh:
                try:
                    await RunOrchestratorService(
                        self.config.db, gh
                    ).dispatch(user_id, promo_id)
                except Exception:
                    pass
        except Exception as exc:
            return __("accounts.error", error=str(exc)[:200])
        return __(
            "pool.to_promo_done",
            account_id=promo_id,
            source=source,
            ref=ref,
        )

    def _format(self, data: dict) -> str:
        action = data.get("action") or "-"
        if not data.get("ok", True):
            return __(
                "pool.report_error",
                action=action,
                error=data.get("error") or "failed",
                url=data.get("run_url") or "",
            )

        counts = data.get("counts") or {}
        counts_txt = " · ".join(
            f"{k}={v}" for k, v in counts.items() if k != "total"
        )
        if action == "status":
            return __(
                "pool.report_status",
                total=counts.get("total", 0),
                counts=counts_txt or "-",
                url=data.get("run_url") or "",
            )
        if action == "get":
            item = data.get("item") or {}
            if not data.get("found"):
                return __(
                    "pool.report_get_missing",
                    url=data.get("run_url") or "",
                )
            return __(
                "pool.report_get",
                ref=item.get("ref") or "-",
                status=item.get("status") or "-",
                title=item.get("title") or "-",
                url=data.get("run_url") or "",
            )
        if action == "list":
            items = data.get("items") or []
            lines = []
            for row in items[:20]:
                lines.append(
                    f"• <code>{row.get('ref')}</code> [{row.get('status')}]"
                )
            listing = "\n".join(lines) if lines else "—"
            return __(
                "pool.report_list",
                filter=data.get("status_filter") or "all",
                listing=listing,
                counts=counts_txt or "-",
                url=data.get("run_url") or "",
            )
        if action in {"approve", "reject"}:
            item = data.get("item") or {}
            return __(
                "pool.report_mutate",
                action=action,
                ref=item.get("ref") or "-",
                status=item.get("status") or "-",
                counts=counts_txt or "-",
                url=data.get("run_url") or "",
            )
        return __(
            "pool.report_generic",
            action=action,
            url=data.get("run_url") or "",
        )
