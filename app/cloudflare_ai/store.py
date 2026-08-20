"""Persistent store for Cloudflare AI accounts and config.

Storage: JSON file at ``data/pool/cloudflare_ai.json`` (same pattern as
``GroupPool`` / ``data/pool/group_pool.json``). This repo does not use
Cloudflare D1; pool data lives under ``data/pool/`` and is gitignored.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from app.paths import ensure_pool_dir, pool_path
from app.storage import load_json, save_json

SCHEMA_VERSION = 1
STORE_FILENAME = "cloudflare_ai.json"
DAILY_NEURON_LIMIT = 10_000


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _utc_midnight_today() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def mask_token(token: str) -> str:
    text = (token or "").strip()
    if len(text) <= 8:
        return "***"
    return f"{text[:4]}…{text[-4:]}"


def default_store() -> dict[str, Any]:
    from app.cloudflare_ai.models import DEFAULT_MODEL

    return {
        "schema_version": SCHEMA_VERSION,
        "config": {
            "default_model": DEFAULT_MODEL,
            "max_tokens": 4096,
            "temperature": 0.7,
        },
        "accounts": [],
    }


class CloudflareAIStore:
    """Thread-safe shared store under data/pool/cloudflare_ai.json."""

    def __init__(self, path=None) -> None:
        ensure_pool_dir()
        self.path = path or pool_path(STORE_FILENAME)
        self._lock = threading.Lock()
        self._data = load_json(self.path, default_store())
        self._migrate()

    def _migrate(self) -> None:
        if not isinstance(self._data, dict):
            self._data = default_store()
        self._data.setdefault("schema_version", SCHEMA_VERSION)
        self._data.setdefault("config", {})
        self._data.setdefault("accounts", [])
        if not isinstance(self._data["config"], dict):
            self._data["config"] = {}
        if not isinstance(self._data["accounts"], list):
            self._data["accounts"] = []

    def reload(self) -> None:
        with self._lock:
            self._data = load_json(self.path, default_store())
            self._migrate()

    def _save(self) -> None:
        save_json(self.path, self._data)

    def config(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data.get("config") or {})

    def default_model(self) -> str:
        from app.cloudflare_ai.models import DEFAULT_MODEL, resolve_model_id

        cfg = self.config()
        return resolve_model_id(str(cfg.get("default_model") or DEFAULT_MODEL))

    def set_default_model(self, model: str) -> str:
        from app.cloudflare_ai.models import resolve_model_id

        resolved = resolve_model_id(model)
        with self._lock:
            cfg = self._data.setdefault("config", {})
            cfg["default_model"] = resolved
            self._save()
        return resolved

    def list_accounts(self, *, include_inactive: bool = True) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._data.get("accounts") or [])
        cleaned: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not include_inactive and not row.get("is_active", True):
                continue
            cleaned.append(dict(row))
        cleaned.sort(key=lambda item: (int(item.get("priority", 0)), str(item.get("name") or "")))
        return cleaned

    def get_account(self, name: str) -> dict[str, Any] | None:
        key = (name or "").strip().lower()
        for row in self.list_accounts():
            if str(row.get("name") or "").lower() == key:
                return row
        return None

    def add_account(
        self,
        *,
        name: str,
        account_id: str,
        api_token: str,
        priority: int | None = None,
        is_active: bool = True,
    ) -> dict[str, Any]:
        label = (name or "").strip()
        acc_id = (account_id or "").strip()
        token = (api_token or "").strip()
        if not label:
            raise ValueError("account name is required")
        if len(acc_id) != 32 or not all(c in "0123456789abcdef" for c in acc_id.lower()):
            raise ValueError("account_id must be a 32-char hex Cloudflare account id")
        if not token:
            raise ValueError("api_token is required")
        if self.get_account(label):
            raise ValueError(f"account already exists: {label}")

        now = utc_now()
        with self._lock:
            accounts = self._data.setdefault("accounts", [])
            if priority is None:
                priority = len(accounts)
            row = {
                "id": uuid.uuid4().hex[:12],
                "name": label,
                "account_id": acc_id,
                "api_token": token,
                "is_active": bool(is_active),
                "priority": int(priority),
                "usage_count": 0,
                "neurons_used_today": 0.0,
                "last_used_at": None,
                "last_error": None,
                "quota_exhausted_at": None,
                "created_at": now,
            }
            accounts.append(row)
            self._save()
            return dict(row)

    def upsert_accounts(self, rows: list[dict[str, Any]]) -> int:
        """Import accounts from seed data. Skips duplicates by name."""
        added = 0
        for row in rows:
            try:
                self.add_account(
                    name=str(row.get("name") or ""),
                    account_id=str(row.get("account_id") or ""),
                    api_token=str(row.get("api_token") or row.get("api_key") or ""),
                    priority=row.get("priority"),
                    is_active=bool(row.get("is_active", True)),
                )
                added += 1
            except ValueError as exc:
                if "already exists" in str(exc):
                    continue
                raise
        return added

    def remove_account(self, name: str) -> bool:
        key = (name or "").strip().lower()
        with self._lock:
            accounts = self._data.setdefault("accounts", [])
            before = len(accounts)
            self._data["accounts"] = [
                row
                for row in accounts
                if isinstance(row, dict) and str(row.get("name") or "").lower() != key
            ]
            removed = before != len(self._data["accounts"])
            if removed:
                self._save()
            return removed

    def set_active(self, name: str, active: bool) -> bool:
        key = (name or "").strip().lower()
        with self._lock:
            changed = False
            for row in self._data.get("accounts") or []:
                if not isinstance(row, dict):
                    continue
                if str(row.get("name") or "").lower() != key:
                    continue
                row["is_active"] = bool(active)
                if active:
                    row["quota_exhausted_at"] = None
                    row["last_error"] = None
                changed = True
                break
            if changed:
                self._save()
            return changed

    def set_priority(self, name: str, priority: int) -> bool:
        key = (name or "").strip().lower()
        with self._lock:
            changed = False
            for row in self._data.get("accounts") or []:
                if not isinstance(row, dict):
                    continue
                if str(row.get("name") or "").lower() != key:
                    continue
                row["priority"] = int(priority)
                changed = True
                break
            if changed:
                self._save()
            return changed

    def account_available(self, row: dict[str, Any]) -> bool:
        if not row.get("is_active", True):
            return False
        exhausted_at = _parse_iso(str(row.get("quota_exhausted_at") or "") or None)
        if exhausted_at and exhausted_at >= _utc_midnight_today():
            return False
        return True

    def usable_accounts(self) -> list[dict[str, Any]]:
        return [row for row in self.list_accounts() if self.account_available(row)]

    def mark_used(
        self,
        name: str,
        *,
        neurons: float = 0.0,
        error: str | None = None,
        exhausted: bool = False,
    ) -> None:
        key = (name or "").strip().lower()
        now = utc_now()
        with self._lock:
            for row in self._data.get("accounts") or []:
                if not isinstance(row, dict):
                    continue
                if str(row.get("name") or "").lower() != key:
                    continue
                if error:
                    row["last_error"] = error[:500]
                else:
                    row["last_error"] = None
                if exhausted:
                    row["quota_exhausted_at"] = now
                else:
                    row["usage_count"] = int(row.get("usage_count") or 0) + 1
                    row["last_used_at"] = now
                    if neurons:
                        row["neurons_used_today"] = float(row.get("neurons_used_today") or 0) + float(
                            neurons
                        )
                break
            self._save()

    def status_summary(self) -> dict[str, Any]:
        accounts = self.list_accounts()
        usable = [row for row in accounts if self.account_available(row)]
        return {
            "path": str(self.path),
            "default_model": self.default_model(),
            "total_accounts": len(accounts),
            "active_accounts": len([row for row in accounts if row.get("is_active", True)]),
            "usable_accounts": len(usable),
            "accounts": [
                {
                    "name": row.get("name"),
                    "account_id": row.get("account_id"),
                    "api_token": mask_token(str(row.get("api_token") or "")),
                    "is_active": row.get("is_active", True),
                    "priority": row.get("priority", 0),
                    "usage_count": row.get("usage_count", 0),
                    "neurons_used_today": row.get("neurons_used_today", 0),
                    "last_used_at": row.get("last_used_at"),
                    "last_error": row.get("last_error"),
                    "quota_exhausted_at": row.get("quota_exhausted_at"),
                    "available": self.account_available(row),
                }
                for row in accounts
            ],
        }
