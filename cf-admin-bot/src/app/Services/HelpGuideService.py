"""Load and format help guides from D1."""
from __future__ import annotations

from typing import Any

from app.Models.HelpGuide import HelpGuide
from app.Support.HelpButtons import (
    CATEGORY_LANG_KEYS,
    category_button,
    topic_button,
)
from app.Support.HelpGuideSeed import CATEGORY_META, DEFAULT_GUIDES
from app.Support.Lang import __
from app.Support.Time import utc_now_iso


class HelpGuideService:
    def __init__(self, db) -> None:
        self.db = db

    async def ensure_seeded(self) -> None:
        rows = await HelpGuide.query(self.db).limit(1).get()
        if rows:
            return
        now = utc_now_iso()
        for item in DEFAULT_GUIDES:
            await HelpGuide.upsert(
                self.db,
                item["category"],
                item["key"],
                item["title"],
                item["content"],
                emoji=item.get("emoji", "📄"),
                order_index=int(item.get("order_index", 0)),
                created_at=now,
                updated_at=now,
            )

    async def guides_for_category(self, category: str) -> list[HelpGuide]:
        await self.ensure_seeded()
        return await HelpGuide.by_category(self.db, category)

    async def get_guide(self, category: str, key: str) -> HelpGuide | None:
        await self.ensure_seeded()
        return await HelpGuide.find_by_key(self.db, category, key)

    async def categories_with_counts(self) -> list[dict[str, Any]]:
        await self.ensure_seeded()
        rows = await HelpGuide.categories(self.db)
        out: list[dict[str, Any]] = []
        for row in rows:
            cat = str(row.get("category") or "")
            meta = CATEGORY_META.get(cat, {})
            out.append(
                {
                    "category": cat,
                    "count": row.get("count", 0),
                    "emoji": meta.get("emoji", "📄"),
                    "title": meta.get("title", cat),
                }
            )
        order = ["general", "discovery", "promo", "forward"]
        out.sort(
            key=lambda r: (
                order.index(r["category"])
                if r["category"] in order
                else 99,
                r["category"],
            )
        )
        return out

    category_button = staticmethod(category_button)
    topic_button = staticmethod(topic_button)

    @staticmethod
    def format_guide(guide: HelpGuide) -> str:
        emoji = guide.get("emoji") or "📄"
        title = guide.get("title") or ""
        content = guide.get("content") or ""
        return f"{emoji} <b>{title}</b>\n────────────\n{content}"

    def format_category_index(
        self, category: str, guides: list[HelpGuide]
    ) -> str:
        meta = CATEGORY_META.get(category, {})
        emoji = meta.get("emoji", "📄")
        title = meta.get("title", category)
        lines = [
            f"{emoji} <b>راهنمای {title}</b>",
            "────────────",
            __("help.topic_pick"),
        ]
        for i, guide in enumerate(guides, start=1):
            lines.append(f"{i}. {self.topic_button(guide)}")
        return "\n".join(lines)

    def format_hub(self, categories: list[dict[str, Any]]) -> str:
        lines = [
            __("help.hub_header"),
            "────────────",
            __("help.hub_pick"),
        ]
        for i, row in enumerate(categories, start=1):
            cat = str(row.get("category") or "")
            lines.append(f"{i}. {self.category_button(cat, row)}")
        return "\n".join(lines)

    async def fallback_content(self, category: str) -> str:
        key = f"{category}.help_full"
        text = __(key)
        if text != key:
            return text
        return __("help.empty")

    async def match_guide(
        self, category: str, text: str
    ) -> HelpGuide | None:
        guides = await self.guides_for_category(category)
        t = (text or "").strip()
        for guide in guides:
            if t == self.topic_button(guide):
                return guide
        return None

    async def match_category(self, text: str) -> str | None:
        t = (text or "").strip()
        for cat in CATEGORY_LANG_KEYS:
            if t == category_button(cat):
                return cat
        categories = await self.categories_with_counts()
        for row in categories:
            cat = str(row.get("category") or "")
            if t == category_button(cat, row):
                return cat
        return None
