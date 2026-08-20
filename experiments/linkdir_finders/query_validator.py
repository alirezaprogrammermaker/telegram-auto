"""Strict validation for machine-generated Telegram search queries.

A JSON schema constrains the *shape* of model output, never its script, so
models routinely slip CJK, Cyrillic or emoji into otherwise plausible Persian
queries. This module is the allowlist gate every generated query must pass
before it can reach the job queue.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

MIN_LENGTH = 2
MAX_LENGTH = 40
MIN_WORDS = 1
MAX_WORDS = 5

ZWNJ = "\u200c"
TATWEEL = "\u0640"

# Persian codepoints outside the U+0600–U+06FF block: the ژ presentation form
# some models emit, plus the zero-width non-joiner used in Persian compounds.
_EXTRA_ALLOWED = {"\ufb8a", ZWNJ}
_ALLOWED_PUNCT = set("_-@.")
_PROSE_MARKERS = (":", "\n", "\r", "\t", "|", "،", "؛", "؟", "?", '"', "'")

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

    if known_keys is not None and dedupe_key(normalized) in known_keys:
        return "duplicate"
    return None


def is_valid_query(query: str, *, known_keys: set[str] | None = None) -> bool:
    return validate_query(query, known_keys=known_keys) is None


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
