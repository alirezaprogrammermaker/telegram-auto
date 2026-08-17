from __future__ import annotations

from app.Support.Env import env_str


class BotConfig:
    """Typed accessors for Worker env (Laravel config-style)."""

    def __init__(self, env) -> None:
        self.env = env

    @property
    def telegram_token(self) -> str:
        return env_str(self.env, "TELEGRAM_BOT_TOKEN")

    @property
    def webhook_secret(self) -> str:
        return env_str(self.env, "WEBHOOK_SECRET")

    @property
    def admin_password(self) -> str:
        return env_str(self.env, "ADMIN_PASSWORD")

    @property
    def bridge_token(self) -> str:
        return env_str(self.env, "BRIDGE_TOKEN")

    @property
    def github_token(self) -> str:
        return env_str(self.env, "GITHUB_TOKEN")

    @property
    def github_repo(self) -> str:
        return env_str(self.env, "GITHUB_REPO", "alirezaprogrammermaker/telegram-auto")

    @property
    def github_branch(self) -> str:
        return env_str(self.env, "GITHUB_BRANCH", "master")

    @property
    def bootstrap_admin_ids(self) -> set[int]:
        raw = env_str(self.env, "ADMIN_IDS")
        out: set[int] = set()
        for part in raw.replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                out.add(int(part))
            except ValueError:
                continue
        return out

    @property
    def db(self):
        return self.env.DB

    def github_ready(self) -> bool:
        return bool(self.github_token and self.github_repo)
