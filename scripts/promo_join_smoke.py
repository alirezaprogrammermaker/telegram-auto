"""One-shot: verify promo session can resolve/join an ad channel, then exit."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from telethon.tl.functions.channels import GetParticipantRequest  # noqa: E402

from app.client import build_client  # noqa: E402
from app.config import load_app_config  # noqa: E402
from modules.promo_spread.targets import ensure_promo_group, ensure_source_channel  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="@channel")
    parser.add_argument(
        "--group",
        action="append",
        default=[],
        help="Optional destination @group (repeatable)",
    )
    parser.add_argument("--limit-groups", type=int, default=3)
    args = parser.parse_args()

    config = load_app_config()
    print(json.dumps({"account_id": os.environ.get("ACCOUNT_ID"), "session": config.session_name}))
    tg = build_client(config)
    await tg.connect()
    try:
        if not await tg.is_user_authorized():
            print(json.dumps({"ok": False, "error": "not_authorized"}))
            return 1
        me = await tg.get_me()
        print(
            json.dumps(
                {
                    "ok": True,
                    "user_id": me.id if me else None,
                    "username": getattr(me, "username", None),
                }
            )
        )

        entity, label = await ensure_source_channel(tg, args.source, auto_join=True)
        me = await tg.get_me()
        await tg(GetParticipantRequest(entity, me))
        print(json.dumps({"source_joined": True, "source": label, "id": int(entity.id)}))

        joined = []
        failed = []
        for ref in (args.group or [])[: max(0, args.limit_groups)]:
            try:
                _e, glabel, gid = await ensure_promo_group(tg, ref, auto_join=True)
                joined.append({"group": glabel, "id": gid})
            except Exception as exc:  # noqa: BLE001 - smoke report
                failed.append({"group": ref, "error": f"{type(exc).__name__}:{exc}"})
        print(json.dumps({"groups_joined": joined, "groups_failed": failed}, ensure_ascii=False))
        return 0 if not failed or joined else 2
    finally:
        await tg.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
