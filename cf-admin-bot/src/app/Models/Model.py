"""Minimal Laravel-like query builder over Cloudflare D1."""
from __future__ import annotations

from typing import Any


def row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if hasattr(row, "to_py"):
        row = row.to_py()
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        return None


class QueryBuilder:
    def __init__(self, db, model_cls: type) -> None:
        self.db = db
        self.model_cls = model_cls
        self._wheres: list[tuple[str, Any]] = []
        self._order: str | None = None
        self._limit: int | None = None

    def where(self, column: str, value: Any) -> "QueryBuilder":
        self._wheres.append((column, value))
        return self

    def order_by(self, column: str, direction: str = "ASC") -> "QueryBuilder":
        direction = "DESC" if str(direction).upper() == "DESC" else "ASC"
        self._order = f"{column} {direction}"
        return self

    def limit(self, n: int) -> "QueryBuilder":
        self._limit = max(1, int(n))
        return self

    def _compose_select(self) -> tuple[str, list[Any]]:
        table = self.model_cls.table
        sql = f"SELECT * FROM {table}"
        params: list[Any] = []
        if self._wheres:
            clauses = []
            for col, val in self._wheres:
                clauses.append(f"{col} = ?")
                params.append(val)
            sql += " WHERE " + " AND ".join(clauses)
        if self._order:
            sql += f" ORDER BY {self._order}"
        if self._limit is not None:
            sql += " LIMIT ?"
            params.append(self._limit)
        return sql, params

    async def first(self) -> Any | None:
        self._limit = 1
        sql, params = self._compose_select()
        stmt = self.db.prepare(sql)
        if params:
            stmt = stmt.bind(*params)
        row = await stmt.first()
        data = row_to_dict(row)
        if not data:
            return None
        return self.model_cls.from_row(data)

    async def get(self) -> list[Any]:
        sql, params = self._compose_select()
        stmt = self.db.prepare(sql)
        if params:
            stmt = stmt.bind(*params)
        result = await stmt.all()
        rows = getattr(result, "results", None)
        if hasattr(rows, "to_py"):
            rows = rows.to_py()
        if not isinstance(rows, list):
            return []
        out = []
        for row in rows:
            data = row_to_dict(row)
            if data:
                out.append(self.model_cls.from_row(data))
        return out

    async def update(self, values: dict[str, Any]) -> None:
        if not self._wheres:
            raise ValueError("Refusing UPDATE without WHERE")
        table = self.model_cls.table
        sets = ", ".join(f"{k} = ?" for k in values.keys())
        params: list[Any] = list(values.values())
        clauses = []
        for col, val in self._wheres:
            clauses.append(f"{col} = ?")
            params.append(val)
        sql = f"UPDATE {table} SET {sets} WHERE " + " AND ".join(clauses)
        await self.db.prepare(sql).bind(*params).run()

    async def insert(self, values: dict[str, Any]) -> None:
        table = self.model_cls.table
        cols = ", ".join(values.keys())
        placeholders = ", ".join("?" for _ in values)
        sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
        await self.db.prepare(sql).bind(*values.values()).run()


class Model:
    table: str = ""
    primary_key: str = "id"
    fillable: tuple[str, ...] = ()

    def __init__(self, **attrs: Any) -> None:
        self._attrs = dict(attrs)

    def __getattr__(self, item: str) -> Any:
        if item.startswith("_"):
            raise AttributeError(item)
        return self._attrs.get(item)

    def get(self, key: str, default: Any = None) -> Any:
        return self._attrs.get(key, default)

    def to_dict(self) -> dict[str, Any]:
        return dict(self._attrs)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Model":
        return cls(**row)

    @classmethod
    def query(cls, db) -> QueryBuilder:
        return QueryBuilder(db, cls)

    @classmethod
    async def find(cls, db, id_value: Any) -> "Model | None":
        return await cls.query(db).where(cls.primary_key, id_value).first()
