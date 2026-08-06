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
    print("# Set GitHub secret TELEGRAM_SESSION_B64 to the line printed above.", file=sys.stderr)


if __name__ == "__main__":
    main()
