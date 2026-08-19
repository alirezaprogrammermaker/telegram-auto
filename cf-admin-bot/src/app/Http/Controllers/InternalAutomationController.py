from __future__ import annotations

from app.Services.AutomationService import AutomationService
from app.Services.GitHubService import GitHubService
from app.Services.RunOrchestratorService import RunOrchestratorService
from app.Services.TelegramService import TelegramService
from app.Support.BridgeAuth import require_bridge_token
from config.bot import BotConfig
from workers import Response


class InternalAutomationController:
    def __init__(self, env) -> None:
        self.config = BotConfig(env)
        self.db = self.config.db

    async def handle(self, request) -> Response:
        denied = require_bridge_token(request, self.config)
        if denied is not None:
            return denied

        user_id = None
        try:
            url = getattr(request, "url", "")
            if "?" in url:
                from urllib.parse import parse_qs, urlparse

                query = parse_qs(urlparse(url).query)
                raw = (query.get("user_id") or [""])[0].strip()
                if raw:
                    user_id = int(raw)
        except Exception:
            user_id = None

        github = None
        if self.config.github_ready():
            github = GitHubService(
                self.config.github_token,
                self.config.github_repo,
                branch=self.config.github_branch,
            )
        runner = RunOrchestratorService(self.db, github) if github else None
        tg = TelegramService(self.config.telegram_token)
        svc = AutomationService(self.db, runner=runner, tg=tg)
        summary = await svc.run_watchdog(
            user_id=user_id, source="internal_automation_endpoint"
        )
        return Response.json({"ok": True, "summary": summary})
