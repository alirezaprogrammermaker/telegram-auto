"""Tests for the generated-query allowlist validator."""

from __future__ import annotations

import pytest

from experiments.linkdir_finders.query_validator import (
    dedupe_key,
    disallowed_chars,
    filter_queries,
    is_valid_query,
    normalize_query,
    validate_query,
)


@pytest.mark.parametrize(
    "query",
    [
        "لینکدونی",
        "تبادل لینک",
        "لینکدونی تهران",
        "گپ تبادل لینک آزاد",
        "link exchange",
        "telegram link dump",
        "لینکدونی 2026",
        "@linkdoni",
        "link-exchange",
        "link_dump",
        "t.me linkdoni",
        "لینک\u200cدونی",
    ],
)
def test_accepts_persian_and_latin_queries(query: str) -> None:
    assert is_valid_query(query), validate_query(query)


@pytest.mark.parametrize(
    ("query", "script"),
    [
        ("链接目录", "chinese"),
        ("لینکدونی 链接", "chinese mixed with persian"),
        ("电报群组", "chinese"),
        ("リンク集", "katakana"),
        ("ひらがな", "hiragana"),
        ("링크 모음", "hangul"),
        ("обмен ссылками", "cyrillic"),
        ("लिंक निर्देशिका", "devanagari"),
        ("λινκ", "greek"),
        ("לינק", "hebrew"),
        ("لینکدونی 🔥", "emoji"),
        ("🔗 links", "emoji"),
    ],
)
def test_rejects_foreign_scripts_and_emoji(query: str, script: str) -> None:
    reason = validate_query(query)
    assert reason is not None, f"{script} query slipped through: {query}"
    assert reason.startswith("disallowed_chars:"), reason


def test_rejection_reason_names_offending_codepoint() -> None:
    reason = validate_query("لینکدونی 链接")
    assert reason == "disallowed_chars:U+94FE,U+63A5"


def test_disallowed_chars_lists_distinct_offenders() -> None:
    assert disallowed_chars("ab链链接") == ["链", "接"]
    assert disallowed_chars("لینکدونی link_2") == []


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("ل", "too_short"),
        ("a" * 41, "too_long"),
        ("one two three four five six", "too_many_words"),
        ("queries: لینکدونی", "looks_like_prose"),
        ("لینکدونی\nتبادل لینک", "looks_like_prose"),
        ('"لینکدونی"', "looks_like_prose"),
        ("لینکدونی، تبادل", "looks_like_prose"),
        ("باشگاه تبادل لینک", "fancy_prefix"),
        ("آرشیو لینک رایگان", "fancy_prefix"),
        ("پروژه لینکدونی", "fancy_prefix"),
        ("مرکز تبادل لینک تخصصی", "fancy_prefix"),
        ("گپ تبلیغات آزاد", "missing_core_anchor"),
        ("تبادل لینک عکاسی", "weak_niche_topic"),
        ("تبادل لینک کتاب", "weak_niche_topic"),
        ("لینکدونی تهران گپ چت آزاد", "too_specific_persian"),
    ],
)
def test_shape_rules(query: str, reason: str) -> None:
    assert validate_query(query) == reason


def test_accepts_proven_short_cores() -> None:
    for query in (
        "تبادل لینک",
        "لینکدونی",
        "ثبت لینک رایگان",
        "لینکدونی تهران",
        "گروه تبادل لینک",
    ):
        assert is_valid_query(query), validate_query(query)


def test_length_boundaries_are_inclusive() -> None:
    assert is_valid_query("ab")
    assert is_valid_query("a" * 40)
    assert not is_valid_query("a" * 41)


def test_normalize_arabic_variants_and_tatweel() -> None:
    assert normalize_query("تبادل لينك") == "تبادل لینک"
    assert normalize_query("لینـــکدونی") == "لینکدونی"
    assert normalize_query("  تبادل   لینک  ") == "تبادل لینک"


def test_normalize_keeps_zwnj_but_dedupe_ignores_it() -> None:
    assert "\u200c" in normalize_query("لینک\u200cدونی")
    assert dedupe_key("لینک\u200cدونی") == dedupe_key("لینکدونی")


def test_dedupe_key_is_case_and_punctuation_insensitive() -> None:
    assert dedupe_key("Link-Exchange") == dedupe_key("link exchange")
    assert dedupe_key("@LinkDoni") == dedupe_key("linkdoni")


def test_duplicate_detection_uses_normalized_form() -> None:
    known = {dedupe_key("تبادل لینک")}
    assert validate_query("تبادل لينك", known_keys=known) == "duplicate"
    assert validate_query("تبادل لینک جدید", known_keys=known) is None


def test_filter_queries_splits_accepted_and_rejected() -> None:
    accepted, rejected = filter_queries(
        [
            "لینکدونی مشهد",
            "链接目录",
            "تبادل لينك",
            "تبادل لینک",
            "a" * 60,
            "link exchange",
        ],
        known=["تبادل لینک"],
    )
    assert accepted == ["لینکدونی مشهد", "link exchange"]
    reasons = [row["reason"] for row in rejected]
    assert reasons[0].startswith("disallowed_chars:U+94FE")
    assert reasons[1:] == ["duplicate", "duplicate", "too_long"]


def test_filter_queries_dedupes_within_the_batch() -> None:
    accepted, rejected = filter_queries(["لینکدونی", "لینـکدونی", "لینکدونی گپ"])
    assert accepted == ["لینکدونی", "لینکدونی گپ"]
    assert rejected == [{"query": "لینـکدونی", "reason": "duplicate"}]


def test_filter_queries_honours_limit() -> None:
    accepted, rejected = filter_queries(
        ["لینکدونی یک", "لینکدونی دو", "لینکدونی سه"], limit=2
    )
    assert len(accepted) == 2
    assert rejected == [{"query": "لینکدونی سه", "reason": "over_limit"}]


def test_filter_queries_normalizes_accepted_output() -> None:
    accepted, _ = filter_queries(["  تبادل   لينك  "])
    assert accepted == ["تبادل لینک"]


def test_filter_queries_rejects_non_string_items() -> None:
    accepted, rejected = filter_queries([None, 12345, {"q": "x"}, "لینکدونی"])
    assert accepted == ["لینکدونی"]
    assert [row["reason"] for row in rejected] == ["not_a_string"] * 3
