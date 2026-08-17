"""Account scaffold logic — keep in sync with scripts/scaffold_account.py."""
from __future__ import annotations

import json
import re
from typing import Any

from app.Services.GitHubService import GitHubError, GitHubService

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
ROLES = ("promo", "forward", "collector", "inspector", "full")
REGISTRY_PATH = "config/accounts.json"


def secret_name_for(account_id: str) -> str:
    if account_id == "elmira":
        return "TELEGRAM_SESSION_B64"
    return f"TELEGRAM_SESSION_B64_{account_id.upper()}"


def cron_for(account_id: str) -> str:
    minute = sum(ord(c) for c in account_id) % 50
    return f"{minute} */6 * * *"


def profile_modules(role: str) -> dict[str, Any]:
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
                "auto_join": False,
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
    return {
        "auto_reply": {"enabled": True},
        "channel_forward": {"enabled": True, "auto_join": False, "routes": []},
        "digest": {"enabled": True},
        "promo_spread": {
            "enabled": True,
            "dry_run": True,
            "paused": False,
            "mode": "forward",
            "auto_join": False,
            "routes": [],
        },
        "link_harvest": {"enabled": False},
        "group_inspect": {"enabled": False},
    }


def workflow_yaml(account_id: str, session_name: str, secret: str, cron: str) -> str:
    return f"""# Auto-scaffolded by admin-bot / scripts/scaffold_account.py
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
"""


def validate_account_id(account_id: str) -> str | None:
    aid = account_id.strip().lower()
    if not ID_RE.match(aid):
        return None
    return aid


def validate_role(role: str) -> str | None:
    r = role.strip().lower()
    return r if r in ROLES else None


def validate_phone(phone: str) -> str | None:
    p = phone.strip().replace(" ", "")
    if re.fullmatch(r"\+[1-9]\d{7,14}", p):
        return p
    return None


class AccountScaffoldService:
    def __init__(self, github: GitHubService) -> None:
        self.github = github

    async def list_registry_accounts(self) -> list[dict[str, Any]]:
        data, _sha = await self.github.get_json(REGISTRY_PATH)
        rows = data.get("accounts") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []
        return [r for r in rows if isinstance(r, dict)]

    async def scaffold(
        self,
        *,
        account_id: str,
        role: str,
        label: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        aid = validate_account_id(account_id)
        if not aid:
            raise GitHubError("invalid account_id")
        role_ok = validate_role(role)
        if not role_ok:
            raise GitHubError("invalid role")

        registry, _sha = await self.github.get_json(REGISTRY_PATH)
        rows = registry.setdefault("accounts", [])
        if not isinstance(rows, list):
            raise GitHubError("accounts.json invalid")

        existing = next((r for r in rows if r.get("id") == aid), None)
        if existing and not force:
            raise GitHubError(f"account already exists: {aid}")

        session_name = aid
        secret = secret_name_for(aid)
        human_label = (label or "").strip() or f"{aid} ({role_ok})"
        workflow_name = f"run-account-{aid}.yml"
        profile_path = f"config/accounts/{aid}.json"
        workflow_path = f".github/workflows/{workflow_name}"
        cron = cron_for(aid)

        profile = {
            "id": aid,
            "label": human_label,
            "session_name": session_name,
            "modules": profile_modules(role_ok),
        }
        entry = {
            "id": aid,
            "label": human_label,
            "enabled": False,
            "workflow": workflow_name,
            "session_name": session_name,
            "session_secret": secret,
            "profile": profile_path,
        }
        if existing:
            rows[rows.index(existing)] = entry
        else:
            rows.append(entry)

        files = {
            REGISTRY_PATH: json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
            profile_path: json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
            workflow_path: workflow_yaml(aid, session_name, secret, cron),
        }
        commit = await self.github.commit_files(
            files,
            f"chore(accounts): scaffold {aid} via admin-bot",
        )
        return {
            "account_id": aid,
            "role": role_ok,
            "label": human_label,
            "session_name": session_name,
            "session_secret": secret,
            "workflow": workflow_name,
            "profile": profile_path,
            "commit": commit,
        }
