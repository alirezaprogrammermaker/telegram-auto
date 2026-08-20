"""Tests for lesson validation, contrastive reflection and lesson recall."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from app.cloudflare_ai.provider import ChatResult
from experiments.linkdir_finders import ai_queries, reflection
from experiments.linkdir_finders.ai_queries import (
    SYSTEM_PROMPT,
    build_system_prompt,
    collect_lessons,
    generate_queries,
)
from experiments.linkdir_finders.query_validator import (
    disallowed_lesson_chars,
    is_valid_lesson,
    lesson_key,
    normalize_lesson,
    validate_lesson,
)
from experiments.linkdir_finders.reflection import parse_lessons, reflect

ROOT = Path(__file__).resolve().parents[1]

GOOD_LESSON = "کوئری‌های ترکیبی نام شهر و لینکدونی نتیجه بهتری می‌دهند"
AVOID_LESSON = "از کلمه رایگان به تنهایی استفاده نکن چون نتایج تبلیغاتی می‌آورد"

CFG: dict[str, Any] = {
    "queries_fa": ["تبادل لینک", "لینکدونی"],
    "ai_queries": {"enabled": True, "count": 5, "web_search": False, "max_tool_rounds": 2},
}


class ScriptedProvider:
    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> ChatResult:
        self.calls.append({"messages": messages, **kwargs})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return ChatResult(
            content=item,
            model="@cf/openai/gpt-oss-120b",
            account_name="a1",
            neurons=1.0,
        )


class FakeCatalog:
    def list_items(self, **_: Any) -> list[dict[str, Any]]:
        return []


class FakeMemory:
    """In-memory stand-in for the D1-backed bridge."""

    def __init__(
        self,
        episodes: list[dict[str, Any]] | None = None,
        lessons: list[dict[str, Any]] | None = None,
        *,
        available: bool = True,
    ) -> None:
        self._episodes = episodes or []
        self._lessons = lessons or []
        self._available = available
        self.written: list[dict[str, Any]] = []
        self.consolidated: list[int] = []

    def available(self) -> bool:
        return self._available

    def episodes(
        self,
        *,
        scored: bool | None = None,
        limit: int = 50,
        order: str = "recent",
        consolidated: bool | None = None,
    ) -> list[dict[str, Any]]:
        rows = list(self._episodes)
        if scored is not None:
            rows = [r for r in rows if (r.get("reward") is not None) is scored]
        if consolidated is not None:
            rows = [r for r in rows if bool(r.get("consolidated")) is consolidated]
        if order in {"best", "worst"}:
            rows.sort(key=lambda r: float(r.get("reward") or 0.0), reverse=order == "best")
        return rows[:limit]

    def lessons(self, *, limit: int = 20, kind: str | None = None) -> list[dict[str, Any]]:
        rows = [r for r in self._lessons if kind is None or r.get("kind") == kind]
        return rows[:limit]

    def add_lessons(self, lessons: list[dict[str, Any]]) -> dict[str, int]:
        self.written.extend(lessons)
        return {"created": len(lessons), "reinforced": 0}

    def mark_consolidated(self, episode_ids: Any) -> int:
        self.consolidated = list(episode_ids)
        return len(self.consolidated)


def _episodes(count: int = 12) -> list[dict[str, Any]]:
    return [
        {
            "id": i + 1,
            "subject": f"لینکدونی شهر {i}",
            "subject_key": f"k{i}",
            "query_set": "fa",
            "keep_count": i,
            "review_count": 1,
            "junk_count": 12 - i,
            "reward": round(i / 12, 3),
            "consolidated": 0,
        }
        for i in range(count)
    ]


# --------------------------------------------------------------------------
# lesson validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize("lesson", [GOOD_LESSON, AVOID_LESSON, "روی نام شهرها تمرکز کن نه واژه عمومی link"])
def test_accepts_persian_sentences(lesson: str) -> None:
    assert is_valid_lesson(lesson), validate_lesson(lesson)


@pytest.mark.parametrize(
    ("lesson", "script"),
    [
        ("کوئری‌های 链接目录 بهتر جواب می‌دهند", "chinese"),
        ("از обмен ссылками استفاده نکن هرگز", "cyrillic"),
        ("لینکدونی شهرها بهتر است 🔥 حتما", "emoji"),
        ("リンク集 را امتحان کن برای نتیجه", "katakana"),
        ("링크 모음 را امتحان کن برای نتیجه", "hangul"),
    ],
)
def test_rejects_foreign_scripts_inside_lessons(lesson: str, script: str) -> None:
    reason = validate_lesson(lesson)
    assert reason is not None, f"{script} slipped through"
    assert reason.startswith("disallowed_chars:"), reason


def test_rejects_lessons_that_are_not_persian() -> None:
    assert validate_lesson("prefer city names over generic words") == "not_persian"


@pytest.mark.parametrize(
    ("lesson", "reason"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("خوب بود", "too_short"),
        ("لینکدونی " * 60, "too_long"),
        ("لینکدونی شهرها و کانال‌ها " + "واژه " * 45, "too_long"),
    ],
)
def test_lesson_shape_rules(lesson: str, reason: str) -> None:
    assert validate_lesson(lesson) == reason


def test_word_count_ceiling_applies_below_the_length_ceiling() -> None:
    lesson = " ".join(["ab"] * 45) + " لینکدونی"
    assert validate_lesson(lesson) == "too_many_words"


def test_lesson_punctuation_is_allowed_but_foreign_scripts_are_not() -> None:
    assert disallowed_lesson_chars("کوئری «شهر»، مثلا: مشهد (fa)؟") == []
    assert disallowed_lesson_chars("کوئری 链接") == ["链", "接"]


def test_newlines_are_folded_rather_than_rejected() -> None:
    assert normalize_lesson("خط اول\nخط دوم") == "خط اول خط دوم"


# --------------------------------------------------------------------------
# lesson_key stability
# --------------------------------------------------------------------------


def test_lesson_key_is_stable_across_cosmetic_rewording() -> None:
    base = lesson_key(GOOD_LESSON)
    assert lesson_key(f"  {GOOD_LESSON}  ") == base
    assert lesson_key(GOOD_LESSON + "،") == base
    assert lesson_key(GOOD_LESSON.replace(" ", "  ")) == base
    assert lesson_key(GOOD_LESSON.replace("\u06cc", "\u064a")) == base
    assert lesson_key(GOOD_LESSON.replace("\u200c", "")) == base


def test_lesson_key_separates_different_advice() -> None:
    assert lesson_key(GOOD_LESSON) != lesson_key(AVOID_LESSON)


def test_lesson_key_is_a_short_hex_digest() -> None:
    key = lesson_key(GOOD_LESSON)
    assert len(key) == 16
    assert all(ch in "0123456789abcdef" for ch in key)


# --------------------------------------------------------------------------
# grounding
# --------------------------------------------------------------------------


def test_parse_lessons_keeps_only_grounded_claims() -> None:
    accepted, rejected = parse_lessons(
        {
            "lessons": [
                {"kind": "do", "lesson": GOOD_LESSON, "evidence": [1, 2], "confidence": 0.8},
                {"kind": "avoid", "lesson": AVOID_LESSON, "evidence": [99]},
                {"kind": "do", "lesson": "از 链接目录 استفاده کن برای نتیجه", "evidence": [1]},
                {"kind": "sideways", "lesson": GOOD_LESSON, "evidence": [1]},
                {"kind": "do", "lesson": AVOID_LESSON, "evidence": []},
                "not an object",
            ]
        },
        allowed_ids={1, 2, 3},
    )

    assert [row["lesson"] for row in accepted] == [GOOD_LESSON]
    assert accepted[0]["evidence"] == [1, 2]
    assert accepted[0]["lesson_key"] == lesson_key(GOOD_LESSON)
    reasons = [row["reason"] for row in rejected]
    assert reasons[0] == "ungrounded_evidence"
    assert reasons[1].startswith("disallowed_chars:")
    assert reasons[2:] == ["bad_kind", "no_evidence", "not_an_object"]


def test_parse_lessons_drops_partially_ungrounded_evidence() -> None:
    accepted, rejected = parse_lessons(
        {"lessons": [{"kind": "do", "lesson": GOOD_LESSON, "evidence": [1, 404]}]},
        allowed_ids={1},
    )
    assert accepted == []
    assert rejected[0]["reason"] == "ungrounded_evidence"


def test_parse_lessons_dedupes_by_lesson_key() -> None:
    accepted, rejected = parse_lessons(
        {
            "lessons": [
                {"kind": "do", "lesson": GOOD_LESSON, "evidence": [1]},
                {"kind": "do", "lesson": f" {GOOD_LESSON}، ", "evidence": [2]},
            ]
        },
        allowed_ids={1, 2},
    )
    assert len(accepted) == 1
    assert rejected[0]["reason"] == "duplicate"


def test_parse_lessons_caps_the_batch() -> None:
    rows = [
        {"kind": "do", "lesson": f"{GOOD_LESSON} شماره {i}", "evidence": [1]}
        for i in range(reflection.MAX_LESSONS + 3)
    ]
    accepted, rejected = parse_lessons({"lessons": rows}, allowed_ids={1})
    assert len(accepted) == reflection.MAX_LESSONS
    assert [row["reason"] for row in rejected] == ["over_limit"] * 3


def test_parse_lessons_survives_a_non_list_payload() -> None:
    accepted, rejected = parse_lessons("garbage", allowed_ids={1})
    assert accepted == []
    assert rejected[0]["reason"] == "not_a_list"


# --------------------------------------------------------------------------
# reflection pass
# --------------------------------------------------------------------------


def test_reflection_skips_cleanly_without_enough_evidence() -> None:
    result = reflect(memory=FakeMemory(_episodes(3)), provider=ScriptedProvider([]))

    assert result.ok is False
    assert result.reason == "insufficient_evidence"
    assert result.summary()["available"] == 3


def test_reflection_skips_when_memory_is_unavailable() -> None:
    result = reflect(memory=FakeMemory(_episodes(), available=False))

    assert result.ok is False
    assert result.reason == "memory_unavailable"
    assert json.loads(json.dumps(result.summary()))["lessons"] == 0


def test_reflection_ignores_already_consolidated_episodes() -> None:
    episodes = _episodes()
    for row in episodes[:6]:
        row["consolidated"] = 1
    result = reflect(memory=FakeMemory(episodes), provider=ScriptedProvider([]))

    assert result.reason == "insufficient_evidence"
    assert result.summary()["available"] == 6


def test_reflection_writes_grounded_lessons_and_consolidates() -> None:
    memory = FakeMemory(_episodes())
    provider = ScriptedProvider(
        [
            json.dumps(
                {
                    "lessons": [
                        {"kind": "do", "lesson": GOOD_LESSON, "evidence": [11], "confidence": 0.9},
                        {"kind": "avoid", "lesson": AVOID_LESSON, "evidence": [1]},
                        {"kind": "do", "lesson": GOOD_LESSON + " واقعا", "evidence": [777]},
                    ]
                },
                ensure_ascii=False,
            )
        ]
    )

    result = reflect(memory=memory, provider=provider)

    assert result.ok is True
    assert result.created == 2
    assert [row["kind"] for row in memory.written] == ["do", "avoid"]
    assert result.consolidated == len(result.episode_ids)
    assert memory.consolidated == result.episode_ids
    assert [row["reason"] for row in result.rejected] == ["ungrounded_evidence"]


def test_reflection_prompt_is_contrastive_and_carries_ids() -> None:
    memory = FakeMemory(_episodes())
    provider = ScriptedProvider(
        [json.dumps({"lessons": [{"kind": "do", "lesson": GOOD_LESSON, "evidence": [11]}]}, ensure_ascii=False)]
    )
    reflect(memory=memory, provider=provider, best=3, worst=3, min_episodes=6)

    prompt = provider.calls[0]["messages"][-1]["content"]
    assert "Best-performing" in prompt
    assert "Worst-performing" in prompt
    assert "#12" in prompt and "#1 " in prompt


def test_reflection_keeps_evidence_when_the_model_produces_nothing_usable() -> None:
    memory = FakeMemory(_episodes())
    provider = ScriptedProvider(
        [json.dumps({"lessons": [{"kind": "do", "lesson": "生成更好的查询", "evidence": [1]}]})]
    )

    result = reflect(memory=memory, provider=provider)

    assert result.ok is False
    assert result.reason == "no_valid_lessons"
    assert memory.written == []
    assert memory.consolidated == []


def test_reflection_dry_run_writes_nothing() -> None:
    memory = FakeMemory(_episodes())
    provider = ScriptedProvider(
        [json.dumps({"lessons": [{"kind": "do", "lesson": GOOD_LESSON, "evidence": [1]}]}, ensure_ascii=False)]
    )

    result = reflect(memory=memory, provider=provider, dry_run=True)

    assert result.ok is True
    assert result.reason == "dry_run"
    assert memory.written == []
    assert memory.consolidated == []


def test_reflection_never_raises_when_memory_explodes() -> None:
    class BrokenMemory:
        def available(self) -> bool:
            return True

        def episodes(self, **_: Any) -> list[dict[str, Any]]:
            raise RuntimeError("d1 unreachable")

    result = reflect(memory=BrokenMemory(), provider=ScriptedProvider([]))

    assert result.ok is False
    assert result.reason == "setup_failed"


def test_reflection_reports_provider_failure_without_raising() -> None:
    memory = FakeMemory(_episodes())
    provider = ScriptedProvider([RuntimeError("cloudflare 500")])

    result = reflect(memory=memory, provider=provider)

    assert result.ok is False
    assert result.reason == "provider_error"
    assert memory.consolidated == []


@pytest.fixture
def reflect_script():
    spec = importlib.util.spec_from_file_location(
        "reflect_agent_memory_under_test", ROOT / "scripts" / "reflect_agent_memory.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reflect_script_exits_zero_when_memory_is_down(
    reflect_script: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        reflect_script,
        "reflect",
        lambda **_: reflection.ReflectionResult(ok=False, reason="memory_unavailable"),
    )
    monkeypatch.setattr(sys, "argv", ["reflect_agent_memory.py"])

    assert reflect_script.main() == 0
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary["reason"] == "memory_unavailable"
    assert summary["agent"] == "linkdir_query"


# --------------------------------------------------------------------------
# recall
# --------------------------------------------------------------------------


def _lesson_rows() -> list[dict[str, Any]]:
    return [
        {"kind": "do", "lesson": GOOD_LESSON, "confidence": 0.8, "support": 3},
        {"kind": "avoid", "lesson": AVOID_LESSON, "confidence": 0.7, "support": 2},
    ]


def test_collect_lessons_groups_by_kind() -> None:
    lessons = collect_lessons(FakeMemory(lessons=_lesson_rows()))

    assert lessons.do == [GOOD_LESSON]
    assert lessons.avoid == [AVOID_LESSON]
    assert lessons.total() == 2


def test_collect_lessons_is_empty_without_memory() -> None:
    assert collect_lessons(None).total() == 0
    assert collect_lessons(FakeMemory(available=False)).total() == 0


def test_collect_lessons_swallows_memory_errors() -> None:
    class BrokenMemory:
        def available(self) -> bool:
            return True

        def lessons(self, **_: Any) -> list[dict[str, Any]]:
            raise RuntimeError("bridge down")

    assert collect_lessons(BrokenMemory()).total() == 0


def test_system_prompt_is_untouched_without_lessons() -> None:
    assert build_system_prompt(None) == SYSTEM_PROMPT
    assert build_system_prompt(ai_queries._Lessons()) == SYSTEM_PROMPT


def test_system_prompt_injects_lessons_grouped_by_kind() -> None:
    prompt = build_system_prompt(collect_lessons(FakeMemory(lessons=_lesson_rows())))

    assert prompt.startswith(SYSTEM_PROMPT)
    assert "DO:" in prompt and "AVOID:" in prompt
    assert prompt.index("DO:") < prompt.index("AVOID:")
    assert GOOD_LESSON in prompt
    assert AVOID_LESSON in prompt


def test_generation_recalls_lessons_and_offers_the_tool() -> None:
    provider = ScriptedProvider([json.dumps({"queries": ["لینکدونی رشت"]}, ensure_ascii=False)])
    result = generate_queries(
        count=2,
        query_set="fa",
        cfg=CFG,
        provider=provider,
        catalog=FakeCatalog(),
        memory=FakeMemory(lessons=_lesson_rows()),
        static_queries=[],
    )

    system = provider.calls[0]["messages"][0]["content"]
    tool_names = {t["function"]["name"] for t in provider.calls[0]["tools"]}

    assert result.ok is True
    assert result.diagnostics["lessons_used"] == 2
    assert GOOD_LESSON in system
    assert "recall_lessons" in tool_names


def test_recall_tool_returns_lessons_on_demand() -> None:
    lessons = collect_lessons(FakeMemory(lessons=_lesson_rows()))
    tools = ai_queries.build_tools(
        ai_queries._Feedback(top=[], weak=[], existing=[], known_keys=set(), titles=[]),
        enable_web_search=False,
        lessons=lessons,
    )
    recall = {tool.name: tool for tool in tools}["recall_lessons"]

    assert recall.handler({}) == [
        {"kind": "do", "lesson": GOOD_LESSON},
        {"kind": "avoid", "lesson": AVOID_LESSON},
    ]
    assert recall.handler({"kind": "avoid"}) == [{"kind": "avoid", "lesson": AVOID_LESSON}]


def test_generation_is_unchanged_when_memory_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ADMIN_BOT_BRIDGE_URL", raising=False)
    monkeypatch.delenv("ADMIN_BOT_BRIDGE_TOKEN", raising=False)

    provider = ScriptedProvider([json.dumps({"queries": ["لینکدونی قم"]}, ensure_ascii=False)])
    result = generate_queries(
        count=2,
        query_set="fa",
        cfg=CFG,
        provider=provider,
        catalog=FakeCatalog(),
        static_queries=[],
    )

    tool_names = {t["function"]["name"] for t in provider.calls[0]["tools"]}

    assert result.ok is True
    assert provider.calls[0]["messages"][0]["content"] == SYSTEM_PROMPT
    assert "recall_lessons" not in tool_names
    assert result.diagnostics["lessons_used"] == 0


def test_generation_survives_a_broken_memory_backend() -> None:
    class BrokenMemory:
        def available(self) -> bool:
            raise RuntimeError("bridge exploded")

    provider = ScriptedProvider([json.dumps({"queries": ["لینکدونی اراک"]}, ensure_ascii=False)])
    result = generate_queries(
        count=2,
        query_set="fa",
        cfg=CFG,
        provider=provider,
        catalog=FakeCatalog(),
        memory=BrokenMemory(),
        static_queries=[],
    )

    assert result.ok is True
    assert result.queries == ["لینکدونی اراک"]
    assert provider.calls[0]["messages"][0]["content"] == SYSTEM_PROMPT
