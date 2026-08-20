"""Tests for context-aware lesson recall ranking."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from experiments.linkdir_finders.lesson_recall import (
    format_lessons_for_prompt,
    infer_scope,
    rank_lessons,
    scope_matches,
)


def test_city_lesson_scope_is_not_english() -> None:
    scope = infer_scope("در کوئری‌های فارسی از نام شهرهای ایران هم استفاده کن")
    assert scope_matches(scope, "fa")
    assert scope_matches(scope, "niche")
    assert not scope_matches(scope, "en")


def test_english_shard_skips_persian_city_tip() -> None:
    rows = [
        {
            "kind": "do",
            "lesson": "در کوئری‌ها از نام شهرهای ایران استفاده کن",
            "scope": "fa,niche",
            "origin": "admin_teach",
            "confidence": 0.9,
            "support": 1,
            "evidence": [],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        {
            "kind": "do",
            "lesson": "برای انگلیسی از عبارتهای کوتاه و رایج مثل link exchange استفاده کن",
            "scope": "en",
            "origin": "reflection",
            "confidence": 0.7,
            "support": 4,
            "evidence": [1, 2, 3],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    ]
    picked = rank_lessons(rows, "en")
    assert len(picked) == 1
    assert "link exchange" in picked[0].lesson or picked[0].scope == "en"


def test_admin_tip_does_not_crowd_out_reflection_bank() -> None:
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "kind": "do",
            "lesson": "از نام شهرهای ایران در کوئری فارسی استفاده کن",
            "scope": "fa,niche",
            "origin": "admin_teach",
            "confidence": 0.95,
            "support": 1,
            "evidence": [],
            "updated_at": now,
        },
        {
            "kind": "do",
            "lesson": "کوئری دو یا سه کلمه‌ای برای لینکدونی بهتر جواب می‌دهد",
            "scope": "fa",
            "origin": "reflection",
            "confidence": 0.8,
            "support": 5,
            "evidence": [10, 11, 12],
            "updated_at": now,
        },
        {
            "kind": "avoid",
            "lesson": "از تک‌واژه خیلی عمومی مثل لینک به تنهایی پرهیز کن",
            "scope": "all",
            "origin": "reflection",
            "confidence": 0.75,
            "support": 3,
            "evidence": [20, 21],
            "updated_at": now,
        },
        {
            "kind": "do",
            "lesson": "دومین نکته ادمین که نباید همه جا غالب شود",
            "scope": "fa",
            "origin": "admin_teach",
            "confidence": 0.9,
            "support": 1,
            "evidence": [],
            "updated_at": now,
        },
    ]
    picked = rank_lessons(rows, "fa", do_limit=4, avoid_limit=3, max_admin_teach=1)
    admin = [row for row in picked if row.origin == "admin_teach"]
    reflection = [row for row in picked if row.origin == "reflection"]
    assert len(admin) <= 1
    assert len(reflection) >= 2
    assert any(row.kind == "avoid" for row in picked)


def test_stale_lessons_rank_below_fresh_reinforced_ones() -> None:
    now = datetime.now(timezone.utc)
    rows = [
        {
            "kind": "do",
            "lesson": "درس قدیمی کم‌تقویت‌شده درباره تبادل",
            "scope": "fa",
            "origin": "reflection",
            "confidence": 0.8,
            "support": 1,
            "evidence": [1],
            "updated_at": (now - timedelta(days=60)).isoformat(),
        },
        {
            "kind": "do",
            "lesson": "درس تازه با پشتیبانی بیشتر درباره لینکدونی تخصصی",
            "scope": "fa",
            "origin": "reflection",
            "confidence": 0.7,
            "support": 6,
            "evidence": [2, 3, 4],
            "updated_at": now.isoformat(),
        },
    ]
    picked = rank_lessons(rows, "fa")
    assert picked[0].lesson.startswith("درس تازه")


def test_prompt_marks_lessons_as_soft_hints() -> None:
    rows = rank_lessons(
        [
            {
                "kind": "do",
                "lesson": "از نام شهر در کوئری فارسی استفاده کن وقتی مرتبط است",
                "scope": "fa,niche",
                "origin": "admin_teach",
                "confidence": 0.72,
                "support": 1,
                "evidence": [],
            }
        ],
        "fa",
    )
    text = format_lessons_for_prompt(rows, query_set="fa")
    assert "NOT hard rules" in text
    assert "when relevant" in text.lower() or "DO (when relevant)" in text
