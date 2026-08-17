from __future__ import annotations

from lang.fa.messages import MESSAGES


def __(key: str, **kwargs) -> str:
    """Laravel-style translator. Missing keys return the key itself."""
    template = MESSAGES.get(key, key)
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except Exception:
        return template
