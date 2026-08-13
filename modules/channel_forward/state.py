"""Persistent forward state: last seen ids and source→dest message mappings."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.paths import data_path
from app.storage import load_json, save_json

_lock = threading.Lock()


class ForwardStateStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_path("forward_state.json")
        self._data: dict[str, Any] = load_json(
            self.path,
            {"last_seen": {}, "mappings": {}},
        )

    def _save(self) -> None:
        save_json(self.path, self._data)

    def get_last_seen(self, route_key: str) -> int | None:
        with _lock:
            self._data = load_json(self.path, {"last_seen": {}, "mappings": {}})
            raw = (self._data.get("last_seen") or {}).get(route_key)
            if raw is None:
                return None
            try:
                return int(raw)
            except (TypeError, ValueError):
                return None

    def set_last_seen(self, route_key: str, message_id: int) -> None:
        with _lock:
            self._data = load_json(self.path, {"last_seen": {}, "mappings": {}})
            last = self._data.setdefault("last_seen", {})
            prev = last.get(route_key)
            if prev is None or int(message_id) > int(prev):
                last[route_key] = int(message_id)
                self._save()

    def record_mapping(
        self,
        route_key: str,
        source_msg_id: int,
        dest_msg_id: int,
    ) -> None:
        with _lock:
            self._data = load_json(self.path, {"last_seen": {}, "mappings": {}})
            bucket = self._data.setdefault("mappings", {}).setdefault(route_key, {})
            bucket[str(int(source_msg_id))] = int(dest_msg_id)
            if len(bucket) > 500:
                keys = sorted(bucket.keys(), key=int)
                for old in keys[:-500]:
                    bucket.pop(old, None)
            self._save()

    def dest_for_source(self, route_key: str, source_msg_id: int) -> int | None:
        with _lock:
            self._data = load_json(self.path, {"last_seen": {}, "mappings": {}})
            bucket = (self._data.get("mappings") or {}).get(route_key) or {}
            raw = bucket.get(str(int(source_msg_id)))
            if raw is None:
                return None
            try:
                return int(raw)
            except (TypeError, ValueError):
                return None

    def remove_mapping(self, route_key: str, source_msg_id: int) -> None:
        with _lock:
            self._data = load_json(self.path, {"last_seen": {}, "mappings": {}})
            bucket = (self._data.get("mappings") or {}).get(route_key)
            if bucket:
                bucket.pop(str(int(source_msg_id)), None)
                self._save()
