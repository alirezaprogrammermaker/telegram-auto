"""Disk-backed promo delivery queue (one job = one group share)."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.paths import data_path
from app.storage import load_json, save_json

_lock = threading.Lock()


class PromoQueue:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_path("promo_queue.json")
        self._data: dict[str, Any] = load_json(self.path, {"items": []})

    def _save(self) -> None:
        save_json(self.path, self._data)

    def enqueue(
        self,
        *,
        source_id: int,
        group_ref: str,
        group_id: int,
        message_ids: list[int],
        mode: str,
        post_key: str,
    ) -> str | None:
        item_id = uuid.uuid4().hex[:12]
        with _lock:
            self._data = load_json(self.path, {"items": []})
            items = self._data.setdefault("items", [])
            for existing in items:
                if (
                    existing.get("status") == "pending"
                    and existing.get("group_id") == group_id
                    and existing.get("post_key") == post_key
                ):
                    return str(existing.get("id"))
            items.append(
                {
                    "id": item_id,
                    "status": "pending",
                    "source_id": int(source_id),
                    "group_ref": group_ref,
                    "group_id": int(group_id),
                    "message_ids": list(message_ids),
                    "mode": mode,
                    "post_key": post_key,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "attempts": 0,
                }
            )
            # Cap queue growth
            pending = [i for i in items if i.get("status") == "pending"]
            done = [i for i in items if i.get("status") != "pending"]
            if len(pending) > 400:
                pending = pending[-400:]
            self._data["items"] = pending + done[-150:]
            self._save()
        return item_id

    def list_pending(self) -> list[dict[str, Any]]:
        with _lock:
            self._data = load_json(self.path, {"items": []})
            return [i for i in self._data.get("items", []) if i.get("status") == "pending"]

    def pending_count(self) -> int:
        return len(self.list_pending())

    def pop_next(self) -> dict[str, Any] | None:
        """Peek oldest pending (does not mutate status)."""
        pending = self.list_pending()
        if not pending:
            return None
        pending.sort(key=lambda i: str(i.get("created_at") or ""))
        return pending[0]

    def mark_done(self, item_id: str) -> None:
        with _lock:
            self._data = load_json(self.path, {"items": []})
            for item in self._data.get("items", []):
                if item.get("id") == item_id:
                    item["status"] = "done"
                    item["done_at"] = datetime.now(timezone.utc).isoformat()
                    break
            self._save()

    def mark_failed(self, item_id: str, error: str, *, retry: bool = False) -> None:
        with _lock:
            self._data = load_json(self.path, {"items": []})
            for item in self._data.get("items", []):
                if item.get("id") == item_id:
                    item["attempts"] = int(item.get("attempts") or 0) + 1
                    item["last_error"] = error[:300]
                    if retry and int(item["attempts"]) < 3:
                        item["status"] = "pending"
                    else:
                        item["status"] = "failed"
                        item["failed_at"] = datetime.now(timezone.utc).isoformat()
                    break
            self._save()

    def defer(self, item_id: str, reason: str) -> None:
        """Keep pending but bump created_at so other jobs can go first."""
        with _lock:
            self._data = load_json(self.path, {"items": []})
            for item in self._data.get("items", []):
                if item.get("id") == item_id:
                    item["deferred_reason"] = reason[:200]
                    item["created_at"] = datetime.now(timezone.utc).isoformat()
                    break
            self._save()

    def clear_pending(self) -> int:
        with _lock:
            self._data = load_json(self.path, {"items": []})
            items = self._data.get("items") or []
            n = sum(1 for i in items if i.get("status") == "pending")
            self._data["items"] = [i for i in items if i.get("status") != "pending"]
            self._save()
        return n

    def try_claim_post_ack(self, post_key: str) -> bool:
        """Return True once when a post has no pending jobs left (first claim wins)."""
        key = str(post_key or "").strip()
        if not key:
            return False
        with _lock:
            self._data = load_json(self.path, {"items": []})
            items = list(self._data.get("items") or [])
            related = [i for i in items if str(i.get("post_key") or "") == key]
            if not related:
                return False
            if any(str(i.get("status") or "") == "pending" for i in related):
                return False
            acked = self._data.setdefault("acked_posts", {})
            if not isinstance(acked, dict):
                acked = {}
                self._data["acked_posts"] = acked
            if key in acked:
                return False
            acked[key] = datetime.now(timezone.utc).isoformat()
            # Bound growth of ack map
            if len(acked) > 300:
                keep = sorted(acked.items(), key=lambda kv: str(kv[1]))[-200:]
                self._data["acked_posts"] = dict(keep)
            self._save()
            return True
