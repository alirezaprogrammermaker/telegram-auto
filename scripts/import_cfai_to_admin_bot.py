#!/usr/bin/env python3
"""Import local data/pool/cloudflare_ai.json into jellymanagerbot D1 via bridge."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from app.bridge_client import bridge_configured, bridge_request  # noqa: E402


def main() -> int:
    store_path = ROOT / "data" / "pool" / "cloudflare_ai.json"
    if not store_path.is_file():
        print(f"Store not found: {store_path}", file=sys.stderr)
        return 1
    if not bridge_configured():
        print(
            "Set ADMIN_BOT_BRIDGE_URL and ADMIN_BOT_BRIDGE_TOKEN in .env",
            file=sys.stderr,
        )
        return 1

    store = json.loads(store_path.read_text(encoding="utf-8"))
    accounts = store.get("accounts") or []
    print(f"Importing {len(accounts)} account(s) from {store_path.name}...")

    result = bridge_request("POST", "/internal/cfai/import", payload={"store": store})
    if not result or not result.get("ok"):
        print(f"Import failed: {result}", file=sys.stderr)
        return 1

    summary = result.get("summary") or {}
    print(
        "OK — "
        f"usable={summary.get('usable_accounts', '?')}/"
        f"{summary.get('total_accounts', '?')} "
        f"model={summary.get('default_model', '?')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
