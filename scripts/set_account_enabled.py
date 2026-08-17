"""Toggle enabled flag in config/accounts.json."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "config" / "accounts.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("account_id")
    parser.add_argument("--enabled", choices=["true", "false"], required=True)
    args = parser.parse_args()

    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    rows = data.get("accounts") or []
    hit = next((r for r in rows if r.get("id") == args.account_id), None)
    if not hit:
        print(f"unknown account: {args.account_id}", file=sys.stderr)
        return 1
    hit["enabled"] = args.enabled == "true"
    REGISTRY.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"id": args.account_id, "enabled": hit["enabled"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
