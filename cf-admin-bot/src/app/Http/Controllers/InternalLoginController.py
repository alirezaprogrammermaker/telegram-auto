"""Internal bridge for GHA login-account workflow."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from app.Services.GitHubService import GitHubService
from app.Services.LoginOrchestratorService import LoginOrchestratorService
from app.Support.Lang import __
from config.bot import BotConfig
from workers import Response


class InternalLoginController:
    def __init__(self, env) -> None:
        self.config = BotConfig(env)

    async def handle(self, request, account_id: str) -> Response:
        expected = self.config.bridge_token
        if not expected:
            return Response.json(
                {"ok": False, "error": "bridge_disabled"}, status=503
            )

        auth = request.headers.get("Authorization") or ""
        token = ""
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        if token != expected:
            return Response.json(
                {"ok": False, "error": __("error.unauthorized")}, status=401
            )

        url = urlparse(request.url)
        qs = parse_qs(url.query or "")
        action = (qs.get("action") or ["send"])[0].strip().lower()
        if action not in {"send", "complete"}:
            return Response.json(
                {"ok": False, "error": "bad_action"}, status=400
            )

        aid = (account_id or "").strip().lower()
        if not aid:
            return Response.json(
                {"ok": False, "error": "missing_account"}, status=400
            )

        gh = GitHubService(
            self.config.github_token,
            self.config.github_repo,
            branch=self.config.github_branch,
        )
        orch = LoginOrchestratorService(self.config.db, gh)
        payload = await orch.bridge_payload(aid, action)
        if not payload:
            return Response.json(
                {"ok": False, "error": "credentials_unavailable"}, status=404
            )
        return Response.json(payload)
