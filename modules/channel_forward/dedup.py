"""Duplicate detection for forwarded content."""
from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from telethon.tl.types import Message

from app.paths import data_path
from app.storage import load_json, save_json

from modules.channel_forward.media_filter import detect_media_type

_lock = threading.Lock()


def content_fingerprint(message: Message) -> str:
    text = (message.message or "").strip().casefold()
    media = detect_media_type(message)
    grouped = getattr(message, "grouped_id", None) or 0
    raw = f"{media}|{grouped}|{text[:500]}"
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:32]


class DedupStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_path("dedup.json")
        self._data: dict[str, Any] = load_json(self.path, {"entries": []})

    def _save(self) -> None:
        save_json(self.path, self._data)

    def _prune(self, window_hours: int) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, window_hours))
        entries = self._data.get("entries") or []
        kept: list[dict[str, Any]] = []
        for item in entries:
            try:
                ts = datetime.fromisoformat(str(item.get("at")))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
            if ts >= cutoff:
                kept.append(item)
        self._data["entries"] = kept[-2000:]

    def is_duplicate(self, route_key: str, fingerprint: str, window_hours: int) -> bool:
        with _lock:
            self._data = load_json(self.path, {"entries": []})
            self._prune(window_hours)
            for item in self._data.get("entries") or []:
                if item.get("route_key") == route_key and item.get("fp") == fingerprint:
                    return True
            return False

    def remember(self, route_key: str, fingerprint: str) -> None:
        with _lock:
            self._data = load_json(self.path, {"entries": []})
            entries = self._data.setdefault("entries", [])
            entries.append(
                {
                    "route_key": route_key,
                    "fp": fingerprint,
                    "at": datetime.now(timezone.utc).isoformat(),
                }
            )
            self._data["entries"] = entries[-2000:]
            self._save()
