"""Dynamic help guides from D1."""
from __future__ import annotations

from app.Models.User import User
from app.Models.UserState import UserState
from app.Support.HelpButtons import (
    back_hub_button,
    back_main_button,
    back_panel_button,
    is_help_button,
)
from app.Services.HelpGuideService import HelpGuideService
from app.Services.TelegramService import TelegramService
from app.Support.HelpGuideSeed import CATEGORY_META
from app.Support.Lang import __
from config.bot import BotConfig
from config.menus import (
    discovery_menu_keyboard,
    forward_menu_keyboard,
    help_categories_keyboard,
    help_hub_keyboard,
    help_topics_keyboard,
    main_keyboard,
    promo_menu_keyboard,
)

ST_HELP_HUB = "help_hub"
ST_HELP_CATEGORY = "help_category"

CANCEL_TEXTS = frozenset({"/cancel", "انصراف"})

PANEL_KEYBOARD = {
    "main": main_keyboard,
    "discovery": discovery_menu_keyboard,
    "promo": promo_menu_keyboard,
    "forward": forward_menu_keyboard,
    "help": help_hub_keyboard,
}


class HelpController:
    def __init__(self, tg: TelegramService, config: BotConfig) -> None:
        self.tg = tg
        self.config = config
        self.db = config.db

    def _svc(self) -> HelpGuideService:
        return HelpGuideService(self.db)

    def _kb(self, panel: str):
        return PANEL_KEYBOARD.get(panel, main_keyboard)

    async def show_hub(self, chat_id: int, user: User) -> None:
        tid = int(user.get("telegram_id"))
        svc = self._svc()
        categories = await svc.categories_with_counts()
        await UserState.set_state(self.db, tid, ST_HELP_HUB, {"panel": "main"})
        buttons = [
            svc.category_button(str(c.get("category") or ""), c)
            for c in categories
        ]
        await self.tg.send_message(
            chat_id,
            svc.format_hub(categories),
            reply_markup=help_categories_keyboard(buttons),
        )

    async def show_category(
        self,
        chat_id: int,
        user: User,
        category: str,
        *,
        panel: str = "help",
    ) -> None:
        tid = int(user.get("telegram_id"))
        svc = self._svc()
        guides = await svc.guides_for_category(category)
        if not guides:
            await self.tg.send_message(
                chat_id,
                await svc.fallback_content(category),
                reply_markup=self._kb(panel),
            )
            return
        await UserState.set_state(
            self.db,
            tid,
            ST_HELP_CATEGORY,
            {"category": category, "panel": panel},
        )
        buttons = [svc.topic_button(g) for g in guides]
        await self.tg.send_message(
            chat_id,
            svc.format_category_index(category, guides),
            reply_markup=help_topics_keyboard(
                buttons,
                back_label=(
                    back_hub_button()
                    if panel == "help"
                    else back_panel_button()
                ),
            ),
        )

    async def show_guide(
        self,
        chat_id: int,
        user: User,
        category: str,
        key: str,
        *,
        panel: str = "help",
    ) -> None:
        svc = self._svc()
        guide = await svc.get_guide(category, key)
        if not guide:
            await self.tg.send_message(
                chat_id,
                await svc.fallback_content(category),
                reply_markup=self._kb(panel),
            )
            return
        guides = await svc.guides_for_category(category)
        buttons = [svc.topic_button(g) for g in guides]
        await self.tg.send_message(
            chat_id,
            svc.format_guide(guide),
            reply_markup=help_topics_keyboard(
                buttons,
                back_label=(
                    back_hub_button()
                    if panel == "help"
                    else back_panel_button()
                ),
            ),
        )

    async def handle(self, chat_id: int, user: User, text: str) -> bool:
        tid = int(user.get("telegram_id"))
        t = (text or "").strip()
        state = await UserState.get_or_idle(self.db, tid)
        current = str(state.get("state") or "")

        if t in CANCEL_TEXTS | {__("accounts.btn_cancel")} and current.startswith(
            "help_"
        ):
            await UserState.clear(self.db, tid)
            await self.tg.send_message(
                chat_id, __("panel.cancelled"), reply_markup=main_keyboard()
            )
            return True

        if current.startswith("help_"):
            await self._handle_active(chat_id, user, t, current, state.context)
            return True

        if t in {
            __("menu.btn_help"),
            "راهنما",
            "📖 راهنما",
            "/help",
        }:
            await self.show_hub(chat_id, user)
            return True

        if t == __("discovery.btn_help"):
            await self.show_category(chat_id, user, "discovery", panel="discovery")
            return True
        if t == __("promo.btn_help"):
            await self.show_category(chat_id, user, "promo", panel="promo")
            return True
        if t == __("forward.btn_help"):
            await self.show_category(chat_id, user, "forward", panel="forward")
            return True

        # Help keyboard labels must never fall through to feature menus.
        if is_help_button(t):
            await self.tg.send_message(
                chat_id,
                __("help.stale_keyboard"),
                reply_markup=main_keyboard(),
            )
            await UserState.clear(self.db, tid)
            return True

        return False

    async def _handle_active(
        self,
        chat_id: int,
        user: User,
        text: str,
        current: str,
        ctx: dict,
    ) -> None:
        if current == ST_HELP_HUB:
            await self._handle_hub(chat_id, user, text)
            return
        if current == ST_HELP_CATEGORY:
            await self._handle_category(chat_id, user, text, ctx)
            return
        await UserState.clear(self.db, int(user.get("telegram_id")))
        await self.show_hub(chat_id, user)

    async def _handle_hub(self, chat_id: int, user: User, text: str) -> None:
        tid = int(user.get("telegram_id"))
        svc = self._svc()

        if text in {back_main_button(), __("accounts.btn_back"), "⬅️ منوی اصلی"}:
            await UserState.clear(self.db, tid)
            await self.tg.send_message(
                chat_id,
                __("auth.welcome_admin", name=user.display_name),
                reply_markup=main_keyboard(),
            )
            return

        category = await svc.match_category(text)
        if not category:
            categories = await svc.categories_with_counts()
            buttons = [
                svc.category_button(str(c.get("category") or ""), c)
                for c in categories
            ]
            await self.tg.send_message(
                chat_id,
                __("help.unknown"),
                reply_markup=help_categories_keyboard(buttons),
            )
            return
        await self.show_category(chat_id, user, category, panel="help")

    async def _handle_category(
        self, chat_id: int, user: User, text: str, ctx: dict
    ) -> None:
        tid = int(user.get("telegram_id"))
        category = str(ctx.get("category") or "")
        panel = str(ctx.get("panel") or "help")
        svc = self._svc()

        if text in {
            back_hub_button(),
            back_panel_button(),
        }:
            if panel == "help":
                await self.show_hub(chat_id, user)
                return
            await UserState.clear(self.db, tid)
            meta = CATEGORY_META.get(category, {})
            label = meta.get("title", category)
            await self.tg.send_message(
                chat_id,
                __("help.back_to_panel", panel=label),
                reply_markup=self._kb(panel),
            )
            return

        guide = await svc.match_guide(category, text)
        if guide:
            await self.show_guide(
                chat_id,
                user,
                category,
                str(guide.get("key") or ""),
                panel=panel,
            )
            return

        await self.tg.send_message(
            chat_id,
            __("help.unknown"),
            reply_markup=help_topics_keyboard(
                [svc.topic_button(g) for g in await svc.guides_for_category(category)],
                back_label=(
                    back_hub_button()
                    if panel == "help"
                    else back_panel_button()
                ),
            ),
        )
