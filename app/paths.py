"""Filesystem paths — account-aware data isolation for multi-account GHA."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def account_id() -> str:
    raw = (os.environ.get("ACCOUNT_ID") or "").strip()
    return raw or "default"


def data_dir() -> Path:
    """Per-account state directory (queues, last_seen, runtime modules, …).

    Override with DATA_DIR, otherwise data/<ACCOUNT_ID> when ACCOUNT_ID is set,
    else plain data/ (backward compatible for local/dev).
    """
    override = (os.environ.get("DATA_DIR") or "").strip()
    if override:
        path = Path(override)
        if not path.is_absolute():
            path = ROOT / path
        return path

    acc = account_id()
    if acc and acc != "default":
        return ROOT / "data" / acc
    return ROOT / "data"


def data_path(*parts: str) -> Path:
    return data_dir().joinpath(*parts)


def lock_file_path() -> Path:
    override = (os.environ.get("LOCK_FILE") or "").strip()
    if override:
        path = Path(override)
        return path if path.is_absolute() else ROOT / path
    acc = account_id()
    if acc and acc != "default":
        return ROOT / f"telegram_auto.{acc}.lock"
    return ROOT / "telegram_auto.lock"


def runtime_modules_path() -> Path:
    return data_path("modules.runtime.json")


def ensure_data_dir() -> Path:
    path = data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path
