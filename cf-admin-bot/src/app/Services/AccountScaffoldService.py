"""Account scaffold logic — keep in sync with scripts/scaffold_account.py."""
from __future__ import annotations

import json
import re
from typing import Any

from app.Services.GitHubService import GitHubError, GitHubService

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
ROLES = ("promo", "forward", "collector", "inspector", "full")
REGISTRY_PATH = "config/accounts.json"
ROLE_FA = {
    "promo": "تبلیغ",
    "forward": "فوروارد",
    "collector": "کالکتور",
    "inspector": "اینسپکتور",
    "full": "کامل",
}
LABEL_MAX_LEN = 64


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


def validate_label(label: str) -> str | None:
    text = " ".join((label or "").strip().split())
    if not text or len(text) > LABEL_MAX_LEN:
        return None
    if any(ch in text for ch in "\n\r\t"):
        return None
    return text


def suggest_label(account_id: str, role: str, *, index: int = 1) -> str:
    fa = ROLE_FA.get(role, role)
    return f"{fa} #{max(1, int(index))} — {account_id}"


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

    async def remove(self, account_id: str) -> dict[str, Any]:
        """Remove account from GitHub registry + profile + workflow (best-effort)."""
        aid = validate_account_id(account_id)
        if not aid:
            raise GitHubError("invalid account_id")

        registry, _sha = await self.github.get_json(REGISTRY_PATH)
        rows = registry.get("accounts") if isinstance(registry, dict) else None
        if not isinstance(rows, list):
            raise GitHubError("accounts.json invalid")

        existing = next((r for r in rows if r.get("id") == aid), None)
        workflow_name = (
            str(existing.get("workflow"))
            if existing and existing.get("workflow")
            else f"run-account-{aid}.yml"
        )
        profile_path = (
            str(existing.get("profile"))
            if existing and existing.get("profile")
            else f"config/accounts/{aid}.json"
        )
        secret = (
            str(existing.get("session_secret"))
            if existing and existing.get("session_secret")
            else secret_name_for(aid)
        )
        workflow_path = f".github/workflows/{workflow_name}"

        if existing:
            registry["accounts"] = [r for r in rows if r.get("id") != aid]
        else:
            registry["accounts"] = rows

        changes: dict[str, dict[str, str | None]] = {
            REGISTRY_PATH: {
                "content": json.dumps(registry, ensure_ascii=False, indent=2) + "\n"
            },
        }
        for path in (profile_path, workflow_path):
            try:
                await self.github.get_file_text(path)
                changes[path] = {"delete": True}
            except GitHubError as exc:
                if getattr(exc, "status", None) != 404:
                    raise

        commit = await self.github.commit_tree_changes(
            changes,
            f"chore(accounts): remove {aid} via admin-bot",
        )
        return {
            "account_id": aid,
            "session_secret": secret,
            "commit": commit,
            "removed_from_registry": bool(existing),
        }

    async def set_registry_enabled(
        self, account_id: str, *, enabled: bool
    ) -> dict[str, Any] | None:
        """Flip enabled flag in accounts.json (no-op if account missing)."""
        aid = validate_account_id(account_id)
        if not aid:
            raise GitHubError("invalid account_id")

        registry, _sha = await self.github.get_json(REGISTRY_PATH)
        rows = registry.get("accounts") if isinstance(registry, dict) else None
        if not isinstance(rows, list):
            raise GitHubError("accounts.json invalid")

        existing = next((r for r in rows if r.get("id") == aid), None)
        if not existing:
            return None
        if bool(existing.get("enabled")) is bool(enabled):
            return {"account_id": aid, "enabled": bool(enabled), "changed": False}

        existing["enabled"] = bool(enabled)
        commit = await self.github.commit_files(
            {
                REGISTRY_PATH: json.dumps(registry, ensure_ascii=False, indent=2)
                + "\n"
            },
            f"chore(accounts): {'enable' if enabled else 'disable'} {aid} via admin-bot",
        )
        return {
            "account_id": aid,
            "enabled": bool(enabled),
            "changed": True,
            "commit": commit,
        }

    async def update_label(self, account_id: str, label: str) -> dict[str, Any]:
        """Update human label in registry + profile (id unchanged)."""
        aid = validate_account_id(account_id)
        label_ok = validate_label(label)
        if not aid:
            raise GitHubError("invalid account_id")
        if not label_ok:
            raise GitHubError("invalid label")

        registry, _sha = await self.github.get_json(REGISTRY_PATH)
        rows = registry.get("accounts") if isinstance(registry, dict) else None
        if not isinstance(rows, list):
            raise GitHubError("accounts.json invalid")

        existing = next((r for r in rows if r.get("id") == aid), None)
        profile_path = (
            str(existing.get("profile"))
            if existing and existing.get("profile")
            else f"config/accounts/{aid}.json"
        )
        if existing:
            existing["label"] = label_ok

        files: dict[str, str] = {
            REGISTRY_PATH: json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        }
        try:
            profile, _ = await self.github.get_json(profile_path)
            if isinstance(profile, dict):
                profile["label"] = label_ok
                files[profile_path] = (
                    json.dumps(profile, ensure_ascii=False, indent=2) + "\n"
                )
        except GitHubError as exc:
            if getattr(exc, "status", None) != 404:
                raise

        commit = await self.github.commit_files(
            files,
            f"chore(accounts): rename label {aid} via admin-bot",
        )
        return {"account_id": aid, "label": label_ok, "commit": commit}

    async def update_role(
        self, account_id: str, role: str, *, label: str | None = None
    ) -> dict[str, Any]:
        """Rewrite profile modules for a new role; optionally set label."""
        aid = validate_account_id(account_id)
        role_ok = validate_role(role)
        if not aid:
            raise GitHubError("invalid account_id")
        if not role_ok:
            raise GitHubError("invalid role")

        label_ok = validate_label(label) if label is not None else None

        registry, _sha = await self.github.get_json(REGISTRY_PATH)
        rows = registry.get("accounts") if isinstance(registry, dict) else None
        if not isinstance(rows, list):
            raise GitHubError("accounts.json invalid")

        existing = next((r for r in rows if r.get("id") == aid), None)
        profile_path = (
            str(existing.get("profile"))
            if existing and existing.get("profile")
            else f"config/accounts/{aid}.json"
        )
        session_name = (
            str(existing.get("session_name"))
            if existing and existing.get("session_name")
            else aid
        )

        if existing and label_ok:
            existing["label"] = label_ok

        try:
            profile, _ = await self.github.get_json(profile_path)
            if not isinstance(profile, dict):
                profile = {}
        except GitHubError as exc:
            if getattr(exc, "status", None) != 404:
                raise
            profile = {}

        human = label_ok or str(profile.get("label") or "").strip() or (
            str(existing.get("label")) if existing else ""
        ) or f"{aid} ({role_ok})"
        profile = {
            "id": aid,
            "label": human,
            "session_name": str(profile.get("session_name") or session_name),
            "modules": profile_modules(role_ok),
        }
        if existing:
            existing["label"] = human

        files = {
            REGISTRY_PATH: json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
            profile_path: json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
        }
        commit = await self.github.commit_files(
            files,
            f"chore(accounts): set role {aid} -> {role_ok} via admin-bot",
        )
        return {
            "account_id": aid,
            "role": role_ok,
            "label": human,
            "profile": profile_path,
            "commit": commit,
        }

    def _profile_path_for(
        self, account_id: str, registry_row: dict[str, Any] | None
    ) -> str:
        if registry_row and registry_row.get("profile"):
            return str(registry_row.get("profile"))
        return f"config/accounts/{account_id}.json"

    async def get_profile(self, account_id: str) -> dict[str, Any]:
        aid = validate_account_id(account_id)
        if not aid:
            raise GitHubError("invalid account_id")
        registry, _ = await self.github.get_json(REGISTRY_PATH)
        rows = registry.get("accounts") if isinstance(registry, dict) else None
        existing = None
        if isinstance(rows, list):
            existing = next((r for r in rows if r.get("id") == aid), None)
        path = self._profile_path_for(
            aid, existing if isinstance(existing, dict) else None
        )
        profile, _ = await self.github.get_json(path)
        if not isinstance(profile, dict):
            raise GitHubError("profile invalid")
        return {"path": path, "profile": profile}

    async def patch_profile_modules(
        self, account_id: str, module: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        """Shallow-merge keys into profile.modules[module]."""
        aid = validate_account_id(account_id)
        if not aid:
            raise GitHubError("invalid account_id")
        mod = (module or "").strip()
        if not mod or not isinstance(patch, dict) or not patch:
            raise GitHubError("invalid profile patch")

        info = await self.get_profile(aid)
        path = str(info["path"])
        profile = dict(info["profile"])
        modules = profile.get("modules")
        if not isinstance(modules, dict):
            modules = {}
            profile["modules"] = modules
        current = modules.get(mod)
        if not isinstance(current, dict):
            current = {}
        merged = dict(current)
        merged.update(patch)
        modules[mod] = merged

        commit = await self.github.commit_files(
            {path: json.dumps(profile, ensure_ascii=False, indent=2) + "\n"},
            f"chore(accounts): patch {aid}.{mod} via admin-bot",
        )
        return {
            "account_id": aid,
            "module": mod,
            "patch": patch,
            "merged": merged,
            "commit": commit,
            "profile_path": path,
        }
