"""Optional web search backend for the query-generation agent.

Priority order: Brave (``BRAVE_SEARCH_API_KEY``/``SEARCH_API_KEY``), Serper
(``SERPER_API_KEY``), then a keyless DuckDuckGo Lite scrape. Everything is
best-effort: a failure, timeout or missing dependency yields ``[]`` so the
agent simply proceeds without web context.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger("linkdir_finders.web_search")

TIMEOUT_SECONDS = 8.0
MAX_RESULTS = 5
MAX_CALLS_PER_PROCESS = 6
MIN_INTERVAL_SECONDS = 1.5
_SNIPPET_CHARS = 180
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)

_DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"
_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
_SERPER_URL = "https://google.serper.dev/search"

_TAG_RE = re.compile(r"<[^>]+>")
# DuckDuckGo serves single- or double-quoted attributes and two markup flavours
# (lite/ and html/); accept either rather than depending on one layout.
_DDG_PATTERNS = tuple(
    re.compile(
        rf"<a[^>]*class=['\"]{link}['\"][^>]*>(?P<title>.*?)</a>.*?"
        rf"class=['\"]{snippet}['\"][^>]*>(?P<snippet>.*?)</(?:td|a)>",
        re.DOTALL | re.IGNORECASE,
    )
    for link, snippet in (("result-link", "result-snippet"), ("result__a", "result__snippet"))
)

_calls_made = 0
_last_call_at = 0.0


def reset_rate_limit() -> None:
    """Test hook: clear the per-process call budget."""
    global _calls_made, _last_call_at
    _calls_made = 0
    _last_call_at = 0.0


def available() -> bool:
    return True


def backend_name() -> str:
    if _api_key("BRAVE_SEARCH_API_KEY", "SEARCH_API_KEY"):
        return "brave"
    if _api_key("SERPER_API_KEY"):
        return "serper"
    return "duckduckgo_lite"


def _api_key(*names: str) -> str:
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def _strip_html(value: str) -> str:
    text = html.unescape(_TAG_RE.sub(" ", value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _http(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    method: str = "GET",
) -> str:
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"User-Agent": _USER_AGENT, "Accept-Language": "fa,en;q=0.8", **(headers or {})},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _throttle() -> None:
    global _last_call_at
    elapsed = time.monotonic() - _last_call_at
    if _last_call_at and elapsed < MIN_INTERVAL_SECONDS:
        time.sleep(MIN_INTERVAL_SECONDS - elapsed)
    _last_call_at = time.monotonic()


def _search_brave(query: str, key: str, limit: int) -> list[dict[str, str]]:
    url = f"{_BRAVE_URL}?{urllib.parse.urlencode({'q': query, 'count': limit})}"
    payload = json.loads(
        _http(url, headers={"Accept": "application/json", "X-Subscription-Token": key})
    )
    rows = ((payload.get("web") or {}).get("results")) or []
    return [
        {
            "title": _strip_html(str(row.get("title") or ""))[:120],
            "snippet": _strip_html(str(row.get("description") or ""))[:_SNIPPET_CHARS],
        }
        for row in rows[:limit]
        if isinstance(row, dict)
    ]


def _search_serper(query: str, key: str, limit: int) -> list[dict[str, str]]:
    body = json.dumps({"q": query, "num": limit}).encode("utf-8")
    payload = json.loads(
        _http(
            _SERPER_URL,
            method="POST",
            data=body,
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
        )
    )
    rows = payload.get("organic") or []
    return [
        {
            "title": _strip_html(str(row.get("title") or ""))[:120],
            "snippet": _strip_html(str(row.get("snippet") or ""))[:_SNIPPET_CHARS],
        }
        for row in rows[:limit]
        if isinstance(row, dict)
    ]


def _search_duckduckgo(query: str, limit: int) -> list[dict[str, str]]:
    body = urllib.parse.urlencode({"q": query, "kl": "wt-wt"}).encode("utf-8")
    page = _http(
        _DDG_LITE_URL,
        method="POST",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    for pattern in _DDG_PATTERNS:
        out: list[dict[str, str]] = []
        for match in pattern.finditer(page):
            title = _strip_html(match.group("title"))[:120]
            snippet = _strip_html(match.group("snippet"))[:_SNIPPET_CHARS]
            if title or snippet:
                out.append({"title": title, "snippet": snippet})
            if len(out) >= limit:
                break
        if out:
            return out
    return []


def web_search(query: str, *, limit: int = MAX_RESULTS) -> list[dict[str, str]]:
    """Return up to ``limit`` ``{title, snippet}`` hits. Never raises."""
    global _calls_made
    text = " ".join(str(query or "").split())[:120]
    if not text:
        return []
    if _calls_made >= MAX_CALLS_PER_PROCESS:
        logger.info("web_search budget exhausted (%s calls)", _calls_made)
        return []

    capped = max(1, min(int(limit), MAX_RESULTS))
    _calls_made += 1
    try:
        _throttle()
        brave_key = _api_key("BRAVE_SEARCH_API_KEY", "SEARCH_API_KEY")
        if brave_key:
            return _search_brave(text, brave_key, capped)
        serper_key = _api_key("SERPER_API_KEY")
        if serper_key:
            return _search_serper(text, serper_key, capped)
        return _search_duckduckgo(text, capped)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("web_search %r failed: %s", text[:40], exc)
        return []
    except Exception as exc:  # noqa: BLE001 - a search miss must never break the agent
        logger.warning("web_search %r unexpected error: %s", text[:40], exc)
        return []
