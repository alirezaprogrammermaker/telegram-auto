"""D1 model for persistent help-guide content."""
from __future__ import annotations

from typing import Any

from app.Models.Model import Model


class HelpGuide(Model):
    """Stored help guides, keyed by (category, key)."""

    table = "help_guides"
    primary_key = "id"
    fillable = (
        "category",
        "key",
        "title",
        "content",
        "emoji",
        "order_index",
        "is_active",
        "created_at",
        "updated_at",
    )

    def to_view(self) -> dict[str, Any]:
        return {
            "id": self.get("id"),
            "category": self.get("category"),
            "key": self.get("key"),
            "title": self.get("title"),
            "content": self.get("content"),
            "emoji": self.get("emoji") or "📄",
            "order_index": int(self.get("order_index") or 0),
        }

    def to_api(self) -> dict[str, Any]:
        return self.to_view()

    @classmethod
    async def all_active(cls, db) -> list["HelpGuide"]:
        rows = (
            await cls.query(db)
            .where("is_active", 1)
            .order_by("order_index", "ASC")
            .get()
        )
        return [r for r in rows if r.get("is_active")]

    @classmethod
    async def by_category(cls, db, category: str) -> list["HelpGuide"]:
        rows = (
            await cls.query(db)
            .where("category", category)
            .where("is_active", 1)
            .order_by("order_index", "ASC")
            .get()
        )
        return [r for r in rows if r.get("is_active")]

    @classmethod
    async def find_by_key(cls, db, category: str, key: str) -> "HelpGuide | None":
        rows = (
            await cls.query(db)
            .where("category", category)
            .where("key", key)
            .where("is_active", 1)
            .limit(1)
            .get()
        )
        for r in rows:
            if r.get("key") == key:
                return r
        return None

    @classmethod
    async def categories(cls, db) -> list[dict[str, Any]]:
        """Return distinct categories with count of guides."""
        rows = await cls.all_active(db)
        cats: dict[str, dict[str, Any]] = {}
        for r in rows:
            cat = str(r.get("category") or "")
            if cat not in cats:
                cats[cat] = {"category": cat, "count": 0}
            cats[cat]["count"] += 1
        return list(cats.values())

    @classmethod
    async def upsert(
        cls, db, category: str, key: str, title: str, content: str, **extra: Any
    ) -> "HelpGuide":
        now = extra.get("created_at", "")
        existing = await cls.find_by_key(db, category, key)
        if existing:
            await cls.query(db).where("id", existing.get("id")).update(
                {
                    "title": title,
                    "content": content,
                    "updated_at": now,
                    **extra,
                }
            )
        else:
            await cls.query(db).insert(
                {
                    "category": category,
                    "key": key,
                    "title": title,
                    "content": content,
                    "emoji": extra.get("emoji", "📄"),
                    "order_index": int(extra.get("order_index", 0)),
                    "is_active": 1,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        return (await cls.find_by_key(db, category, key)) or cls(
            category=category, key=key, title=title, content=content
        )