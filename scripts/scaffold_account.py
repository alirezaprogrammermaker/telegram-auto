"""Scaffold a new multi-account identity (registry + profile + GHA caller).

Usage:
  python scripts/scaffold_account.py promo2 --role promo --label "Promo worker 2"
  python scripts/scaffold_account.py forward2 --role forward
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "config" / "accounts.json"
ACCOUNTS_DIR = ROOT / "config" / "accounts"
WORKFLOWS = ROOT / ".github" / "workflows"

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


def secret_name_for(account_id: str) -> str:
    if account_id == "elmira":
        return "TELEGRAM_SESSION_B64"
    return f"TELEGRAM_SESSION_B64_{account_id.upper()}"


def cron_for(account_id: str) -> str:
    # Stagger within the hour so many accounts don't start together.
    minute = sum(ord(c) for c in account_id) % 50
    return f"{minute} */6 * * *"


def linkdir_crons(account_id: str) -> list[str]:
    base = sum(ord(c) for c in account_id) % 50
    hours = (6, 11, 16, 21)
    return [f"{(base + i * 7) % 60} {h} * * *" for i, h in enumerate(hours)]


def workflow_name_for(role: str, account_id: str) -> str:
    if role == "linkdir":
        return f"run-linkdir-{account_id}.yml"
    return f"run-account-{account_id}.yml"


def profile_modules(role: str) -> dict:
    if role == "promo":
        return {
            "auto_reply": {"enabled": True},
            "channel_forward": {"enabled": False},
            "digest": {"enabled": False},
            "promo_spread": {
                "enabled": True,
                "dry_run": True,
                "paused": False,
                "mode": "forward",
                "auto_join": True,
                "routes": [],
            },
            "link_harvest": {"enabled": False},
            "group_inspect": {"enabled": False},
        }
    if role == "forward":
        return {
            "auto_reply": {"enabled": True},
            "channel_forward": {"enabled": True, "auto_join": False, "routes": []},
            "digest": {"enabled": True},
            "promo_spread": {"enabled": False},
            "link_harvest": {"enabled": False},
            "group_inspect": {"enabled": False},
        }
    if role == "collector":
        return {
            "auto_reply": {"enabled": True},
            "channel_forward": {"enabled": False},
            "digest": {"enabled": False},
            "promo_spread": {"enabled": False},
            "link_harvest": {
                "enabled": True,
                "paused": False,
                "join_directories": True,
                "catch_up_limit": 40,
                "directories": [],
            },
            "group_inspect": {"enabled": False},
        }
    if role == "inspector":
        return {
            "auto_reply": {"enabled": True},
            "channel_forward": {"enabled": False},
            "digest": {"enabled": False},
            "promo_spread": {"enabled": False},
            "link_harvest": {"enabled": False},
            "group_inspect": {
                "enabled": True,
                "dry_run": True,
                "paused": False,
                "daily_join_budget": 4,
                "delay_min_seconds": 1800,
                "delay_max_seconds": 10800,
                "leave_after": True,
                "timezone": "Asia/Tehran",
            },
        }
    if role == "linkdir":
        return {
            "auto_reply": {"enabled": False},
            "channel_forward": {"enabled": False},
            "digest": {"enabled": False},
            "promo_spread": {"enabled": False},
            "link_harvest": {"enabled": False},
            "group_inspect": {"enabled": False},
            "linkdir_collect": {
                "enabled": True,
                "paused": False,
                "steps": "search,snowball,rerank",
            },
        }
    # full
    return {
        "auto_reply": {"enabled": True},
        "channel_forward": {"enabled": True, "auto_join": False, "routes": []},
        "digest": {"enabled": True},
        "promo_spread": {
            "enabled": True,
            "dry_run": True,
            "paused": False,
            "mode": "forward",
            "auto_join": True,
            "routes": [],
        },
        "link_harvest": {"enabled": False},
        "group_inspect": {"enabled": False},
    }


def workflow_yaml(account_id: str, session_name: str, secret: str, cron: str) -> str:
    return f"""# Auto-scaffolded by scripts/scaffold_account.py
# Session secret: {secret}
# Profile: config/accounts/{account_id}.json

name: run-account-{account_id}

on:
  schedule:
    - cron: "{cron}"
  workflow_dispatch:
    inputs:
      max_runtime_seconds:
        description: "Seconds to run before clean exit (default 5h55m)"
        required: false
        default: "21300"

permissions:
  contents: read

jobs:
  {account_id}:
    uses: ./.github/workflows/run-account.yml
    with:
      account_id: {account_id}
      session_name: {session_name}
      max_runtime_seconds: ${{{{ inputs.max_runtime_seconds || '21300' }}}}
    secrets:
      API_ID: ${{{{ secrets.API_ID }}}}
      API_HASH: ${{{{ secrets.API_HASH }}}}
      ADMIN_PASSWORD: ${{{{ secrets.ADMIN_PASSWORD }}}}
      TELEGRAM_SESSION_B64: ${{{{ secrets.{secret} }}}}
      ADMIN_IDS: ${{{{ secrets.ADMIN_IDS }}}}
      ADMIN_BOT_BRIDGE_URL: ${{{{ secrets.ADMIN_BOT_BRIDGE_URL }}}}
      ADMIN_BOT_BRIDGE_TOKEN: ${{{{ secrets.ADMIN_BOT_BRIDGE_TOKEN }}}}
"""


def linkdir_workflow_yaml(account_id: str, session_name: str, secret: str) -> str:
    cron_block = "\n".join(
        f'    - cron: "{c}"' for c in linkdir_crons(account_id)
    )
    return f"""# Auto-scaffolded by scripts/scaffold_account.py
# Linkdir discovery batches — not a long-running bot.

name: run-linkdir-{account_id}

on:
  schedule:
{cron_block}
  workflow_dispatch:
    inputs:
      steps:
        description: "Comma steps: search,snowball,rerank"
        required: false
        type: string
        default: ""

permissions:
  contents: read

jobs:
  {account_id}:
    uses: ./.github/workflows/run-linkdir.yml
    with:
      account_id: {account_id}
      session_name: {session_name}
      steps: ${{{{ inputs.steps || '' }}}}
    secrets:
      API_ID: ${{{{ secrets.API_ID }}}}
      API_HASH: ${{{{ secrets.API_HASH }}}}
      TELEGRAM_SESSION_B64: ${{{{ secrets.{secret} }}}}
      ADMIN_BOT_BRIDGE_URL: ${{{{ secrets.ADMIN_BOT_BRIDGE_URL }}}}
      ADMIN_BOT_BRIDGE_TOKEN: ${{{{ secrets.ADMIN_BOT_BRIDGE_TOKEN }}}}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Scaffold a Telegram account for GHA")
    parser.add_argument("account_id", help="lowercase id, e.g. promo2")
    parser.add_argument(
        "--role",
        choices=["promo", "forward", "full", "collector", "inspector", "linkdir"],
        default="promo",
        help="Module profile template",
    )
    parser.add_argument("--label", default="", help="Human label")
    parser.add_argument(
        "--session-name",
        default="",
        help="Telethon session stem (default = account_id)",
    )
    parser.add_argument(
        "--enable",
        action="store_true",
        help="Set enabled=true in registry (default: false until login)",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    args = parser.parse_args()

    account_id = args.account_id.strip().lower()
    if not ID_RE.match(account_id):
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": "account_id must match ^[a-z][a-z0-9_]{1,31}$",
                }
            )
        )
        return 1

    session_name = (args.session_name or account_id).strip()
    secret = secret_name_for(account_id)
    label = args.label.strip() or f"{account_id} ({args.role})"
    workflow_name = workflow_name_for(args.role, account_id)
    profile_path = ACCOUNTS_DIR / f"{account_id}.json"
    workflow_path = WORKFLOWS / workflow_name

    if not REGISTRY.exists():
        print(json.dumps({"status": "failed", "error": "missing config/accounts.json"}))
        return 1

    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    rows = data.setdefault("accounts", [])
    if not isinstance(rows, list):
        print(json.dumps({"status": "failed", "error": "accounts.json invalid"}))
        return 1

    existing = next((r for r in rows if r.get("id") == account_id), None)
    if existing and not args.force:
        print(
            json.dumps(
                {
                    "status": "exists",
                    "account_id": account_id,
                    "error": "already in registry — pass --force to overwrite files",
                }
            )
        )
        return 1

    if (profile_path.exists() or workflow_path.exists()) and not args.force and not existing:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": f"files already exist for {account_id} — use --force",
                }
            )
        )
        return 1

    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    WORKFLOWS.mkdir(parents=True, exist_ok=True)

    profile = {
        "id": account_id,
        "label": label,
        "session_name": session_name,
        "modules": profile_modules(args.role),
    }
    profile_path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    cron = cron_for(account_id)
    if args.role == "linkdir":
        wf_body = linkdir_workflow_yaml(account_id, session_name, secret)
    else:
        wf_body = workflow_yaml(account_id, session_name, secret, cron)
    workflow_path.write_text(wf_body, encoding="utf-8")

    entry = {
        "id": account_id,
        "label": label,
        "enabled": bool(args.enable),
        "workflow": workflow_name,
        "session_name": session_name,
        "session_secret": secret,
        "profile": f"config/accounts/{account_id}.json",
    }
    if existing:
        idx = rows.index(existing)
        rows[idx] = entry
    else:
        rows.append(entry)

    REGISTRY.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = {
        "status": "scaffolded",
        "account_id": account_id,
        "role": args.role,
        "enabled": entry["enabled"],
        "session_name": session_name,
        "session_secret": secret,
        "workflow": workflow_name,
        "profile": str(profile_path.relative_to(ROOT)).replace("\\", "/"),
        "cron": cron,
        "next": [
            "Commit + push these files to master",
            f".\\manage.ps1 login-send -Account {account_id} -Phone +98...",
            "Set LOGIN_OTP (and LOGIN_2FA if needed), then login-complete",
            f"Optionally: .\\manage.ps1 account-enable -Account {account_id}",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
