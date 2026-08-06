"""Disk-backed queue for scheduled channel publishes."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import ROOT
from app.storage import load_json, save_json

_lock = threading.Lock()


class PublishQueue:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (ROOT / "data" / "publish_queue.json")
        self._data: dict[str, Any] = load_json(self.path, {"items": []})

    def _save(self) -> None:
        save_json(self.path, self._data)

    def add(
        self,
        *,
        route_key: str,
        source_id: int,
        dest_id: int,
        message_ids: list[int],
        mode: str,
        filter_cfg: dict[str, Any],
    ) -> str:
        item_id = uuid.uuid4().hex[:12]
        with _lock:
            self._data = load_json(self.path, {"items": []})
            items = self._data.setdefault("items", [])
            # de-dupe same source+ids still pending
            for existing in items:
                if (
                    existing.get("status") == "pending"
                    and existing.get("source_id") == source_id
                    and existing.get("message_ids") == message_ids
                ):
                    return str(existing.get("id"))
            items.append(
                {
                    "id": item_id,
                    "status": "pending",
                    "route_key": route_key,
                    "source_id": source_id,
                    "dest_id": dest_id,
                    "message_ids": list(message_ids),
                    "mode": mode,
                    "filter": filter_cfg,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            self._save()
        return item_id

    def list_pending(self) -> list[dict[str, Any]]:
        with _lock:
            self._data = load_json(self.path, {"items": []})
            return [i for i in self._data.get("items", []) if i.get("status") == "pending"]

    def mark_done(self, item_id: str) -> None:
        with _lock:
            self._data = load_json(self.path, {"items": []})
            for item in self._data.get("items", []):
                if item.get("id") == item_id:
                    item["status"] = "done"
                    item["done_at"] = datetime.now(timezone.utc).isoformat()
                    break
            # prune old done items (keep last 200)
            items = self._data.get("items", [])
            done = [i for i in items if i.get("status") == "done"]
            pending = [i for i in items if i.get("status") == "pending"]
            self._data["items"] = pending + done[-200:]
            self._save()

    def mark_failed(self, item_id: str, error: str) -> None:
        with _lock:
            self._data = load_json(self.path, {"items": []})
            for item in self._data.get("items", []):
                if item.get("id") == item_id:
                    item["status"] = "failed"
                    item["error"] = error[:300]
                    item["failed_at"] = datetime.now(timezone.utc).isoformat()
                    break
            self._save()

    def pending_count(self) -> int:
        return len(self.list_pending())
