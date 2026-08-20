"""Contrastive reflection: distill scored episodes into reusable lessons.

Consolidation is the step that turns a log of what happened into experience
the agent can act on. Two properties keep it honest:

* **Contrastive** — the model sees the best *and* the worst episodes in one
  prompt, so it can name what to repeat and what to avoid instead of
  rationalising whatever it happens to be shown.
* **Grounded** — every lesson must cite the ids of episodes it was derived
  from, and any lesson citing an id we did not supply is dropped. Ungrounded
  reflection is how an agent talks itself into a confident falsehood and then
  keeps reinforcing it.

Raw episodes are never rewritten; consumed ones are only flagged
``consolidated`` so the next pass works on fresh evidence.

:func:`reflect` never raises — inspect ``ReflectionResult.ok``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from experiments.linkdir_finders.ai_queries import MEMORY_AGENT
from experiments.linkdir_finders.query_validator import (
    lesson_key,
    normalize_lesson,
    validate_lesson,
)

logger = logging.getLogger("linkdir_finders.reflection")

MIN_SCORED_EPISODES = 8
DEFAULT_BEST = 6
DEFAULT_WORST = 6
MAX_LESSONS = 8
DEFAULT_CONFIDENCE = 0.5
_SUBJECT_CHARS = 60

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lessons": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["do", "avoid"]},
                    "lesson": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "integer"}},
                    "confidence": {"type": "number"},
                },
                "required": ["kind", "lesson", "evidence"],
            },
        }
    },
    "required": ["lessons"],
}

SYSTEM_PROMPT = """You are the reflection module of an agent that writes \
Telegram search queries to find Persian "لینکدونی" (link-directory) channels.

You are shown past queries with their measured reward: how many results were \
kept, sent to review, or judged junk. Compare the best and the worst and write \
short, concrete lessons the query writer can apply next time.

Hard rules for every lesson:
- Write in Persian only. Use ONLY Persian/Arabic script, basic English letters \
and digits, and ordinary sentence punctuation.
- NEVER use Chinese, Japanese, Korean, Cyrillic, Devanagari, emoji or any other script.
- One actionable sentence, 3 to 40 words. No lists, no numbering, no preamble.
- "kind" is "do" for a pattern worth repeating, "avoid" for one to stop using.
- "evidence" MUST list episode ids taken from the episodes shown to you. Never \
invent an id, and never write a lesson you cannot point at evidence for.
- "confidence" is between 0 and 1.
- Say something specific about wording, niche, length or phrasing — not \
generic advice like "write better queries"."""


@dataclass
class ReflectionResult:
    """Outcome of one reflection pass. ``ok=False`` means nothing was learned."""

    ok: bool
    reason: str = "ok"
    lessons: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)
    episode_ids: list[int] = field(default_factory=list)
    created: int = 0
    reinforced: int = 0
    consolidated: int = 0
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "episodes": len(self.episode_ids),
            "lessons": len(self.lessons),
            "rejected": len(self.rejected),
            "created": self.created,
            "reinforced": self.reinforced,
            "consolidated": self.consolidated,
            **self.diagnostics,
        }


def _episode_id(row: dict[str, Any]) -> int | None:
    try:
        value = int(row.get("id"))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _is_pending(row: dict[str, Any]) -> bool:
    """A missing ``consolidated`` field is treated as not-yet-consolidated."""
    try:
        return int(row.get("consolidated") or 0) == 0
    except (TypeError, ValueError):
        return True


def select_episodes(
    memory: Any, *, best: int = DEFAULT_BEST, worst: int = DEFAULT_WORST
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch the best and worst scored, not-yet-consolidated episodes."""
    top = memory.episodes(scored=True, order="best", limit=best, consolidated=False)
    bottom = memory.episodes(scored=True, order="worst", limit=worst, consolidated=False)

    seen: set[int] = set()
    kept_top: list[dict[str, Any]] = []
    kept_bottom: list[dict[str, Any]] = []
    for rows, bucket in ((top, kept_top), (bottom, kept_bottom)):
        for row in rows or []:
            episode_id = _episode_id(row)
            if episode_id is None or episode_id in seen or not _is_pending(row):
                continue
            seen.add(episode_id)
            bucket.append(row)
    return kept_top, kept_bottom


def _episode_line(row: dict[str, Any]) -> str:
    subject = str(row.get("subject") or "")[:_SUBJECT_CHARS]
    try:
        reward = float(row.get("reward") or 0.0)
    except (TypeError, ValueError):
        reward = 0.0
    return (
        f"#{_episode_id(row)} reward={reward:.2f} "
        f"keep={int(row.get('keep_count') or 0)} "
        f"review={int(row.get('review_count') or 0)} "
        f"junk={int(row.get('junk_count') or 0)} "
        f"set={row.get('query_set') or '-'} :: {subject}"
    )


def build_prompt(best: list[dict[str, Any]], worst: list[dict[str, Any]]) -> str:
    lines = [
        "Best-performing queries so far (highest reward):",
        *(_episode_line(row) for row in best),
        "",
        "Worst-performing queries so far (lowest reward):",
        *(_episode_line(row) for row in worst),
        "",
        f"Write at most {MAX_LESSONS} lessons, in Persian, mixing 'do' and 'avoid'.",
        'Answer with JSON only: {"lessons": [{"kind": "...", "lesson": "...", '
        '"evidence": [12, 34], "confidence": 0.7}]}',
    ]
    return "\n".join(lines)


def parse_lessons(
    payload: Any, allowed_ids: set[int]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Validate model output against the allowlist and the supplied evidence."""
    rows = payload.get("lessons") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return [], [{"lesson": str(payload)[:60], "reason": "not_a_list"}]

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    seen_keys: set[str] = set()

    for raw in rows:
        if not isinstance(raw, dict):
            rejected.append({"lesson": str(raw)[:60], "reason": "not_an_object"})
            continue

        text = normalize_lesson(raw.get("lesson"))
        preview = text[:60] or str(raw)[:60]

        if len(accepted) >= MAX_LESSONS:
            rejected.append({"lesson": preview, "reason": "over_limit"})
            continue

        kind = str(raw.get("kind") or "").strip().lower()
        if kind not in {"do", "avoid"}:
            rejected.append({"lesson": preview, "reason": "bad_kind"})
            continue

        reason = validate_lesson(text)
        if reason:
            rejected.append({"lesson": preview, "reason": reason})
            continue

        evidence: list[int] = []
        ungrounded = False
        for item in raw.get("evidence") or []:
            try:
                episode_id = int(item)
            except (TypeError, ValueError):
                ungrounded = True
                break
            if episode_id not in allowed_ids:
                ungrounded = True
                break
            if episode_id not in evidence:
                evidence.append(episode_id)
        if ungrounded:
            rejected.append({"lesson": preview, "reason": "ungrounded_evidence"})
            continue
        if not evidence:
            rejected.append({"lesson": preview, "reason": "no_evidence"})
            continue

        key = lesson_key(text)
        if key in seen_keys:
            rejected.append({"lesson": preview, "reason": "duplicate"})
            continue
        seen_keys.add(key)

        try:
            confidence = float(raw.get("confidence", DEFAULT_CONFIDENCE))
        except (TypeError, ValueError):
            confidence = DEFAULT_CONFIDENCE

        accepted.append(
            {
                "kind": kind,
                "lesson": text,
                "lesson_key": key,
                "evidence": evidence,
                "confidence": max(0.0, min(1.0, confidence)),
            }
        )

    return accepted, rejected


def _build_provider(cfg: dict[str, Any] | None, model: str | None) -> Any:
    from app.cloudflare_ai.hydrate import ensure_store
    from app.cloudflare_ai.provider import CloudflareAIProvider

    settings = (cfg or {}).get("ai_queries") or {}
    store = ensure_store()
    if not store.usable_accounts():
        return None
    return CloudflareAIProvider(store, model=model or settings.get("model") or None)


def reflect(
    *,
    memory: Any = None,
    provider: Any = None,
    cfg: dict[str, Any] | None = None,
    best: int = DEFAULT_BEST,
    worst: int = DEFAULT_WORST,
    min_episodes: int = MIN_SCORED_EPISODES,
    model: str | None = None,
    dry_run: bool = False,
) -> ReflectionResult:
    """Run one contrastive reflection pass. Never raises — check ``ok``."""
    try:
        if memory is None:
            from app.agent_memory import AgentMemory

            memory = AgentMemory(MEMORY_AGENT)
        if not memory.available():
            return ReflectionResult(ok=False, reason="memory_unavailable")

        top, bottom = select_episodes(memory, best=best, worst=worst)
        episodes = top + bottom
        if len(episodes) < max(1, int(min_episodes)):
            return ReflectionResult(
                ok=False,
                reason="insufficient_evidence",
                diagnostics={
                    "available": len(episodes),
                    "required": int(min_episodes),
                },
            )

        allowed_ids = {
            episode_id
            for episode_id in (_episode_id(row) for row in episodes)
            if episode_id is not None
        }

        if provider is None:
            provider = _build_provider(cfg, model)
            if provider is None:
                return ReflectionResult(
                    ok=False,
                    reason="no_accounts",
                    diagnostics={"available": len(episodes)},
                )
    except Exception as exc:  # noqa: BLE001 - reflection is strictly additive
        logger.warning("reflection setup failed: %s", exc)
        return ReflectionResult(
            ok=False, reason="setup_failed", diagnostics={"error": str(exc)[:200]}
        )

    from app.cloudflare_ai.agent import Agent

    agent = Agent(
        provider,
        system_prompt=SYSTEM_PROMPT,
        max_tool_rounds=0,
        response_schema=RESPONSE_SCHEMA,
        temperature=0.3,
    )
    run = agent.run(build_prompt(top, bottom))
    diagnostics: dict[str, Any] = run.diagnostics()
    diagnostics["best"] = len(top)
    diagnostics["worst"] = len(bottom)

    if not run.ok:
        return ReflectionResult(
            ok=False,
            reason=run.reason,
            episode_ids=sorted(allowed_ids),
            diagnostics=diagnostics,
        )

    payload = run.data
    if payload is None:
        from app.cloudflare_ai.agent import parse_json_object

        payload = parse_json_object(run.content)

    accepted, rejected = parse_lessons(payload, allowed_ids)
    if not accepted:
        return ReflectionResult(
            ok=False,
            reason="no_valid_lessons",
            rejected=rejected,
            episode_ids=sorted(allowed_ids),
            diagnostics=diagnostics,
        )

    if dry_run:
        return ReflectionResult(
            ok=True,
            reason="dry_run",
            lessons=accepted,
            rejected=rejected,
            episode_ids=sorted(allowed_ids),
            diagnostics=diagnostics,
        )

    try:
        written = memory.add_lessons(accepted)
        created = int(written.get("created") or 0)
        reinforced = int(written.get("reinforced") or 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("lesson write failed: %s", exc)
        return ReflectionResult(
            ok=False,
            reason="lesson_write_failed",
            lessons=accepted,
            rejected=rejected,
            episode_ids=sorted(allowed_ids),
            diagnostics={**diagnostics, "error": str(exc)[:200]},
        )

    # Only burn the evidence once something was actually learned from it.
    consolidated = 0
    if created or reinforced:
        try:
            consolidated = int(memory.mark_consolidated(sorted(allowed_ids)) or 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("mark_consolidated failed: %s", exc)

    return ReflectionResult(
        ok=True,
        reason="ok",
        lessons=accepted,
        rejected=rejected,
        episode_ids=sorted(allowed_ids),
        created=created,
        reinforced=reinforced,
        consolidated=consolidated,
        diagnostics=diagnostics,
    )
