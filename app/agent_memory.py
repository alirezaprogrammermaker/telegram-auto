"""Client for the agent experience-memory bridge (``/internal/agentmem/*``).

Implements the runner side of a storage -> reflection -> experience loop:
episodes are appended when an agent acts, scored once the real-world outcome
is known, distilled into lessons by a reflection pass, and recalled before the
next run.

The client is deliberately agent-agnostic — it only knows about an ``agent``
name, opaque subjects and lesson rows — so future agents can reuse it.

Every method is fail-soft. When the bridge is unconfigured, unreachable or
answers with an error, callers get an empty/zero result instead of an
exception, so an unattended CI run degrades to its pre-memory behaviour.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Iterable

from app.bridge_client import bridge_configured, bridge_request

logger = logging.getLogger(__name__)

EPISODES_PATH = "/internal/agentmem/episodes"
SCORE_PATH = "/internal/agentmem/score"
LESSONS_PATH = "/internal/agentmem/lessons"
CONSOLIDATED_PATH = "/internal/agentmem/consolidated"
STATS_PATH = "/internal/agentmem/stats"

BATCH_SIZE = 50
MAX_FETCH = 500
EPISODE_ORDERS = ("best", "worst", "recent")
LESSON_KINDS = ("do", "avoid")


def subject_key(subject: str) -> str:
    """Stable id for an episode subject.

    Mirrors ``experiments.linkdir_finders.job_queue.query_key`` so an episode
    and the search job it describes share one key. Callers that already have a
    domain-specific key function should pass its output explicitly.
    """
    return hashlib.sha1(str(subject or "").strip().encode("utf-8")).hexdigest()[:16]


def lesson_fallback_key(lesson: str) -> str:
    """Last-resort key when a caller supplies no domain-normalized one."""
    return hashlib.sha1(str(lesson or "").strip().lower().encode("utf-8")).hexdigest()[:16]


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _chunks(rows: list[Any], size: int) -> Iterable[list[Any]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


class AgentMemory:
    """Fail-soft accessor for one named agent's episodic and semantic memory."""

    def __init__(self, agent: str, *, timeout: float = 20.0) -> None:
        self.agent = (str(agent or "").strip()) or "default"
        self.timeout = float(timeout)

    def available(self) -> bool:
        return bridge_configured()

    def _call(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not bridge_configured():
            return None
        try:
            resp = bridge_request(
                method, path, payload=payload, query=query, timeout=self.timeout
            )
        except Exception as exc:  # noqa: BLE001 - memory is strictly additive
            logger.warning("agent memory %s %s crashed: %s", method, path, exc)
            return None
        if not isinstance(resp, dict):
            return None
        if not resp.get("ok"):
            logger.warning("agent memory %s %s rejected: %s", method, path, str(resp)[:200])
            return None
        return resp

    def record_episodes(self, episodes: Iterable[dict[str, Any]]) -> dict[str, int]:
        """Append episodes. Returns ``{"inserted": n, "skipped": n}``."""
        rows: list[dict[str, Any]] = []
        for raw in episodes or []:
            row = self._episode_payload(raw)
            if row is not None:
                rows.append(row)

        totals = {"inserted": 0, "skipped": 0}
        for chunk in _chunks(rows, BATCH_SIZE):
            resp = self._call(
                "POST", EPISODES_PATH, payload={"agent": self.agent, "episodes": chunk}
            )
            if resp is None:
                continue
            totals["inserted"] += _as_int(resp.get("inserted"))
            totals["skipped"] += _as_int(resp.get("skipped"))
        return totals

    @staticmethod
    def _episode_payload(raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        subject = str(raw.get("subject") or "").strip()
        if not subject:
            return None
        row: dict[str, Any] = {
            "subject": subject,
            "subject_key": str(raw.get("subject_key") or "").strip()
            or subject_key(subject),
        }
        for field in ("kind", "query_set", "source"):
            value = raw.get(field)
            if value is not None and str(value).strip():
                row[field] = str(value).strip()
        meta = raw.get("meta")
        if isinstance(meta, dict) and meta:
            row["meta"] = meta
        return row

    def score_episodes(self, outcomes: Iterable[dict[str, Any]]) -> int:
        """Attach measured outcomes to episodes. Returns rows updated."""
        rows: list[dict[str, Any]] = []
        for raw in outcomes or []:
            if not isinstance(raw, dict):
                continue
            key = str(raw.get("subject_key") or "").strip()
            if not key:
                continue
            rows.append(
                {
                    "subject_key": key,
                    "results_total": _as_int(raw.get("results_total")),
                    "keep_count": _as_int(raw.get("keep_count")),
                    "review_count": _as_int(raw.get("review_count")),
                    "junk_count": _as_int(raw.get("junk_count")),
                    "reward": float(raw.get("reward") or 0.0),
                }
            )

        updated = 0
        for chunk in _chunks(rows, BATCH_SIZE):
            resp = self._call(
                "POST", SCORE_PATH, payload={"agent": self.agent, "outcomes": chunk}
            )
            if resp is not None:
                updated += _as_int(resp.get("updated"))
        return updated

    def episodes(
        self,
        *,
        scored: bool | None = None,
        limit: int = 50,
        order: str = "recent",
        consolidated: bool | None = None,
    ) -> list[dict[str, Any]]:
        """Read episodes. Returns ``[]`` when memory is unavailable."""
        query: dict[str, Any] = {
            "agent": self.agent,
            "limit": max(1, min(MAX_FETCH, _as_int(limit, 50))),
        }
        if scored is not None:
            query["scored"] = 1 if scored else 0
        if consolidated is not None:
            query["consolidated"] = 1 if consolidated else 0
        if order in EPISODE_ORDERS:
            query["order"] = order

        resp = self._call("GET", EPISODES_PATH, query=query)
        rows = (resp or {}).get("episodes")
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)]

    def add_lessons(self, lessons: Iterable[dict[str, Any]]) -> dict[str, int]:
        """Upsert distilled lessons. Returns ``{"created", "reinforced"}``."""
        rows: list[dict[str, Any]] = []
        for raw in lessons or []:
            row = self._lesson_payload(raw)
            if row is not None:
                rows.append(row)

        totals = {"created": 0, "reinforced": 0}
        for chunk in _chunks(rows, BATCH_SIZE):
            resp = self._call(
                "POST", LESSONS_PATH, payload={"agent": self.agent, "lessons": chunk}
            )
            if resp is None:
                continue
            totals["created"] += _as_int(resp.get("created"))
            totals["reinforced"] += _as_int(resp.get("reinforced"))
        return totals

    @staticmethod
    def _lesson_payload(raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        text = str(raw.get("lesson") or "").strip()
        kind = str(raw.get("kind") or "do").strip().lower()
        if not text or kind not in LESSON_KINDS:
            return None
        evidence = [
            _as_int(item)
            for item in (raw.get("evidence") or [])
            if _as_int(item, -1) >= 0
        ]
        confidence = raw.get("confidence")
        row: dict[str, Any] = {
            "kind": kind,
            "lesson": text,
            "lesson_key": str(raw.get("lesson_key") or "").strip()
            or lesson_fallback_key(text),
            "evidence": evidence,
        }
        if confidence is not None:
            try:
                row["confidence"] = max(0.0, min(1.0, float(confidence)))
            except (TypeError, ValueError):
                pass
        return row

    def lessons(
        self, *, limit: int = 20, kind: str | None = None
    ) -> list[dict[str, Any]]:
        """Read active lessons, strongest first. Returns ``[]`` on failure."""
        query: dict[str, Any] = {
            "agent": self.agent,
            "limit": max(1, min(MAX_FETCH, _as_int(limit, 20))),
        }
        if kind in LESSON_KINDS:
            query["kind"] = kind

        resp = self._call("GET", LESSONS_PATH, query=query)
        rows = (resp or {}).get("lessons")
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)]

    def mark_consolidated(self, episode_ids: Iterable[Any]) -> int:
        """Flag episodes as already reflected on. Returns rows updated."""
        ids = sorted({_as_int(item, -1) for item in episode_ids or []} - {-1})
        if not ids:
            return 0
        updated = 0
        for chunk in _chunks(ids, BATCH_SIZE):
            resp = self._call(
                "POST",
                CONSOLIDATED_PATH,
                payload={"agent": self.agent, "episode_ids": chunk},
            )
            if resp is not None:
                updated += _as_int(resp.get("updated"))
        return updated

    def stats(self) -> dict[str, Any]:
        """Aggregate counters for dashboards. Returns ``{}`` on failure."""
        resp = self._call("GET", STATS_PATH, query={"agent": self.agent})
        if resp is None:
            return {}
        out = {key: value for key, value in resp.items() if key != "ok"}
        inner = out.get("stats")
        return inner if isinstance(inner, dict) else out
