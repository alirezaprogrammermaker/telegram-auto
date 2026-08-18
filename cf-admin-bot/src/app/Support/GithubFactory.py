"""Shared GitHub client construction from BotConfig."""
from __future__ import annotations

from app.Services.AccountScaffoldService import AccountScaffoldService
from app.Services.GitHubService import GitHubService
from config.bot import BotConfig


def make_github(config: BotConfig) -> GitHubService | None:
    if not config.github_ready():
        return None
    return GitHubService(
        config.github_token,
        config.github_repo,
        branch=config.github_branch,
    )


def make_scaffold(config: BotConfig) -> AccountScaffoldService | None:
    gh = make_github(config)
    if not gh:
        return None
    return AccountScaffoldService(gh)
