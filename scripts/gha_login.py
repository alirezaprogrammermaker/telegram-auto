"""GitHub Actions login helpers — OTP send/complete entirely on the runner IP.

Security notes:
- Do NOT pass the OTP as a workflow input on a public repo (inputs are visible).
- Set temporary secrets LOGIN_OTP / LOGIN_2FA via `gh secret set`, then clear them.
- Session secret is written with `gh secret set` from the runner (same IP as login).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from telethon.errors import (  # noqa: E402
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession  # noqa: E402

from app.client import build_client  # noqa: E402
from app.config import load_app_config  # noqa: E402
from app.paths import ensure_data_dir  # noqa: E402


def _pending_path() -> Path:
    ensure_data_dir()
    # Keep pending login next to session in workspace root (artifact-friendly)
    return ROOT / "pending_login.json"


def _mask(s: str) -> str:
    if not s:
        return ""
    if len(s) <= 4:
        return "***"
    return s[:2] + "***" + s[-2:]


async def _portable_session_payload() -> dict:
    """Return a portable StringSession payload from the current authorized login."""
    config = load_app_config()
    tg = build_client(config)
    await tg.connect()
    try:
        if not await tg.is_user_authorized():
            return {
                "status": "failed",
                "error": f"session_not_authorized:{config.session_name}",
            }
        session_string = StringSession.save(tg.session)
        return {
            "status": "ok",
            "format": "telethon_string_session",
            "session": session_string,
            "session_name": config.session_name,
        }
    finally:
        await tg.disconnect()


async def cmd_send(phone: str) -> dict:
    os.environ["PHONE"] = phone.replace(" ", "")
    config = load_app_config()
    tg = build_client(config)
    await tg.connect()
    try:
        if await tg.is_user_authorized():
            me = await tg.get_me()
            return {
                "status": "already_authorized",
                "user_id": me.id if me else None,
                "username": getattr(me, "username", None),
                "session": config.session_name,
            }

        sent = await tg.send_code_request(config.phone)
        pending = {
            "phone": config.phone,
            "phone_code_hash": sent.phone_code_hash,
            "session_name": config.session_name,
            "account_id": os.environ.get("ACCOUNT_ID", ""),
        }
        _pending_path().write_text(json.dumps(pending, indent=2), encoding="utf-8")
        return {
            "status": "code_sent",
            "phone": _mask(config.phone or ""),
            "session": config.session_name,
            "pending": str(_pending_path().name),
            "hint": "Set secret LOGIN_OTP (and LOGIN_2FA if needed), then run action=complete",
        }
    except FloodWaitError as exc:
        wait = int(getattr(exc, "seconds", 0) or 0)
        hours, rem = divmod(wait, 3600)
        minutes = rem // 60
        wait_label = f"{hours}h {minutes}m" if hours else f"{minutes}m"
        print(
            f"::error::Telegram FloodWait {wait}s (~{wait_label}). "
            "Do not retry send until that wait ends; extra attempts extend the lockout.",
            file=sys.stderr,
        )
        return {
            "status": "failed",
            "error": f"flood_wait:{wait}",
            "wait_seconds": wait,
            "hint": f"Wait ~{wait_label} before requesting another code for this number",
        }
    finally:
        await tg.disconnect()


async def cmd_complete(code: str, password: str | None) -> dict:
    config = load_app_config()
    pending_path = _pending_path()
    if not pending_path.exists():
        return {
            "status": "failed",
            "error": "pending_login.json missing — run action=send first on GHA",
        }

    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    phone = pending["phone"]
    phone_code_hash = pending["phone_code_hash"]
    code = code.strip().replace(" ", "")

    tg = build_client(config)
    await tg.connect()
    try:
        if await tg.is_user_authorized():
            me = await tg.get_me()
            pending_path.unlink(missing_ok=True)
            return {
                "status": "already_authorized",
                "user_id": me.id if me else None,
                "username": getattr(me, "username", None),
            }

        try:
            await tg.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            if not password:
                return {
                    "status": "2fa_required",
                    "error": "Set secret LOGIN_2FA and re-run action=complete",
                }
            await tg.sign_in(password=password)
        except PhoneCodeInvalidError:
            return {"status": "failed", "error": "Invalid login code"}
        except PhoneCodeExpiredError:
            return {"status": "failed", "error": "Code expired — run action=send again"}

        me = await tg.get_me()
        pending_path.unlink(missing_ok=True)
        session_file = ROOT / f"{config.session_name}.session"
        return {
            "status": "logged_in",
            "user_id": me.id if me else None,
            "username": getattr(me, "username", None),
            "first_name": getattr(me, "first_name", None),
            "session_file": session_file.name,
            "session_bytes": session_file.stat().st_size if session_file.exists() else 0,
        }
    finally:
        await tg.disconnect()


def cmd_export_secret(secret_name: str) -> dict:
    config = load_app_config()
    session_file = ROOT / f"{config.session_name}.session"
    if not session_file.exists():
        return {"status": "failed", "error": f"missing {session_file.name}"}

    if not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        return {
            "status": "failed",
            "error": "GH_TOKEN/GITHUB_TOKEN missing — set REPO_SECRETS_TOKEN secret",
        }

    portable = asyncio.run(_portable_session_payload())
    if portable.get("status") != "ok":
        return portable
    # Base64-wrap JSON so GHA env injection never truncates `{...}` payloads to `{}`.
    encoded = base64.b64encode(
        json.dumps(portable, ensure_ascii=True).encode("ascii")
    ).decode("ascii")
    # Pipe body on stdin (do not use "--body -" — gh stores literal "-" on some runners).
    env = os.environ.copy()
    proc = subprocess.run(
        ["gh", "secret", "set", secret_name],
        cwd=str(ROOT),
        input=encoded,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        return {
            "status": "failed",
            "error": (proc.stderr or proc.stdout or "gh secret set failed")[:300],
        }
    return {
        "status": "secret_set",
        "secret_name": secret_name,
        "session": config.session_name,
        "bytes": session_file.stat().st_size,
        "format": "telethon_string_session_b64",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="GHA Telegram login")
    parser.add_argument("action", choices=["send", "complete", "export-secret"])
    parser.add_argument("--phone", default="")
    parser.add_argument("--secret-name", default="TELEGRAM_SESSION_B64")
    args = parser.parse_args()

    if args.action == "send":
        phone = (args.phone or os.environ.get("LOGIN_PHONE") or os.environ.get("PHONE") or "").strip()
        if not phone:
            print(json.dumps({"status": "failed", "error": "PHONE/LOGIN_PHONE required"}))
            return 1
        result = asyncio.run(cmd_send(phone))
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("status") in {"code_sent", "already_authorized"} else 1

    if args.action == "complete":
        code = (os.environ.get("LOGIN_OTP") or "").strip()
        password = (os.environ.get("LOGIN_2FA") or "").strip() or None
        if not code:
            print(json.dumps({
                "status": "failed",
                "error": "LOGIN_OTP secret is empty — gh secret set LOGIN_OTP",
            }))
            return 1
        result = asyncio.run(cmd_complete(code, password))
        print(json.dumps(result, ensure_ascii=False))
        if result.get("status") not in {"logged_in", "already_authorized"}:
            return 1
        # Immediately export session to the account secret (same runner IP)
        exported = cmd_export_secret(args.secret_name)
        print(json.dumps(exported, ensure_ascii=False))
        return 0 if exported.get("status") == "secret_set" else 1

    if args.action == "export-secret":
        result = cmd_export_secret(args.secret_name)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("status") == "secret_set" else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
