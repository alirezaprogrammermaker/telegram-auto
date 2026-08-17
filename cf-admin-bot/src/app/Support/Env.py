from __future__ import annotations


def env_str(env, name: str, default: str = "") -> str:
    try:
        val = getattr(env, name, None)
    except Exception:
        val = None
    if val is None:
        return default
    return str(val)
