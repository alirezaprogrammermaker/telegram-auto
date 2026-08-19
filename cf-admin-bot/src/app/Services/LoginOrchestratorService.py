"""Orchestrates GHA login from the admin bot (bridge + workflow dispatch)."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from app.Models.LoginSession import LoginSession
from app.Services.AccountScaffoldService import (
    AccountScaffoldService,
    validate_account_id,
    validate_phone,
    validate_role,
)
from app.Services.AccountService import AccountConflictError, AccountService
from app.Services.GitHubService import GitHubError, GitHubService
from app.Services.RunOrchestratorService import RunOrchestratorService

LOGIN_WORKFLOW = "login-account.yml"


class LoginOrchestratorService:
    def __init__(self, db, github: GitHubService) -> None:
        self.db = db
        self.github = github
        self.scaffold = AccountScaffoldService(github)
        self.accounts = AccountService(db)

    async def _dispatch_and_track(
        self, session: LoginSession, *, action: str, account_id: str, status: str
    ) -> LoginSession:
        previous_run_id = str(session.get("github_run_id") or "")
        started = time.time()
        await self.github.dispatch_workflow(
            LOGIN_WORKFLOW,
            {"action": action, "account_id": account_id},
        )
        run = None
        for attempt in range(10):
            candidate = await self.github.latest_workflow_run(LOGIN_WORKFLOW)
            if candidate and candidate.get("id") is not None:
                rid = str(candidate.get("id"))
                created = str(candidate.get("created_at") or "")
                fresh_enough = True
                try:
                    from datetime import datetime

                    created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    fresh_enough = created_dt.timestamp() >= started - 5
                except Exception:
                    fresh_enough = attempt >= 2
                if rid != previous_run_id and fresh_enough:
                    run = candidate
                    break
            await asyncio.sleep(1.5 * (1.2**attempt))
        if run is None:
            run = await self.github.wait_for_workflow_run(
                LOGIN_WORKFLOW, not_before_epoch=started
            )
            if run and str(run.get("id") or "") == previous_run_id:
                run = None
        run_id = str(run.get("id")) if run and run.get("id") is not None else None
        return await session.touch(
            self.db,
            status=status,
            github_run_id=run_id,
            extend_ttl=True,
        )

    async def list_accounts_view(self, user_id: int) -> list[dict[str, Any]]:
        """Only accounts owned by this admin (D1)."""
        return await self.accounts.list_for_user(user_id)

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

        await self.accounts.assert_phone_available(phone_ok, except_account_id=aid)
        await self.accounts.assert_key_available_for_user(created_by, aid)

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
            if "already exists" in str(exc).lower() and not force:
                rows = await self.scaffold.list_registry_accounts()
                row = next((r for r in rows if r.get("id") == aid), None)
                if not row:
                    await session.touch(
                        self.db, status="failed", error=str(exc), clear_secrets=True
                    )
                    raise
                result = {
                    "account_id": aid,
                    "role": role_ok,
                    "label": row.get("label") or aid,
                    "session_name": row.get("session_name") or aid,
                    "session_secret": row.get("session_secret"),
                    "workflow": row.get("workflow"),
                    "profile": row.get("profile"),
                    "commit": {"sha": "existing"},
                }
            else:
                await session.touch(
                    self.db, status="failed", error=str(exc), clear_secrets=True
                )
                raise

        commit = result.get("commit") if isinstance(result.get("commit"), dict) else {}
        try:
            await self.accounts.sync_from_login(
                user_id=created_by,
                account_id=aid,
                label=str(result.get("label") or aid),
                role=role_ok,
                phone_e164=phone_ok,
                enabled=0,
                session_name=str(result.get("session_name") or aid),
                session_secret=result.get("session_secret"),
                workflow=result.get("workflow"),
                profile_path=result.get("profile"),
                github_commit_sha=(commit or {}).get("sha"),
                status="logging_in",
            )
        except PermissionError:
            await session.touch(
                self.db,
                status="failed",
                error="account_owned_by_other",
                clear_secrets=True,
            )
            raise AccountConflictError("account_owned_by_other", account_id=aid)

        await asyncio.sleep(3)
        await session.touch(self.db, status="sending", extend_ttl=True)
        return await self._dispatch_and_track(
            session, action="send", account_id=aid, status="awaiting_otp"
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

        owned = await self.accounts.get_owned(created_by, aid)
        if not owned:
            # Allow claim only if key exists on GitHub and is free in D1.
            try:
                await self.accounts.assert_key_available_for_user(created_by, aid)
            except AccountConflictError:
                raise
            registry = await self.scaffold.list_registry_accounts()
            row = next((r for r in registry if r.get("id") == aid), None)
            if not row:
                raise ValueError("account_missing")
        else:
            row = {
                "label": owned.get("label"),
                "session_name": owned.get("session_name"),
                "session_secret": owned.get("session_secret"),
                "workflow": owned.get("workflow"),
                "profile": owned.get("profile_path"),
                "enabled": owned.get("enabled"),
            }

        await self.accounts.assert_phone_available(phone_ok, except_account_id=aid)

        session = await LoginSession.create_new(
            self.db,
            account_id=aid,
            role=owned.get("role") if owned else None,
            created_by=created_by,
            phone=phone_ok,
            status="sending",
        )
        await self.accounts.sync_from_login(
            user_id=created_by,
            account_id=aid,
            label=str(row.get("label") or aid),
            role=(owned.get("role") if owned else None),
            phone_e164=phone_ok,
            enabled=int(row.get("enabled") or 0),
            session_name=str(row.get("session_name") or aid),
            session_secret=row.get("session_secret"),
            workflow=row.get("workflow"),
            profile_path=row.get("profile") or row.get("profile_path"),
            status="logging_in",
        )
        await session.touch(self.db, status="sending", extend_ttl=True)
        return await self._dispatch_and_track(
            session, action="send", account_id=aid, status="awaiting_otp"
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
        return await self._dispatch_and_track(
            session, action="complete", account_id=aid, status="completing"
        )

    async def refresh_run_status(self, session: LoginSession) -> dict[str, Any]:
        run_id = session.get("github_run_id")
        if not run_id:
            run = await self.github.latest_workflow_run(LOGIN_WORKFLOW)
            if run and run.get("id") is not None:
                run_id = str(run.get("id"))
                session = await session.touch(
                    self.db, github_run_id=run_id, extend_ttl=True
                )
            else:
                return {"status": "unknown", "conclusion": None, "html_url": ""}
        run = await self.github.get_run(run_id)
        conclusion = run.get("conclusion")
        status = run.get("status")
        session_status = str(session.get("status") or "")
        result = {
            "status": status,
            "conclusion": conclusion,
            "html_url": run.get("html_url"),
            "run_id": run_id,
            "session_status": session_status,
        }
        owner_id = int(session.get("created_by") or 0)
        aid = str(session.get("account_id"))

        if status == "completed" and session_status == "completing":
            if conclusion == "success":
                await session.touch(
                    self.db, status="done", clear_secrets=True, error=None
                )
                if owner_id:
                    existing = await self.accounts.get_owned(owner_id, aid)
                    role = str((existing or {}).get("role") or "").lower()
                    await self.accounts.sync_from_login(
                        user_id=owner_id,
                        account_id=aid,
                        label=(existing.get("label") if existing else aid),
                        role=(existing.get("role") if existing else None),
                        phone_e164=(existing.get("phone_e164") if existing else None),
                        enabled=int(existing.get("enabled") or 0) if existing else 0,
                        session_name=(
                            existing.get("session_name") if existing else aid
                        ),
                        session_secret=(
                            existing.get("session_secret") if existing else None
                        ),
                        workflow=(existing.get("workflow") if existing else None),
                        profile_path=(
                            existing.get("profile_path") if existing else None
                        ),
                        mark_login=True,
                    )
                    try:
                        from app.Services.ProvisioningService import ProvisioningService

                        provisioning = ProvisioningService(
                            self.db,
                            accounts=self.accounts,
                            scaffold=self.scaffold,
                            runner=RunOrchestratorService(self.db, self.github),
                        )
                        provisioned = await provisioning.provision_after_login(
                            user_id=owner_id,
                            account_id=aid,
                        )
                        result["provisioning"] = provisioned
                    except Exception as exc:
                        result["provisioning_error"] = str(exc)[:200]
                result["login"] = "done"
            else:
                await session.touch(
                    self.db,
                    status="failed",
                    error=f"workflow_{conclusion or 'failed'}",
                )
                if owner_id:
                    existing = await self.accounts.get_owned(owner_id, aid)
                    await self.accounts.sync_from_login(
                        user_id=owner_id,
                        account_id=aid,
                        label=(existing.get("label") if existing else aid),
                        role=(existing.get("role") if existing else None),
                        phone_e164=(existing.get("phone_e164") if existing else None),
                        enabled=int(existing.get("enabled") or 0) if existing else 0,
                        session_name=(
                            existing.get("session_name") if existing else aid
                        ),
                        session_secret=(
                            existing.get("session_secret") if existing else None
                        ),
                        workflow=(existing.get("workflow") if existing else None),
                        profile_path=(
                            existing.get("profile_path") if existing else None
                        ),
                        status="error",
                        last_error=f"workflow_{conclusion or 'failed'}",
                    )
                result["login"] = "failed"
        elif status == "completed" and session_status in {
            "awaiting_otp",
            "awaiting_2fa",
            "sending",
        }:
            if conclusion == "success":
                result["login"] = "otp_sent"
            else:
                result["login"] = "send_failed"
                result["error"] = f"workflow_{conclusion or 'failed'}"
        return result

    async def cancel(self, session: LoginSession) -> LoginSession:
        return await session.touch(
            self.db, status="cancelled", clear_secrets=True, error="cancelled"
        )

    async def poll_until_settled(
        self,
        session: LoginSession,
        *,
        expect: str = "completing",
        attempts: int = 24,
        delay_seconds: float = 4.0,
    ) -> dict[str, Any]:
        last: dict[str, Any] = {"status": "unknown"}
        for _ in range(attempts):
            sid = session.get("id")
            fresh = await LoginSession.find(self.db, sid) if sid else session
            if fresh:
                session = fresh
            last = await self.refresh_run_status(session)
            status = last.get("status")
            login = last.get("login")
            if status == "completed" or login in {
                "done",
                "failed",
                "otp_sent",
                "send_failed",
            }:
                if expect == "completing" and login == "otp_sent":
                    await asyncio.sleep(delay_seconds)
                    continue
                return last
            await asyncio.sleep(delay_seconds)
        last["login"] = last.get("login") or "timeout"
        return last

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
