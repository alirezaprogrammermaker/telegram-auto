"""Print base64 of the local Telethon session for GitHub Secret TELEGRAM_SESSION_B64."""
from __future__ import annotations

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    name = (sys.argv[1] if len(sys.argv) > 1 else "easy_seen").strip() or "easy_seen"
    path = ROOT / f"{name}.session"
    if not path.exists():
        print(f"Session not found: {path}", file=sys.stderr)
        print("Run login first: python login.py send && python login.py sign_in <code>", file=sys.stderr)
        sys.exit(1)

    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    print(encoded)
    print(f"\n# file={path.name} bytes={path.stat().st_size} b64_len={len(encoded)}", file=sys.stderr)
    print("# Set the matching GitHub secret, e.g.:", file=sys.stderr)
    print("#   easy_seen → TELEGRAM_SESSION_B64", file=sys.stderr)
    print("#   promo1    → TELEGRAM_SESSION_B64_PROMO1", file=sys.stderr)
    print("# See config/accounts.json and docs/multi-account.md", file=sys.stderr)


if __name__ == "__main__":
    main()
