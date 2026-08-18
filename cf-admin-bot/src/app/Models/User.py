from __future__ import annotations

from app.Models.Model import Model
from app.Support.Time import utc_now_iso


class User(Model):
    table = "users"
    primary_key = "telegram_id"
    fillable = (
        "telegram_id",
        "chat_id",
        "username",
        "first_name",
        "last_name",
        "role",
        "created_at",
        "updated_at",
        "last_seen_at",
    )

    @property
    def is_admin(self) -> bool:
        return str(self.get("role") or "") == "admin"

    @property
    def display_name(self) -> str:
        return (
            self.get("first_name")
            or self.get("username")
            or str(self.get("telegram_id") or "")
        )

    @classmethod
    async def ensure_schema(cls, db) -> None:
        await db.prepare(
            """
            CREATE TABLE IF NOT EXISTS users (
              telegram_id INTEGER PRIMARY KEY,
              chat_id INTEGER NOT NULL,
              username TEXT,
              first_name TEXT,
              last_name TEXT,
              role TEXT NOT NULL DEFAULT 'user',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              last_seen_at TEXT
            )
            """
        ).run()
        await db.prepare(
            "CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)"
        ).run()

    @classmethod
    async def upsert_from_telegram(
        cls,
        db,
        *,
        telegram_id: int,
        chat_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> "User":
        now = utc_now_iso()
        existing = await cls.find(db, telegram_id)
        if existing:
            await cls.query(db).where("telegram_id", telegram_id).update(
                {
                    "chat_id": chat_id,
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                    "updated_at": now,
                    "last_seen_at": now,
                }
            )
            return (await cls.find(db, telegram_id)) or existing

        await cls.query(db).insert(
            {
                "telegram_id": telegram_id,
                "chat_id": chat_id,
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "role": "user",
                "created_at": now,
                "updated_at": now,
                "last_seen_at": now,
            }
        )
        return (await cls.find(db, telegram_id)) or cls(
            telegram_id=telegram_id,
            chat_id=chat_id,
            role="user",
        )

    async def promote_to_admin(self, db) -> "User":
        now = utc_now_iso()
        tid = int(self.get("telegram_id"))
        await self.query(db).where("telegram_id", tid).update(
            {"role": "admin", "updated_at": now, "last_seen_at": now}
        )
        return (await self.find(db, tid)) or self

    @classmethod
    async def admins(cls, db, *, limit: int = 50) -> list["User"]:
        return (
            await cls.query(db)
            .where("role", "admin")
            .order_by("updated_at", "DESC")
            .limit(limit)
            .get()
        )

    @classmethod
    async def role_counts(cls, db) -> dict[str, int]:
        result = await db.prepare(
            "SELECT role, COUNT(*) AS c FROM users GROUP BY role"
        ).all()
        rows = getattr(result, "results", None)
        if hasattr(rows, "to_py"):
            rows = rows.to_py()
        counts = {"user": 0, "admin": 0, "total": 0}
        if isinstance(rows, list):
            from app.Models.Model import row_to_dict

            for row in rows:
                item = row_to_dict(row)
                if not item:
                    continue
                role = str(item.get("role") or "")
                c = int(item.get("c") or 0)
                if role in counts:
                    counts[role] = c
                counts["total"] += c
        return counts
