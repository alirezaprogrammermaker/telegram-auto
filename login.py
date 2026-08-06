"""Telethon login helpers: send OTP, complete with code, optional 2FA password."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from telethon.errors import (
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)

from app.client import build_client
from app.config import load_app_config

ROOT = Path(__file__).resolve().parent
PENDING_PATH = ROOT / "pending_login.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("login")


async def send_login_code() -> dict:
    config = load_app_config()
    if not config.phone:
        return {"status": "failed", "error": "PHONE is missing in .env"}

    tg = build_client(config)
    await tg.connect()
    try:
        if await tg.is_user_authorized():
            me = await tg.get_me()
            return {
                "status": "already_authorized",
                "user_id": me.id if me else None,
                "username": getattr(me, "username", None),
            }

        sent = await tg.send_code_request(config.phone)
        pending = {
            "phone": config.phone,
            "phone_code_hash": sent.phone_code_hash,
            "type": type(sent.type).__name__ if sent.type else None,
            "next_type": type(sent.next_type).__name__ if sent.next_type else None,
            "timeout": getattr(sent, "timeout", None),
            "session_name": config.session_name,
        }
        PENDING_PATH.write_text(json.dumps(pending, indent=2), encoding="utf-8")
        return {
            "status": "code_sent",
            "phone": config.phone,
            "type": pending["type"],
            "next_type": pending["next_type"],
            "timeout": pending["timeout"],
            "pending_file": str(PENDING_PATH),
        }
    finally:
        await tg.disconnect()


async def complete_login(code: str, password: str | None = None) -> dict:
    config = load_app_config()
    code = code.strip().replace(" ", "")

    tg = build_client(config)
    await tg.connect()
    try:
        if await tg.is_user_authorized():
            me = await tg.get_me()
            PENDING_PATH.unlink(missing_ok=True)
            return {
                "status": "already_authorized",
                "user_id": me.id if me else None,
                "username": getattr(me, "username", None),
            }

        if not PENDING_PATH.exists():
            return {
                "status": "failed",
                "error": "No pending_login.json — run: python login.py send",
            }

        pending = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
        phone = pending["phone"]
        phone_code_hash = pending["phone_code_hash"]

        try:
            await tg.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            if not password:
                return {
                    "status": "2fa_required",
                    "message": "OTP accepted. Provide 2FA password: "
                    "python login.py sign_in <code> <password>",
                }
            await tg.sign_in(password=password)
        except PhoneCodeInvalidError:
            return {"status": "failed", "error": "Invalid login code"}
        except PhoneCodeExpiredError:
            return {
                "status": "failed",
                "error": "Login code expired — run: python login.py send",
            }

        me = await tg.get_me()
        PENDING_PATH.unlink(missing_ok=True)
        return {
            "status": "logged_in",
            "user_id": me.id if me else None,
            "username": getattr(me, "username", None),
            "first_name": getattr(me, "first_name", None),
            "phone": getattr(me, "phone", None),
            "session_file": str(ROOT / f"{config.session_name}.session"),
        }
    finally:
        await tg.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram session login")
    sub = parser.add_subparsers(dest="action")

    sub.add_parser("send", help="Send login code")
    sign = sub.add_parser("sign_in", help="Complete login with OTP (+ optional 2FA)")
    sign.add_argument("code", help="OTP code from Telegram")
    sign.add_argument("password", nargs="?", default=None, help="2FA cloud password")

    args = parser.parse_args()
    action = args.action or "send"

    if action == "send":
        result = asyncio.run(send_login_code())
    elif action == "sign_in":
        result = asyncio.run(complete_login(args.code, args.password))
    else:
        parser.print_help()
        sys.exit(2)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") in {"failed"}:
        sys.exit(1)


if __name__ == "__main__":
    main()
