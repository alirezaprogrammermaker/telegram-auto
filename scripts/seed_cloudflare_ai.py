#!/usr/bin/env python3
"""Seed Cloudflare AI accounts from YAML/JSON without hardcoding secrets in source."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.cloudflare_ai.store import CloudflareAIStore  # noqa: E402


def _load_rows(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise SystemExit(
                "PyYAML is required for YAML seed files: pip install pyyaml"
            ) from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)

    if isinstance(data, dict) and "accounts" in data:
        rows = data["accounts"]
    elif isinstance(data, list):
        rows = data
    else:
        raise ValueError("seed file must contain a list or {accounts: [...]}")

    if not isinstance(rows, list):
        raise ValueError("accounts must be a list")
    return [row for row in rows if isinstance(row, dict)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed Cloudflare AI accounts store")
    parser.add_argument(
        "--file",
        help="YAML/JSON file with accounts (name, account_id, api_key/api_token)",
    )
    parser.add_argument(
        "--store",
        help="Optional override path for cloudflare_ai.json",
    )
    args = parser.parse_args()

    seed_file = args.file or os.environ.get("CLOUDFLARE_AI_SEED_FILE", "").strip()
    if not seed_file:
        print(
            "Provide --file or set CLOUDFLARE_AI_SEED_FILE to a YAML/JSON config.",
            file=sys.stderr,
        )
        return 2

    path = Path(seed_file)
    if not path.is_file():
        print(f"Seed file not found: {path}", file=sys.stderr)
        return 2

    rows = _load_rows(path)
    store = CloudflareAIStore(path=args.store) if args.store else CloudflareAIStore()

    default_model = None
    if path.suffix.lower() in {".yaml", ".yml"}:
        import yaml  # type: ignore

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            alias = data.get("default_model")
            models = data.get("models") or {}
            if alias and isinstance(models, dict) and alias in models:
                default_model = str(models[alias])
            elif isinstance(alias, str) and alias.startswith("@cf/"):
                default_model = alias

    added = store.upsert_accounts(rows)
    if default_model:
        store.set_default_model(default_model)

    print(f"Seeded {added} new account(s) into {store.path}")
    if default_model:
        print(f"Default model: {default_model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
