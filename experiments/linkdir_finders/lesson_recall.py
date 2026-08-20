"""Context-aware lesson recall for the linkdir query agent.

Lessons are experience, not commandments. A human does not apply every past
note to every new task: some advice is for Persian niches, some for English,
some fades when stronger evidence arrives, and a single admin tip must not
crowd out everything the agent has measured for itself.

This module ranks active lessons for the *current* ``query_set`` and returns a
diversified subset for the prompt / ``recall_lessons`` tool.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

SCOPES = ("all", "fa", "en", "niche")
ORIGINS = ("reflection", "admin_teach")

DEFAULT_DO_LIMIT = 4
DEFAULT_AVOID_LIMIT = 3
MAX_ADMIN_TEACH_IN_PROMPT = 1
RECENCY_HALF_LIFE_DAYS = 21.0

# Heuristic cues that bind a lesson to one or more shards.
_CITY_RE = re.compile(
    r"(شهر|ایران|تهران|مشهد|اصفهان|شیراز|تبریز|کرج|اهواز|قم|کرمان|رشت|"
    r"همدان|یزد|ارومیه|کرمانشاه|زاهدان|اردبیل|بندر|استان)",
    re.IGNORECASE,
)
_EN_RE = re.compile(
    r"\b(english|lowercase|latin|ascii|channel|promo|exchange links?)\b",
    re.IGNORECASE,
)
_FA_RE = re.compile(r"(فارسی|پارسی|لینکدونی|تبادل لینک|کانال)")
_NICHE_RE = re.compile(r"(نیش|niche|موضوعی|تخصصی|شهرستان)")


@dataclass(frozen=True)
class RankedLesson:
    kind: str
    lesson: str
    score: float
    scope: str
    origin: str
    support: int
    confidence: float
    lesson_key: str = ""
    evidence_count: int = 0


def normalize_scope(value: Any) -> str:
    """Return a canonical scope token; unknown values fall back to ``all``."""
    raw = str(value or "all").strip().lower().replace(" ", "")
    if not raw:
        return "all"
    # Allow "fa,niche" — keep as-is for matching; primary token is first.
    parts = [part for part in raw.split(",") if part]
    if not parts:
        return "all"
    if "all" in parts:
        return "all"
    cleaned = []
    for part in parts:
        cleaned.append(part if part in SCOPES else "all")
    # Deduplicate while preserving order.
    out: list[str] = []
    for part in cleaned:
        if part not in out:
            out.append(part)
    if len(out) == 1:
        return out[0]
    return ",".join(out)


def scope_matches(scope: str, query_set: str) -> bool:
    """True when a lesson may be shown for this shard."""
    shard = (query_set or "fa").strip().lower() or "fa"
    normalized = normalize_scope(scope)
    if normalized == "all":
        return True
    allowed = {part for part in normalized.split(",") if part}
    return shard in allowed or "all" in allowed


def infer_scope(lesson: str, *, explicit: Any = None) -> str:
    """Prefer an explicit scope; otherwise guess from the lesson text."""
    if explicit is not None and str(explicit).strip():
        return normalize_scope(explicit)
    text = str(lesson or "")
    hits: list[str] = []
    if _CITY_RE.search(text) or _NICHE_RE.search(text):
        hits.extend(["fa", "niche"])
    if _FA_RE.search(text) and "fa" not in hits:
        hits.append("fa")
    if _EN_RE.search(text):
        hits.append("en")
    if not hits:
        return "all"
    # City/niche advice must not leak into English generation.
    if "en" in hits and ("fa" in hits or "niche" in hits):
        hits = [h for h in hits if h != "en"]
    return normalize_scope(",".join(hits))


def infer_origin(row: dict[str, Any]) -> str:
    raw = str(row.get("origin") or "").strip().lower()
    if raw in ORIGINS:
        return raw
    evidence = row.get("evidence") or []
    # Admin teaching writes empty evidence + high confidence.
    try:
        confidence = float(row.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if (not evidence) and confidence >= 0.7:
        return "admin_teach"
    return "reflection"


def _parse_time(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def lesson_relevance_score(row: dict[str, Any], query_set: str) -> float:
    """Higher is better. Out-of-scope lessons score 0 and should be dropped."""
    scope = infer_scope(str(row.get("lesson") or ""), explicit=row.get("scope"))
    if not scope_matches(scope, query_set):
        return 0.0

    try:
        confidence = max(0.0, min(1.0, float(row.get("confidence") or 0.5)))
    except (TypeError, ValueError):
        confidence = 0.5
    support = max(0, int(row.get("support") or 0))
    evidence = row.get("evidence") or []
    evidence_n = len(evidence) if isinstance(evidence, list) else 0
    origin = infer_origin(row)

    # Evidence-backed reflection is the backbone; admin tips are useful but
    # must not permanently outrank measured experience.
    base = confidence * (0.55 + 0.45 * (math.log1p(support) / math.log1p(12)))
    if evidence_n:
        base *= 1.0 + min(0.35, 0.08 * evidence_n)
    if origin == "admin_teach":
        base *= 0.85

    updated = _parse_time(row.get("updated_at") or row.get("created_at"))
    if updated is not None:
        age_days = max(
            0.0,
            (datetime.now(timezone.utc) - updated).total_seconds() / 86400.0,
        )
        # Soft recency: halves over ~3 weeks so stale tips fade unless reinforced.
        base *= 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)

    # Exact shard match beats a broad "all" lesson when both exist.
    normalized = normalize_scope(scope)
    shard = (query_set or "fa").strip().lower() or "fa"
    if normalized == shard:
        base *= 1.12
    elif normalized == "all":
        base *= 0.95

    return round(base, 6)


def rank_lessons(
    rows: Iterable[Any],
    query_set: str,
    *,
    do_limit: int = DEFAULT_DO_LIMIT,
    avoid_limit: int = DEFAULT_AVOID_LIMIT,
    max_admin_teach: int = MAX_ADMIN_TEACH_IN_PROMPT,
) -> list[RankedLesson]:
    """Pick a diversified, in-scope subset for one generation call."""
    ranked: list[RankedLesson] = []
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("lesson") or "").strip()
        if not text:
            continue
        kind = str(raw.get("kind") or "do").strip().lower()
        if kind not in {"do", "avoid"}:
            continue
        score = lesson_relevance_score(raw, query_set)
        if score <= 0:
            continue
        evidence = raw.get("evidence") or []
        ranked.append(
            RankedLesson(
                kind=kind,
                lesson=text,
                score=score,
                scope=infer_scope(text, explicit=raw.get("scope")),
                origin=infer_origin(raw),
                support=max(0, int(raw.get("support") or 0)),
                confidence=float(raw.get("confidence") or 0.0),
                lesson_key=str(raw.get("lesson_key") or ""),
                evidence_count=len(evidence) if isinstance(evidence, list) else 0,
            )
        )

    ranked.sort(key=lambda row: (-row.score, -row.support, row.lesson))

    selected: list[RankedLesson] = []
    do_n = avoid_n = admin_n = 0
    for row in ranked:
        if row.kind == "do" and do_n >= max(0, int(do_limit)):
            continue
        if row.kind == "avoid" and avoid_n >= max(0, int(avoid_limit)):
            continue
        if row.origin == "admin_teach" and admin_n >= max(0, int(max_admin_teach)):
            # Still allow admin tips when we have no reflection lessons yet.
            has_reflection = any(item.origin == "reflection" for item in ranked)
            if has_reflection:
                continue
        selected.append(row)
        if row.kind == "do":
            do_n += 1
        else:
            avoid_n += 1
        if row.origin == "admin_teach":
            admin_n += 1
    return selected


def format_lessons_for_prompt(
    lessons: list[RankedLesson], *, query_set: str
) -> str:
    """Render ranked lessons as soft, contextual guidance."""
    if not lessons:
        return ""
    do_rows = [row for row in lessons if row.kind == "do"]
    avoid_rows = [row for row in lessons if row.kind == "avoid"]
    parts = [
        f"Experience hints for query_set='{query_set}'. These are ranked "
        "suggestions from earlier runs and optional admin notes — NOT hard "
        "rules. Apply what fits THIS shard; skip anything that does not fit. "
        "Do not force every hint into every query. Prefer evidence-backed "
        "patterns when they conflict with a single tip.",
    ]
    if do_rows:
        parts.append("DO (when relevant):")
        for row in do_rows:
            parts.append(
                f"- [{row.scope}|{row.origin}|c={row.confidence:.2f}|s={row.support}] "
                f"{row.lesson}"
            )
    if avoid_rows:
        parts.append("AVOID (when relevant):")
        for row in avoid_rows:
            parts.append(
                f"- [{row.scope}|{row.origin}|c={row.confidence:.2f}|s={row.support}] "
                f"{row.lesson}"
            )
    parts.append("Call recall_lessons if you need more of the bank.")
    return "\n".join(parts)
