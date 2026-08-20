"""AI-generated Telegram search queries for the linkdir finder pipeline.

Wraps the reusable Cloudflare AI agent runtime with catalog feedback tools and
the strict query validator. The public entrypoint :func:`generate_queries`
never raises: when accounts are exhausted, the bridge is down or the model
returns junk, it comes back with ``ok=False`` and an empty query list so the
caller can fall through to the static config queries.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from experiments.linkdir_finders.query_validator import dedupe_key, filter_queries

logger = logging.getLogger("linkdir_finders.ai_queries")

TOOL_ITEM_CAP = 15
_CATALOG_SCAN_LIMIT = 200
_TITLE_CHARS = 60

QUERY_SET_HINTS = {
    "fa": "Persian (Farsi) search terms only. No English words.",
    "en": "English search terms only, lowercase, no Persian script.",
    "niche": (
        "Persian search terms that combine the link-directory idea with a niche "
        "(city, topic, marketplace, hobby) to reach smaller uncrowded directories."
    ),
}

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "queries": {
            "type": "array",
            "items": {"type": "string"},
        }
    },
    "required": ["queries"],
}

SYSTEM_PROMPT = """You generate Telegram search queries that find "لینکدونی" \
(link-directory) channels and groups: places where users post invite links, \
exchange links, and advertise channels.

Hard rules for every query you output:
- Use ONLY Persian/Arabic script or basic English letters and digits.
- NEVER use Chinese, Japanese, Korean, Cyrillic, Devanagari, emoji or any other script.
- 1 to 5 words, 2 to 40 characters. Short search phrases, not sentences.
- No punctuation except spaces, and no explanations or numbering.
- Do not repeat queries that already exist.

Call the provided tools first to learn which query patterns produced good and \
bad results, then answer with the JSON object required by the schema."""


@dataclass
class QueryGenResult:
    """Outcome of one generation run. ``ok=False`` means: use static queries."""

    ok: bool
    queries: list[str] = field(default_factory=list)
    used_ai: bool = False
    reason: str = "disabled"
    rejected: list[dict[str, str]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "used": self.used_ai,
            "reason": self.reason,
            "accepted": len(self.queries),
            "rejected": len(self.rejected),
            **self.diagnostics,
        }


def ai_config(cfg: dict[str, Any] | None) -> dict[str, Any]:
    section = (cfg or {}).get("ai_queries")
    return dict(section) if isinstance(section, dict) else {}


def _row_queries(row: dict[str, Any]) -> list[str]:
    out: list[str] = []
    single = row.get("query")
    if isinstance(single, str) and single.strip():
        out.append(single.strip())
    many = row.get("queries")
    if isinstance(many, str):
        try:
            many = json.loads(many)
        except (json.JSONDecodeError, ValueError):
            many = []
    if isinstance(many, list):
        out.extend(str(q).strip() for q in many if str(q).strip())
    return out


def _verdict_counter(catalog: Any, verdict: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    try:
        rows = catalog.list_items(verdict=verdict, limit=_CATALOG_SCAN_LIMIT) or []
    except Exception as exc:  # noqa: BLE001 - catalog access is advisory only
        logger.warning("catalog list_items(%s) failed: %s", verdict, exc)
        return counter
    for row in rows:
        if not isinstance(row, dict):
            continue
        for query in _row_queries(row):
            counter[query] += 1
    return counter


def _sample_titles(catalog: Any, verdict: str, limit: int) -> list[str]:
    try:
        rows = catalog.list_items(verdict=verdict, limit=limit) or []
    except Exception:  # noqa: BLE001
        return []
    titles: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        if title:
            titles.append(title[:_TITLE_CHARS])
        if len(titles) >= limit:
            break
    return titles


@dataclass
class _Feedback:
    top: list[dict[str, Any]]
    weak: list[dict[str, Any]]
    existing: list[str]
    known_keys: set[str]
    titles: list[str]


def collect_feedback(
    catalog: Any,
    *,
    static_queries: list[str],
) -> _Feedback:
    keeps = _verdict_counter(catalog, "keep")
    junks = _verdict_counter(catalog, "junk")

    top = [
        {"query": query[:_TITLE_CHARS], "keeps": count}
        for query, count in keeps.most_common(TOOL_ITEM_CAP)
    ]
    weak = [
        {"query": query[:_TITLE_CHARS], "junk": count}
        for query, count in junks.most_common(TOOL_ITEM_CAP * 2)
        if keeps.get(query, 0) == 0
    ][:TOOL_ITEM_CAP]

    seen: set[str] = set()
    existing: list[str] = []
    for query in list(static_queries) + list(keeps) + list(junks):
        key = dedupe_key(query)
        if not key or key in seen:
            continue
        seen.add(key)
        existing.append(query[:_TITLE_CHARS])

    return _Feedback(
        top=top,
        weak=weak,
        existing=existing,
        known_keys=seen,
        titles=_sample_titles(catalog, "keep", TOOL_ITEM_CAP),
    )


def build_tools(feedback: _Feedback, *, enable_web_search: bool) -> list[Any]:
    from app.cloudflare_ai.agent import AgentTool

    no_args: dict[str, Any] = {"type": "object", "properties": {}}

    tools = [
        AgentTool(
            name="get_top_queries",
            description="Search queries that produced the most 'keep' verdicts so far.",
            parameters=no_args,
            handler=lambda _args: feedback.top,
        ),
        AgentTool(
            name="get_weak_queries",
            description="Search queries that produced only 'junk' results. Avoid these patterns.",
            parameters=no_args,
            handler=lambda _args: feedback.weak,
        ),
        AgentTool(
            name="get_existing_queries",
            description="Queries already in use. Never propose one of these again.",
            parameters=no_args,
            handler=lambda _args: feedback.existing[:TOOL_ITEM_CAP],
        ),
    ]

    if enable_web_search:
        from experiments.linkdir_finders.web_search import web_search

        tools.append(
            AgentTool(
                name="web_search",
                description=(
                    "Search the public web for Persian Telegram link-directory wording. "
                    "Returns a short list of {title, snippet}."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search phrase"}
                    },
                    "required": ["query"],
                },
                handler=lambda args: web_search(str(args.get("query") or "")),
            )
        )
    return tools


def _user_prompt(count: int, query_set: str, feedback: _Feedback) -> str:
    hint = QUERY_SET_HINTS.get(query_set, QUERY_SET_HINTS["fa"])
    lines = [
        f"Generate {count} NEW Telegram search queries for the '{query_set}' query set.",
        hint,
        "Prefer wording that real Persian link-directory admins put in channel names and bios.",
    ]
    if feedback.titles:
        lines.append(
            "Titles of channels already classified as good: "
            + "; ".join(feedback.titles[:8])
        )
    lines.append(
        f'Answer with JSON only: {{"queries": ["...", "..."]}} containing {count} entries.'
    )
    return "\n".join(lines)


def _extract_candidates(data: Any, content: str) -> list[str]:
    if isinstance(data, dict):
        rows = data.get("queries")
    elif isinstance(data, list):
        rows = data
    else:
        rows = None
    if not isinstance(rows, list):
        from app.cloudflare_ai.agent import parse_json_object

        parsed = parse_json_object(content)
        rows = parsed.get("queries") if isinstance(parsed, dict) else parsed
    if not isinstance(rows, list):
        return []
    return [str(item) for item in rows if str(item).strip()]


def generate_queries(
    count: int = 15,
    query_set: str = "fa",
    cfg: dict[str, Any] | None = None,
    *,
    provider: Any = None,
    catalog: Any = None,
    static_queries: list[str] | None = None,
    enable_web_search: bool | None = None,
    model: str | None = None,
    max_tool_rounds: int | None = None,
) -> QueryGenResult:
    """Generate validated search queries. Never raises — check ``ok``."""
    settings = ai_config(cfg)
    shard = (query_set or "fa").strip().lower() or "fa"
    want = max(1, int(count))
    use_web = bool(settings.get("web_search", False) if enable_web_search is None else enable_web_search)
    rounds = int(max_tool_rounds if max_tool_rounds is not None else settings.get("max_tool_rounds") or 4)

    try:
        if provider is None:
            from app.cloudflare_ai.hydrate import ensure_store
            from app.cloudflare_ai.provider import CloudflareAIProvider

            store = ensure_store()
            if not store.usable_accounts():
                return QueryGenResult(
                    ok=False,
                    reason="no_accounts",
                    diagnostics={"store": str(store.path)},
                )
            provider = CloudflareAIProvider(
                store, model=model or settings.get("model") or None
            )

        if catalog is None:
            from experiments.linkdir_finders.catalog import LinkDirCatalog

            catalog = LinkDirCatalog()

        if static_queries is None:
            from experiments.linkdir_finders.job_queue import queries_for_set

            static_queries = queries_for_set(cfg or {}, shard)

        feedback = collect_feedback(catalog, static_queries=list(static_queries))
        tools = build_tools(feedback, enable_web_search=use_web)
    except Exception as exc:  # noqa: BLE001 - setup must not break the pipeline
        logger.warning("AI query generation setup failed: %s", exc)
        return QueryGenResult(ok=False, reason="setup_failed", diagnostics={"error": str(exc)[:200]})

    from app.cloudflare_ai.agent import Agent

    agent = Agent(
        provider,
        system_prompt=SYSTEM_PROMPT,
        tools=tools,
        max_tool_rounds=rounds,
        response_schema=RESPONSE_SCHEMA,
        temperature=0.8,
    )
    result = agent.run(_user_prompt(want, shard, feedback))
    diagnostics: dict[str, Any] = result.diagnostics()
    if use_web:
        from experiments.linkdir_finders.web_search import backend_name

        diagnostics["web_search_backend"] = backend_name()

    if not result.ok:
        return QueryGenResult(
            ok=False, reason=result.reason, diagnostics=diagnostics
        )

    candidates = _extract_candidates(result.data, result.content)
    if not candidates:
        diagnostics["error"] = "model returned no queries"
        return QueryGenResult(ok=False, reason="empty_output", diagnostics=diagnostics)

    accepted, rejected = filter_queries(candidates, known=feedback.known_keys, limit=want)
    diagnostics["candidates"] = len(candidates)
    if not accepted:
        return QueryGenResult(
            ok=False,
            reason="all_rejected",
            rejected=rejected,
            diagnostics=diagnostics,
        )

    return QueryGenResult(
        ok=True,
        queries=accepted,
        used_ai=True,
        reason="ok",
        rejected=rejected,
        diagnostics=diagnostics,
    )
