"""D1-backed job queue helpers for linkdir search (via admin-bot bridge)."""
from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger("linkdir_finders.job_queue")

SEARCH_JOB_TYPE = "search"
SNOWBALL_JOB_TYPE = "snowball"


def query_key(query: str) -> str:
    return hashlib.sha1(query.strip().encode("utf-8")).hexdigest()[:16]


def bridge_ready() -> bool:
    try:
        from app.linkdir_bridge import is_available

        return bool(is_available())
    except Exception:
        return False


def claim_search_jobs(
    owner: str,
    *,
    limit: int = 5,
    lease_seconds: int = 900,
    query_set: str | None = None,
) -> list[dict[str, Any]]:
    if not owner.strip():
        return []
    try:
        from app.linkdir_bridge import claim_jobs

        jobs = claim_jobs(
            owner=owner.strip(),
            limit=max(1, min(20, int(limit))),
            lease_seconds=max(60, int(lease_seconds)),
            job_type=SEARCH_JOB_TYPE,
            query_set=(query_set or "").strip() or None,
        )
        return jobs or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("claim_search_jobs failed: %s", exc)
        return []


def complete_job(
    job_id: int,
    *,
    status: str = "done",
    error: str | None = None,
    result_count: int | None = None,
) -> None:
    try:
        from app.linkdir_bridge import complete_job as bridge_complete

        payload: dict[str, Any] = {"id": int(job_id), "status": status}
        if error:
            payload["error"] = error[:500]
        if result_count is not None:
            payload["result_count"] = int(result_count)
        bridge_complete(payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("complete_job id=%s failed: %s", job_id, exc)


def enqueue_search_job(
    query: str,
    *,
    priority: int = 100,
    redo_after_days: int = 14,
    source: str = "seed",
    query_set: str | None = None,
    collector_role: str | None = None,
) -> dict[str, Any] | None:
    query = (query or "").strip()
    if not query:
        return None
    shard = (query_set or "").strip().lower() or None
    try:
        from app.linkdir_bridge import enqueue_job

        payload: dict[str, Any] = {
            "query": query,
            "query_key": query_key(query),
            "source": source,
        }
        if shard:
            payload["query_set"] = shard
            payload["collector_role"] = collector_role or f"search_{shard}"
        elif collector_role:
            payload["collector_role"] = collector_role
        return enqueue_job(
            {
                "job_type": SEARCH_JOB_TYPE,
                "priority": int(priority),
                "redo_after_days": int(redo_after_days),
                "payload": payload,
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("enqueue_search_job %r failed: %s", query[:40], exc)
        return None


def enqueue_snowball_job(
    ref: str,
    *,
    priority: int = 120,
    parent_query: str | None = None,
) -> dict[str, Any] | None:
    ref = (ref or "").strip()
    if not ref:
        return None
    try:
        from app.linkdir_bridge import enqueue_job

        return enqueue_job(
            {
                "job_type": SNOWBALL_JOB_TYPE,
                "priority": int(priority),
                "payload": {
                    "ref": ref,
                    "parent_query": parent_query,
                },
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("enqueue_snowball_job %r failed: %s", ref, exc)
        return None


def expand_seed_queries(
    base_queries: list[str],
    *,
    niches: list[str] | None = None,
    suffixes: list[str] | None = None,
) -> list[str]:
    """Build a deduped query list: base + niche×suffix templates."""
    niches = niches or ["گپ", "کانال", "گروه"]
    suffixes = suffixes or ["لینک", "لینکدونی", "تبادل لینک", "عضویت"]
    seen: set[str] = set()
    out: list[str] = []

    def add(q: str) -> None:
        q = " ".join(q.split())
        if not q or q in seen:
            return
        seen.add(q)
        out.append(q)

    for q in base_queries:
        add(q)
    for niche in niches:
        for suffix in suffixes:
            add(f"{niche} {suffix}")
    return out


def queries_for_set(cfg: dict[str, Any], query_set: str | None) -> list[str]:
    """Return config queries for fa/en/niche, else the mixed default list."""
    shard = (query_set or "").strip().lower()
    if shard in {"fa", "en", "niche"}:
        rows = list(cfg.get(f"queries_{shard}") or [])
        if rows:
            return [str(q).strip() for q in rows if str(q).strip()]
    return [str(q).strip() for q in (cfg.get("queries") or []) if str(q).strip()]
