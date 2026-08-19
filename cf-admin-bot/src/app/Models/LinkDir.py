"""D1 models for link-directory discovery catalog."""
from __future__ import annotations

import json
from typing import Any

from app.Models.Model import Model


def _dumps(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _loads(raw: Any, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default


class LinkDirItem(Model):
    table = "linkdir_items"
    primary_key = "key"
    fillable = (
        "key",
        "ref",
        "username",
        "chat_id",
        "invite_hash",
        "title",
        "about",
        "kind",
        "is_channel",
        "is_group",
        "broadcast",
        "megagroup",
        "gigagroup",
        "members_can_send",
        "postable",
        "participants",
        "identity_score",
        "quality_score",
        "rank_score",
        "verdict",
        "status",
        "promo_ready",
        "seed_only",
        "reasons_json",
        "gates_json",
        "activity_json",
        "methods_json",
        "queries_json",
        "parent_seed",
        "last_method",
        "seen_count",
        "first_seen_at",
        "last_seen_at",
        "last_ranked_at",
        "stale_at",
        "created_at",
        "updated_at",
    )

    def to_api(self) -> dict[str, Any]:
        d = self.to_dict()
        members = d.get("members_can_send")
        postable = d.get("postable")
        return {
            "key": d.get("key"),
            "ref": d.get("ref"),
            "username": d.get("username"),
            "chat_id": d.get("chat_id"),
            "invite_hash": d.get("invite_hash"),
            "title": d.get("title"),
            "about": d.get("about"),
            "kind": d.get("kind"),
            "is_channel": bool(int(d.get("is_channel") or 0)),
            "is_group": bool(int(d.get("is_group") or 0)),
            "broadcast": bool(int(d.get("broadcast") or 0)),
            "megagroup": bool(int(d.get("megagroup") or 0)),
            "gigagroup": bool(int(d.get("gigagroup") or 0)),
            "members_can_send": None if members is None else bool(int(members)),
            "postable": None if postable is None else bool(int(postable)),
            "participants": d.get("participants"),
            "identity_score": d.get("identity_score"),
            "quality_score": d.get("quality_score"),
            "rank_score": d.get("rank_score"),
            "verdict": d.get("verdict"),
            "status": d.get("status"),
            "promo_ready": bool(int(d.get("promo_ready") or 0)),
            "seed_only": bool(int(d.get("seed_only") or 0)),
            "reasons": _loads(d.get("reasons_json"), []),
            "gates": _loads(d.get("gates_json"), []),
            "activity": _loads(d.get("activity_json"), None),
            "methods": _loads(d.get("methods_json"), []),
            "queries": _loads(d.get("queries_json"), []),
            "parent_seed": d.get("parent_seed"),
            "last_method": d.get("last_method"),
            "seen_count": int(d.get("seen_count") or 0),
            "first_seen_at": d.get("first_seen_at"),
            "last_seen_at": d.get("last_seen_at"),
            "last_ranked_at": d.get("last_ranked_at"),
            "stale_at": d.get("stale_at"),
            "created_at": d.get("created_at"),
            "updated_at": d.get("updated_at"),
        }


class LinkDirEvent(Model):
    table = "linkdir_events"
    primary_key = "id"
    fillable = (
        "item_key",
        "event_type",
        "collector_id",
        "method",
        "payload_json",
        "created_at",
    )


class LinkDirCollector(Model):
    table = "linkdir_collectors"
    primary_key = "id"
    fillable = (
        "id",
        "session_name",
        "label",
        "enabled",
        "status",
        "circuit_until",
        "circuit_reason",
        "budgets_json",
        "last_run_at",
        "meta_json",
        "created_at",
        "updated_at",
    )

    def to_api(self) -> dict[str, Any]:
        d = self.to_dict()
        return {
            "id": d.get("id"),
            "session_name": d.get("session_name"),
            "label": d.get("label"),
            "enabled": bool(int(d.get("enabled") or 0)),
            "status": d.get("status"),
            "circuit_until": d.get("circuit_until"),
            "circuit_reason": d.get("circuit_reason"),
            "budgets": _loads(d.get("budgets_json"), {}),
            "last_run_at": d.get("last_run_at"),
            "meta": _loads(d.get("meta_json"), {}),
            "created_at": d.get("created_at"),
            "updated_at": d.get("updated_at"),
        }


class LinkDirJob(Model):
    table = "linkdir_jobs"
    primary_key = "id"
    fillable = (
        "job_type",
        "payload_json",
        "priority",
        "status",
        "lease_owner",
        "lease_until",
        "attempts",
        "last_error",
        "created_at",
        "updated_at",
        "done_at",
    )

    def to_api(self) -> dict[str, Any]:
        d = self.to_dict()
        return {
            "id": d.get("id"),
            "job_type": d.get("job_type"),
            "payload": _loads(d.get("payload_json"), {}),
            "priority": int(d.get("priority") or 100),
            "status": d.get("status"),
            "lease_owner": d.get("lease_owner"),
            "lease_until": d.get("lease_until"),
            "attempts": int(d.get("attempts") or 0),
            "last_error": d.get("last_error"),
            "created_at": d.get("created_at"),
            "updated_at": d.get("updated_at"),
            "done_at": d.get("done_at"),
        }


class LinkDirRun(Model):
    table = "linkdir_runs"
    primary_key = "id"
    fillable = (
        "collector_id",
        "steps_json",
        "ok",
        "summary_json",
        "started_at",
        "finished_at",
    )


# Re-export helpers for the service
dumps_json = _dumps
loads_json = _loads
