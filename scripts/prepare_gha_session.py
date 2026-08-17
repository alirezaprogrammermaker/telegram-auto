"""Restore Telethon session + seed data dir for a GitHub Actions account job."""
from __future__ import annotations

import base64
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.paths import data_dir, data_path, ensure_data_dir  # noqa: E402

_LEGACY_FILES = (
    "admins.json",
    "modules.runtime.json",
    "forward_state.json",
    "publish_queue.json",
    "dedup.json",
    "stats.json",
    "promo_queue.json",
    "promo_safety.json",
)


def _migrate_legacy_flat_data(account_data: Path) -> None:
    """Move pre-multi-account files from data/*.json into data/<account>/."""
    legacy_root = ROOT / "data"
    if account_data.resolve() == legacy_root.resolve():
        return
    if not legacy_root.is_dir():
        return
    for name in _LEGACY_FILES:
        src = legacy_root / name
        dst = account_data / name
        if src.exists() and src.is_file() and not dst.exists():
            shutil.move(str(src), str(dst))
            print(f"migrated legacy {name} → {dst}")


def _account_enabled(account: str) -> bool | None:
    """Return False if registry explicitly disables the account; None if unknown."""
    registry = ROOT / "config" / "accounts.json"
    if not registry.exists():
        return None
    try:
        rows = json.loads(registry.read_text(encoding="utf-8")).get("accounts") or []
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    for row in rows:
        if isinstance(row, dict) and str(row.get("id")) == account:
            return bool(row.get("enabled", True))
    return None


def _write_skip(skip: bool) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"skip={'true' if skip else 'false'}\n")
    print(f"skip={'true' if skip else 'false'}")


def main() -> int:
    account = (os.environ.get("ACCOUNT_ID") or "default").strip()
    session_name = (os.environ.get("SESSION_NAME") or "easy_seen").strip() or "easy_seen"
    raw = (os.environ.get("TELEGRAM_SESSION_B64") or "").strip()

    data = ensure_data_dir()
    _migrate_legacy_flat_data(data)
    admins = data_path("admins.json")
    if not admins.exists():
        admins.write_text('{"admin_ids":[]}\n', encoding="utf-8")

    enabled = _account_enabled(account)
    if enabled is False:
        print(f"::warning::Account {account} is disabled in config/accounts.json — skipping")
        _write_skip(True)
        return 0

    if not raw:
        print(f"::warning::No session secret for account={account} — job will skip run")
        _write_skip(True)
        return 0

    session = ROOT / f"{session_name}.session"
    session.write_bytes(base64.b64decode(raw))
    print(f"account={account} session={session.name} bytes={session.stat().st_size} data={data}")
    _write_skip(False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
