"""One-shot: set GHA secrets from local .env + session."""
from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def set_secret(name: str, value: str) -> None:
    proc = subprocess.run(
        ["gh", "secret", "set", name],
        input=value.encode("utf-8"),
        cwd=ROOT,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"failed to set {name}: {proc.stderr.decode(errors='replace')}"
        )
    print(f"set {name} ok")


def main() -> None:
    env = load_env(ROOT / ".env")
    needed = ["API_ID", "API_HASH", "ADMIN_PASSWORD"]
    missing = [k for k in needed if not env.get(k)]
    if missing:
        raise SystemExit(f"missing in .env: {missing}")

    session = ROOT / f"{env.get('SESSION_NAME', 'easy_seen')}.session"
    if not session.exists():
        raise SystemExit(f"missing session: {session}")

    for key in needed:
        set_secret(key, env[key])
    set_secret("TELEGRAM_SESSION_B64", base64.b64encode(session.read_bytes()).decode("ascii"))
    print("all secrets configured")


if __name__ == "__main__":
    main()
