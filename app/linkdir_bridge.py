"""Thin client for /internal/linkdir/* (D1 catalog bridge)."""
from __future__ import annotations

import logging
from typing import Any

from app.bridge_client import bridge_configured, bridge_request

logger = logging.getLogger(__name__)


def upsert_items(
    items: list[dict[str, Any]],
    *,
    collector_id: str | None = None,
    method: str = "local_catalog",
) -> dict[str, Any] | None:
    if not items:
        return {"ok": True, "upserted": 0, "errors": 0}
    return bridge_request(
        "POST",
        "/internal/linkdir/upsert",
        payload={
            "items": items,
            "collector_id": collector_id,
            "method": method,
        },
    )


def list_items(
    *,
    promo_ready: bool | None = None,
    verdict: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]] | None:
    query: dict[str, Any] = {"limit": limit}
    if promo_ready is not None:
        query["promo_ready"] = 1 if promo_ready else 0
    if verdict:
        query["verdict"] = verdict
    if status:
        query["status"] = status
    resp = bridge_request("GET", "/internal/linkdir/items", query=query)
    if not resp or not resp.get("ok"):
        return None
    items = resp.get("items")
    return items if isinstance(items, list) else []


def counts() -> dict[str, int] | None:
    resp = bridge_request("GET", "/internal/linkdir/counts")
    if not resp or not resp.get("ok"):
        return None
    raw = resp.get("counts")
    return raw if isinstance(raw, dict) else None


def mark_stale(*, older_than_hours: float = 72.0) -> dict[str, Any] | None:
    return bridge_request(
        "POST",
        "/internal/linkdir/mark-stale",
        payload={"older_than_hours": older_than_hours},
    )


def export_promo_ready(*, limit: int = 200) -> dict[str, Any] | None:
    return bridge_request(
        "GET",
        "/internal/linkdir/promo-export-url",
        query={"limit": limit},
    )


def collector_heartbeat(payload: dict[str, Any]) -> dict[str, Any] | None:
    return bridge_request(
        "POST",
        "/internal/linkdir/collectors/heartbeat",
        payload=payload,
    )


def claim_jobs(
    *,
    owner: str,
    limit: int = 5,
    lease_seconds: int = 900,
    job_type: str | None = None,
    query_set: str | None = None,
) -> list[dict[str, Any]] | None:
    resp = bridge_request(
        "POST",
        "/internal/linkdir/jobs/claim",
        payload={
            "owner": owner,
            "limit": limit,
            "lease_seconds": lease_seconds,
            "job_type": job_type,
            "query_set": query_set,
        },
    )
    if not resp or not resp.get("ok"):
        return None
    jobs = resp.get("jobs")
    return jobs if isinstance(jobs, list) else []


def complete_job(payload: dict[str, Any]) -> dict[str, Any] | None:
    return bridge_request("POST", "/internal/linkdir/jobs/complete", payload=payload)


def enqueue_job(payload: dict[str, Any]) -> dict[str, Any] | None:
    return bridge_request("POST", "/internal/linkdir/jobs/enqueue", payload=payload)


def record_run(payload: dict[str, Any]) -> dict[str, Any] | None:
    return bridge_request("POST", "/internal/linkdir/runs", payload=payload)


def is_available() -> bool:
    return bridge_configured()
