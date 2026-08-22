"""Strict validation for machine-generated Telegram search queries and lessons.

A JSON schema constrains the *shape* of model output, never its script, so
models routinely slip CJK, Cyrillic or emoji into otherwise plausible Persian
text. This module is the allowlist gate every generated string must pass
before it can reach the job queue or the lesson store.

Queries and lessons share the script allowlist and the normalizer but not the
shape rules: a query is a 1-5 word search phrase, a lesson is a Persian
sentence, so :func:`validate_lesson` is a separate gate rather than a looser
:func:`validate_query`.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any, Iterable

MIN_LENGTH = 2
MAX_LENGTH = 40
MIN_WORDS = 1
MAX_WORDS = 5

# Words that make Telegram contacts.Search return almost nothing for
# لینکدونی discovery (local probe 2026-08-21). Prefer short core phrases.
_FANCY_PREFIXES = (
    "باشگاه",
    "آرشیو",
    "پروژه",
    "مرکز",
    "پلتفرم",
    "سامانه",
    "انجمن",
    "کلوب",
    "کلاب",
    "آکادمی",
    "دانشنامه",
)
_FANCY_SUFFIXES = ("تخصصی", "حرفه‌ای", "رسمی", "بین‌المللی", "بین المللی")
_WEAK_NICHE_TOPICS = (
    "کتاب",
    "عکاسی",
    "موسیقی",
    "ورزش",
    "شعر",
    "آشپزی",
    "pdf",
    "پادکست",
)
_CORE_ANCHORS = (
    "لینکدونی",
    "لینک دونی",
    "تبادل لینک",
    "لینک رایگان",
    "ثبت لینک",
    "تبلیغ رایگان",
    "دیوار لینک",
    "پخش لینک",
    "گروه لینک",
    "کانال لینک",
    "linkdoni",
    "link exchange",
    "link dump",
    "links directory",
)

LESSON_MIN_LENGTH = 12
LESSON_MAX_LENGTH = 220
LESSON_MIN_WORDS = 3
LESSON_MAX_WORDS = 40

ZWNJ = "\u200c"
TATWEEL = "\u0640"

# Persian codepoints outside the U+0600–U+06FF block: the ژ presentation form
# some models emit, plus the zero-width non-joiner used in Persian compounds.
_EXTRA_ALLOWED = {"\ufb8a", ZWNJ}
_ALLOWED_PUNCT = set("_-@.")
_PROSE_MARKERS = (":", "\n", "\r", "\t", "|", "،", "؛", "؟", "?", '"', "'")

# Sentence punctuation a lesson may use but a search query may not.
_LESSON_PUNCT = set("،؛؟:!?,;()«»\"'/%+×٪")

_WHITESPACE_RE = re.compile(r"\s+")
_ARABIC_RANGE = ("\u0600", "\u06ff")


def _is_allowed_char(ch: str) -> bool:
    if ch == " ":
        return True
    if ch in _EXTRA_ALLOWED or ch in _ALLOWED_PUNCT:
        return True
    if _ARABIC_RANGE[0] <= ch <= _ARABIC_RANGE[1]:
        return True
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ("0" <= ch <= "9")


def disallowed_chars(text: str) -> list[str]:
    """Return the distinct characters that fall outside the allowlist."""
    seen: list[str] = []
    for ch in text:
        if _is_allowed_char(ch) or ch in seen:
            continue
        seen.append(ch)
    return seen


def normalize_query(text: str) -> str:
    """Canonicalize Persian spelling variants and whitespace."""
    raw = unicodedata.normalize("NFC", str(text or ""))
    raw = raw.replace("\u064a", "\u06cc").replace("\u0649", "\u06cc")
    raw = raw.replace("\u0643", "\u06a9")
    raw = raw.replace(TATWEEL, "")
    return _WHITESPACE_RE.sub(" ", raw).strip()


def dedupe_key(text: str) -> str:
    """Comparison key: ZWNJ- punctuation- and case-insensitive."""
    normalized = normalize_query(text).lower().replace(ZWNJ, "")
    stripped = "".join(" " if ch in _ALLOWED_PUNCT else ch for ch in normalized)
    return _WHITESPACE_RE.sub(" ", stripped).strip()


def validate_query(query: str, *, known_keys: set[str] | None = None) -> str | None:
    """Return a rejection reason, or ``None`` when the query is acceptable."""
    raw = str(query or "")
    if not raw.strip():
        return "empty"
    if any(marker in raw for marker in _PROSE_MARKERS):
        return "looks_like_prose"

    normalized = normalize_query(raw)
    if not normalized:
        return "empty"

    bad = disallowed_chars(normalized)
    if bad:
        codes = ",".join(f"U+{ord(ch):04X}" for ch in bad[:4])
        return f"disallowed_chars:{codes}"

    if len(normalized) < MIN_LENGTH:
        return "too_short"
    if len(normalized) > MAX_LENGTH:
        return "too_long"

    words = normalized.split(" ")
    if len(words) < MIN_WORDS:
        return "too_few_words"
    if len(words) > MAX_WORDS:
        return "too_many_words"

    fancy_reason = _telegram_search_effectiveness(normalized)
    if fancy_reason:
        return fancy_reason

    if known_keys is not None and dedupe_key(normalized) in known_keys:
        return "duplicate"
    return None


def _telegram_search_effectiveness(normalized: str) -> str | None:
    """Reject phrases that Telegram search does not match for linkdirs."""
    lower = normalized.lower().replace(ZWNJ, "")
    words = lower.split(" ")
    if words and words[0] in _FANCY_PREFIXES:
        return "fancy_prefix"
    if any(suf.replace(ZWNJ, "") in lower for suf in _FANCY_SUFFIXES):
        return "fancy_suffix"
    if any(topic in lower for topic in _WEAK_NICHE_TOPICS):
        return "weak_niche_topic"
    # Persian multi-word queries need a proven anchor; otherwise Search
    # returns empty or off-topic hobby groups.
    if has_persian(normalized) and len(words) >= 2:
        if not any(anchor.replace(ZWNJ, "") in lower for anchor in _CORE_ANCHORS):
            return "missing_core_anchor"
        # 5+ word Persian phrases almost never beat short cores.
        if len(words) >= 5:
            return "too_specific_persian"
    return None


def is_valid_query(query: str, *, known_keys: set[str] | None = None) -> bool:
    return validate_query(query, known_keys=known_keys) is None


def _is_allowed_lesson_char(ch: str) -> bool:
    return _is_allowed_char(ch) or ch in _LESSON_PUNCT


def disallowed_lesson_chars(text: str) -> list[str]:
    """Distinct characters in a lesson that fall outside the allowlist."""
    seen: list[str] = []
    for ch in text:
        if _is_allowed_lesson_char(ch) or ch in seen:
            continue
        seen.append(ch)
    return seen


def has_persian(text: str) -> bool:
    return any(_ARABIC_RANGE[0] <= ch <= _ARABIC_RANGE[1] for ch in text)


def normalize_lesson(text: str) -> str:
    """Collapse a lesson to one canonical single-line sentence."""
    return normalize_query(str(text or "").replace("\n", " ").replace("\r", " "))


def validate_lesson(lesson: str) -> str | None:
    """Return a rejection reason, or ``None`` when the lesson is acceptable.

    Same script allowlist as :func:`validate_query` plus sentence punctuation,
    with sentence-sized length limits and a requirement that the lesson is
    actually written in Persian.
    """
    normalized = normalize_lesson(lesson)
    if not normalized:
        return "empty"

    bad = disallowed_lesson_chars(normalized)
    if bad:
        codes = ",".join(f"U+{ord(ch):04X}" for ch in bad[:4])
        return f"disallowed_chars:{codes}"

    if len(normalized) < LESSON_MIN_LENGTH:
        return "too_short"
    if len(normalized) > LESSON_MAX_LENGTH:
        return "too_long"

    words = [w for w in normalized.split(" ") if w]
    if len(words) < LESSON_MIN_WORDS:
        return "too_few_words"
    if len(words) > LESSON_MAX_WORDS:
        return "too_many_words"

    if not has_persian(normalized):
        return "not_persian"
    return None


def is_valid_lesson(lesson: str) -> bool:
    return validate_lesson(lesson) is None


def lesson_key(lesson: str) -> str:
    """Stable id for a lesson: normalized, lowercased, punctuation-stripped.

    Re-learning the same advice with different wording noise therefore bumps
    ``support`` on the existing row instead of creating a near-duplicate.
    """
    normalized = normalize_lesson(lesson).lower().replace(ZWNJ, "")
    stripped = "".join(
        " " if (ch in _ALLOWED_PUNCT or ch in _LESSON_PUNCT) else ch
        for ch in normalized
    )
    canonical = _WHITESPACE_RE.sub(" ", stripped).strip()
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


def filter_queries(
    queries: Iterable[Any],
    *,
    known: Iterable[str] = (),
    limit: int | None = None,
) -> tuple[list[str], list[dict[str, str]]]:
    """Split candidates into accepted (normalized, deduped) and rejected."""
    known_keys = {dedupe_key(item) for item in known if str(item).strip()}
    accepted: list[str] = []
    rejected: list[dict[str, str]] = []

    for candidate in queries:
        if limit is not None and len(accepted) >= limit:
            rejected.append({"query": str(candidate)[:60], "reason": "over_limit"})
            continue
        if not isinstance(candidate, str):
            rejected.append({"query": str(candidate)[:60], "reason": "not_a_string"})
            continue
        text = candidate
        reason = validate_query(text, known_keys=known_keys)
        if reason:
            rejected.append({"query": text[:60], "reason": reason})
            continue
        normalized = normalize_query(text)
        known_keys.add(dedupe_key(normalized))
        accepted.append(normalized)

    return accepted, rejected
