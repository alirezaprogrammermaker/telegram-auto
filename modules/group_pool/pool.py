"""Shared group discovery pool (collector → inspector → approve → promo)."""
from __future__ import annotations

import hashlib
import re
import threading
from datetime import datetime, timezone
from typing import Any

from app.paths import ensure_pool_dir, pool_path
from app.storage import load_json, save_json

STATUSES = ("raw", "inspected_ok", "rejected", "approved")

_LINK_RE = re.compile(
    r"(?i)\b(?:https?://)?(?:t\.me|telegram\.me)/(?:joinchat/|\+)?([A-Za-z0-9_/+-]+)(?:\?[^\s]*)?"
)
_AT_RE = re.compile(r"(?<!\w)@([A-Za-z][A-Za-z0-9_]{3,})", re.UNICODE)

KNOWN_ANTISPAM = (
    "combot",
    "rose",
    "missrose",
    "shieldy",
    "grouphelp",
    "grouphelpbot",
    "sibyl",
    "spamobot",
    "safebot",
    "anti_spam",
    "antispambot",
    "captchabot",
    "gatekeeper",
    "watcher_bot",
    "controllercatbot",
    "heimdall",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_group_ref(raw: str) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    text = text.split()[0].strip("<>()[].,;\"'")
    if text.startswith("@"):
        return "@" + text[1:]
    lower = text.lower()
    if "t.me/" in lower or "telegram.me/" in lower:
        if text.startswith("http://"):
            text = "https://" + text[len("http://") :]
        if not text.startswith("https://"):
            text = "https://" + text.lstrip("/")
        text = text.split("?")[0].rstrip("/")
        return text
    if text.startswith("+") and len(text) > 4:
        return f"https://t.me/{text}"
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,}", text):
        return f"@{text}"
    return None


def link_key(ref: str) -> str:
    norm = normalize_group_ref(ref) or ref.strip()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def extract_links_from_text(
    text: str, *, exclude_usernames: set[str] | None = None
) -> list[str]:
    exclude = {u.lower().lstrip("@") for u in (exclude_usernames or set())}
    found: list[str] = []
    seen: set[str] = set()

    for match in _LINK_RE.finditer(text or ""):
        path = match.group(1).strip("/")
        full = match.group(0)
        if path.lower().startswith("c/"):
            continue
        # t.me/username/123 → username
        if (
            "/" in path
            and not path.lower().startswith("joinchat/")
            and "/+" not in full.lower()
        ):
            parts = path.split("/")
            if parts[0].lower() != "joinchat" and not path.startswith("+"):
                if parts[0].lower() in exclude:
                    continue
                if len(parts) >= 2 and parts[1].isdigit():
                    path = parts[0]
                    full = f"https://t.me/{path}"
        ref = normalize_group_ref(
            full if "t.me" in full.lower() or "telegram.me" in full.lower() else f"https://t.me/{path}"
        )
        if not ref:
            continue
        key = link_key(ref)
        if key in seen:
            continue
        if ref.startswith("@") and ref[1:].lower() in exclude:
            continue
        seen.add(key)
        found.append(ref)

    for match in _AT_RE.finditer(text or ""):
        name = match.group(1)
        if name.lower() in exclude:
            continue
        ref = f"@{name}"
        key = link_key(ref)
        if key in seen:
            continue
        seen.add(key)
        found.append(ref)

    return found


def looks_like_antispam(username: str | None, title: str | None = None) -> bool:
    blob = f"{username or ''} {title or ''}".lower()
    return any(tok in blob for tok in KNOWN_ANTISPAM)


class GroupPool:
    """Thread-safe shared pool under data/pool/group_pool.json."""

    def __init__(self, path=None) -> None:
        ensure_pool_dir()
        self.path = path or pool_path("group_pool.json")
        self._lock = threading.Lock()
        self._data = load_json(self.path, {"items": {}, "version": 1})
        if not isinstance(self._data.get("items"), dict):
            self._data["items"] = {}

    def _save(self) -> None:
        save_json(self.path, self._data)

    def items(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return dict(self._data.get("items") or {})

    def get(self, ref: str) -> dict[str, Any] | None:
        key = link_key(ref)
        with self._lock:
            item = (self._data.get("items") or {}).get(key)
            return dict(item) if isinstance(item, dict) else None

    def upsert_raw(
        self,
        ref: str,
        *,
        source_channel: str,
        message_id: int | None = None,
        collector_account: str = "",
        extra: dict[str, Any] | None = None,
    ) -> tuple[str, bool]:
        norm = normalize_group_ref(ref)
        if not norm:
            raise ValueError(f"invalid ref: {ref!r}")
        key = link_key(norm)
        now = utc_now()
        with self._lock:
            items = self._data.setdefault("items", {})
            item = items.get(key)
            is_new = not isinstance(item, dict)
            if is_new:
                item = {
                    "key": key,
                    "ref": norm,
                    "status": "raw",
                    "sources": [],
                    "created_at": now,
                    "updated_at": now,
                }
            assert isinstance(item, dict)
            sources = item.setdefault("sources", [])
            if not isinstance(sources, list):
                sources = []
                item["sources"] = sources
            sources.append(
                {
                    "channel": source_channel,
                    "message_id": message_id,
                    "collected_at": now,
                    "account": collector_account,
                }
            )
            item["sources"] = sources[-20:]
            if item.get("status") not in {"approved", "rejected", "inspected_ok"}:
                item["status"] = "raw"
            item["updated_at"] = now
            if extra:
                item.update(extra)
            items[key] = item
            self._save()
            return str(item["status"]), is_new

    def set_status(
        self,
        ref: str,
        status: str,
        *,
        inspect: dict[str, Any] | None = None,
        title: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        norm = normalize_group_ref(ref) or ref
        key = link_key(norm)
        now = utc_now()
        with self._lock:
            items = self._data.setdefault("items", {})
            item = items.get(key)
            if not isinstance(item, dict):
                item = {
                    "key": key,
                    "ref": norm,
                    "status": status,
                    "sources": [],
                    "created_at": now,
                }
            item["ref"] = norm
            item["status"] = status
            item["updated_at"] = now
            if title:
                item["title"] = title
            if note:
                item["note"] = note
            if inspect is not None:
                item["inspect"] = inspect
            items[key] = item
            self._save()
            return dict(item)

    def list_by_status(
        self, status: str | None = None, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = list((self._data.get("items") or {}).values())
        rows = [r for r in rows if isinstance(r, dict)]
        if status:
            rows = [r for r in rows if r.get("status") == status]
        rows.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
        return rows[: max(1, limit)]

    def counts(self) -> dict[str, int]:
        with self._lock:
            items = list((self._data.get("items") or {}).values())
        out: dict[str, int] = {s: 0 for s in STATUSES}
        out["total"] = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            out["total"] += 1
            st = str(item.get("status") or "")
            if st in out:
                out[st] += 1
        return out

    def next_raw(self, *, exclude_keys: set[str] | None = None) -> dict[str, Any] | None:
        skip = exclude_keys or set()
        for item in self.list_by_status("raw", limit=500):
            if item.get("key") in skip:
                continue
            return item
        return None
