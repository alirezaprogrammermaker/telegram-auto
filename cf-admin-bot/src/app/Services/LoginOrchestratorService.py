"""Orchestrates GHA login from the admin bot (bridge + workflow dispatch)."""
from __future__ import annotations

import asyncio
from typing import Any

from app.Models.Account import Account
from app.Models.LoginSession import LoginSession, mask_phone
from app.Services.AccountScaffoldService import (
    AccountScaffoldService,
    validate_account_id,
    validate_phone,
    validate_role,
)
from app.Services.GitHubService import GitHubError, GitHubService

LOGIN_WORKFLOW = "login-account.yml"


class LoginOrchestratorService:
    def __init__(self, db, github: GitHubService) -> None:
        self.db = db
        self.github = github
        self.scaffold = AccountScaffoldService(github)

    async def list_accounts_view(self) -> list[dict[str, Any]]:
        try:
            registry = await self.scaffold.list_registry_accounts()
        except GitHubError:
            registry = []
        local_rows = await Account.all_ordered(self.db)
        local_map = {str(a.get("id")): a for a in local_rows}
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in registry:
            aid = str(row.get("id") or "")
            if not aid:
                continue
            seen.add(aid)
            local = local_map.get(aid)
            out.append(
                {
                    "id": aid,
                    "label": row.get("label") or aid,
                    "enabled": bool(row.get("enabled")),
                    "session_secret": row.get("session_secret"),
                    "status": (local.get("status") if local else "scaffolded"),
                    "phone_mask": (local.get("phone_mask") if local else ""),
                }
            )
        for aid, local in local_map.items():
            if aid in seen:
                continue
            out.append(
                {
                    "id": aid,
                    "label": local.get("label") or aid,
                    "enabled": bool(local.get("enabled")),
                    "session_secret": local.get("session_secret"),
                    "status": local.get("status"),
                    "phone_mask": local.get("phone_mask") or "",
                }
            )
        return out

    async def start_add(
        self,
        *,
        account_id: str,
        role: str,
        phone: str,
        created_by: int,
        force: bool = False,
    ) -> LoginSession:
        aid = validate_account_id(account_id)
        role_ok = validate_role(role)
        phone_ok = validate_phone(phone)
        if not aid or not role_ok or not phone_ok:
            raise ValueError("invalid_input")

        session = await LoginSession.create_new(
            self.db,
            account_id=aid,
            role=role_ok,
            created_by=created_by,
            phone=phone_ok,
            status="scaffolding",
        )

        try:
            result = await self.scaffold.scaffold(
                account_id=aid, role=role_ok, force=force
            )
        except GitHubError as exc:
            await session.touch(
                self.db, status="failed", error=str(exc), clear_secrets=True
            )
            raise

        await Account.upsert_row(
            self.db,
            {
                "id": aid,
                "label": result["label"],
                "role": role_ok,
                "enabled": 0,
                "session_name": result["session_name"],
                "session_secret": result["session_secret"],
                "phone_mask": mask_phone(phone_ok),
                "status": "logging_in",
                "last_error": None,
            },
        )

        # Give GitHub a moment so login-account checkout sees the new registry entry.
        await asyncio.sleep(3)

        await session.touch(self.db, status="sending", extend_ttl=True)
        await self.github.dispatch_workflow(
            LOGIN_WORKFLOW,
            {"action": "send", "account_id": aid},
        )
        run = await self.github.latest_workflow_run(LOGIN_WORKFLOW)
        run_id = str(run.get("id")) if run and run.get("id") is not None else None
        return await session.touch(
            self.db,
            status="awaiting_otp",
            github_run_id=run_id,
            extend_ttl=True,
        )

    async def start_login_existing(
        self,
        *,
        account_id: str,
        phone: str,
        created_by: int,
    ) -> LoginSession:
        aid = validate_account_id(account_id)
        phone_ok = validate_phone(phone)
        if not aid or not phone_ok:
            raise ValueError("invalid_input")

        registry = await self.scaffold.list_registry_accounts()
        row = next((r for r in registry if r.get("id") == aid), None)
        if not row:
            raise ValueError("account_missing")

        session = await LoginSession.create_new(
            self.db,
            account_id=aid,
            role=None,
            created_by=created_by,
            phone=phone_ok,
            status="sending",
        )
        await Account.upsert_row(
            self.db,
            {
                "id": aid,
                "label": row.get("label") or aid,
                "role": None,
                "enabled": 1 if row.get("enabled") else 0,
                "session_name": row.get("session_name") or aid,
                "session_secret": row.get("session_secret"),
                "phone_mask": mask_phone(phone_ok),
                "status": "logging_in",
                "last_error": None,
            },
        )
        await self.github.dispatch_workflow(
            LOGIN_WORKFLOW,
            {"action": "send", "account_id": aid},
        )
        run = await self.github.latest_workflow_run(LOGIN_WORKFLOW)
        run_id = str(run.get("id")) if run and run.get("id") is not None else None
        return await session.touch(
            self.db,
            status="awaiting_otp",
            github_run_id=run_id,
            extend_ttl=True,
        )

    async def submit_otp(self, session: LoginSession, otp: str) -> LoginSession:
        code = otp.strip().replace(" ", "")
        if not code.isdigit() or not (4 <= len(code) <= 8):
            raise ValueError("invalid_otp")
        return await session.touch(
            self.db, otp=code, status="awaiting_otp", extend_ttl=True
        )

    async def submit_2fa(self, session: LoginSession, password: str) -> LoginSession:
        pwd = password.strip()
        if not pwd:
            raise ValueError("invalid_2fa")
        return await session.touch(
            self.db, twofa=pwd, status="awaiting_2fa", extend_ttl=True
        )

    async def dispatch_complete(self, session: LoginSession) -> LoginSession:
        aid = str(session.get("account_id"))
        await session.touch(self.db, status="completing", extend_ttl=True)
        await self.github.dispatch_workflow(
            LOGIN_WORKFLOW,
            {"action": "complete", "account_id": aid},
        )
        run = await self.github.latest_workflow_run(LOGIN_WORKFLOW)
        run_id = str(run.get("id")) if run and run.get("id") is not None else None
        return await session.touch(self.db, github_run_id=run_id, extend_ttl=True)

    async def refresh_run_status(self, session: LoginSession) -> dict[str, Any]:
        run_id = session.get("github_run_id")
        if not run_id:
            return {"status": "unknown"}
        run = await self.github.get_run(run_id)
        conclusion = run.get("conclusion")
        status = run.get("status")
        result = {
            "status": status,
            "conclusion": conclusion,
            "html_url": run.get("html_url"),
            "run_id": run_id,
        }
        if status == "completed":
            aid = str(session.get("account_id"))
            existing = await Account.find(self.db, aid)
            if conclusion == "success":
                await session.touch(
                    self.db, status="done", clear_secrets=True, error=None
                )
                await Account.upsert_row(
                    self.db,
                    {
                        "id": aid,
                        "label": (existing.get("label") if existing else aid),
                        "role": (existing.get("role") if existing else None),
                        "enabled": int(existing.get("enabled") or 0) if existing else 0,
                        "session_name": (
                            existing.get("session_name") if existing else aid
                        ),
                        "session_secret": (
                            existing.get("session_secret") if existing else None
                        ),
                        "phone_mask": (
                            existing.get("phone_mask") if existing else ""
                        ),
                        "status": "ready",
                        "last_error": None,
                    },
                )
                result["login"] = "done"
            else:
                await session.touch(
                    self.db,
                    status="failed",
                    error=f"workflow_{conclusion or 'failed'}",
                )
                await Account.upsert_row(
                    self.db,
                    {
                        "id": aid,
                        "label": (existing.get("label") if existing else aid),
                        "role": (existing.get("role") if existing else None),
                        "enabled": int(existing.get("enabled") or 0) if existing else 0,
                        "session_name": (
                            existing.get("session_name") if existing else aid
                        ),
                        "session_secret": (
                            existing.get("session_secret") if existing else None
                        ),
                        "phone_mask": (
                            existing.get("phone_mask") if existing else ""
                        ),
                        "status": "error",
                        "last_error": f"workflow_{conclusion or 'failed'}",
                    },
                )
                result["login"] = "failed"
        return result

    async def cancel(self, session: LoginSession) -> LoginSession:
        return await session.touch(
            self.db, status="cancelled", clear_secrets=True, error="cancelled"
        )

    async def bridge_payload(
        self, account_id: str, action: str
    ) -> dict[str, Any] | None:
        session = await LoginSession.for_bridge(self.db, account_id, action=action)
        if not session:
            return None
        if action == "send":
            phone = session.get("phone")
            if not phone:
                return None
            return {"ok": True, "phone": phone, "account_id": account_id}
        if action == "complete":
            otp = session.get("otp")
            if not otp:
                return None
            payload: dict[str, Any] = {
                "ok": True,
                "otp": otp,
                "account_id": account_id,
            }
            twofa = session.get("twofa")
            if twofa:
                payload["twofa"] = twofa
            return payload
        return None
