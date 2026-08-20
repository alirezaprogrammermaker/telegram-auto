"""Telegram admin commands for /cfai."""

from __future__ import annotations

import asyncio
from typing import Any

from app.cloudflare_ai.models import list_models_text, model_label, resolve_model_id
from app.cloudflare_ai.provider import CloudflareAIProvider
from app.cloudflare_ai.store import CloudflareAIStore, mask_token


async def handle_cfai_command(parts: list[str], *, progress) -> None:
    action = parts[1].lower() if len(parts) >= 2 else "status"
    store = CloudflareAIStore()
    provider = CloudflareAIProvider(store)

    if action in {"status", "stat"}:
        await _show_status(store, progress)
        return

    if action in {"help", "?"}:
        await progress.success(_help_text())
        return

    if action in {"accounts", "list"}:
        await _show_accounts(store, progress)
        return

    if action == "add" and len(parts) >= 5:
        name, account_id, api_token = parts[2], parts[3], parts[4]
        priority = int(parts[5]) if len(parts) >= 6 and parts[5].isdigit() else None
        try:
            row = store.add_account(
                name=name,
                account_id=account_id,
                api_token=api_token,
                priority=priority,
            )
        except ValueError as exc:
            await progress.fail(str(exc))
            return
        await progress.success(
            f"Account added: `{row['name']}`\n"
            f"id: `{row['account_id']}`\n"
            f"token: `{mask_token(api_token)}`\n"
            f"priority: {row['priority']}\n"
            f"store: `{store.path}`"
        )
        return

    if action == "remove" and len(parts) >= 3:
        name = parts[2]
        if store.remove_account(name):
            await progress.success(f"Removed `{name}`")
        else:
            await progress.fail(f"Not found: `{name}`")
        return

    if action in {"enable", "disable"} and len(parts) >= 3:
        name = parts[2]
        active = action == "enable"
        if store.set_active(name, active):
            await progress.success(f"`{name}` → {'active' if active else 'inactive'}")
        else:
            await progress.fail(f"Not found: `{name}`")
        return

    if action == "priority" and len(parts) >= 4:
        name = parts[2]
        try:
            priority = int(parts[3])
        except ValueError:
            await progress.fail("priority must be an integer")
            return
        if store.set_priority(name, priority):
            await progress.success(f"`{name}` priority → {priority}")
        else:
            await progress.fail(f"Not found: `{name}`")
        return

    if action == "model":
        if len(parts) >= 3 and parts[2].lower() == "set" and len(parts) >= 4:
            model = resolve_model_id(parts[3])
            store.set_default_model(model)
            await progress.success(
                f"Default model set to `{model}`\n({model_label(model)})"
            )
            return
        await progress.success(
            f"Default model: `{store.default_model()}`\n\n{list_models_text()}"
        )
        return

    if action == "test":
        model = None
        account_name = None
        if len(parts) >= 3:
            if parts[2].lower() == "model" and len(parts) >= 4:
                model = resolve_model_id(parts[3])
                account_name = parts[4] if len(parts) >= 5 else None
            else:
                account_name = parts[2]

        await progress.set_title("Testing Cloudflare AI")
        await progress.step(
            f"model: `{model or store.default_model()}`"
            + (f" · account: `{account_name}`" if account_name else " · auto-rotate")
        )
        try:
            if account_name:
                result = await asyncio.to_thread(
                    provider.test_account,
                    account_name,
                    model=model,
                )
            else:
                result = await asyncio.to_thread(
                    provider.chat,
                    [{"role": "user", "content": "Reply with exactly: OK"}],
                    model=model,
                    max_tokens=32,
                    temperature=0.0,
                )
        except Exception as exc:
            await progress.fail(str(exc))
            return

        await progress.success(
            "Test OK\n"
            f"account: `{result.account_name}`\n"
            f"model: `{result.model}`\n"
            f"response: `{result.content[:200]}`\n"
            f"neurons: {result.neurons:.2f}"
        )
        return

    await progress.fail("Unknown command — `/cfai help`")


async def _show_status(store: CloudflareAIStore, progress) -> None:
    summary = store.status_summary()
    await progress.set_title("Cloudflare AI status")
    await progress.step(f"store: `{summary['path']}`")
    await progress.step(
        f"default model: `{summary['default_model']}` ({model_label(summary['default_model'])})"
    )
    await progress.step(
        f"accounts: {summary['usable_accounts']}/{summary['total_accounts']} usable "
        f"({summary['active_accounts']} active)"
    )
    for row in summary["accounts"]:
        flag = "OK" if row["available"] else "EXHAUSTED"
        await progress.step(
            f"{flag} `{row['name']}` p={row['priority']} "
            f"uses={row['usage_count']} neurons={float(row['neurons_used_today']):.1f}"
        )
    await progress.success("Manage with `/cfai help`")


async def _show_accounts(store: CloudflareAIStore, progress) -> None:
    rows = store.list_accounts()
    if not rows:
        await progress.success("No accounts configured.\nUse `/cfai add <name> <account_id> <token>`")
        return
    lines = ["Cloudflare AI accounts:"]
    for row in rows:
        status = "active" if store.account_available(row) else "exhausted/inactive"
        lines.append(
            f"• `{row.get('name')}` — {status}\n"
            f"  id: `{row.get('account_id')}` token: `{mask_token(str(row.get('api_token') or ''))}`\n"
            f"  priority={row.get('priority', 0)} uses={row.get('usage_count', 0)}"
        )
    await progress.success("\n".join(lines))


def _help_text() -> str:
    return (
        "Cloudflare AI admin\n"
        "`/cfai status` — overview\n"
        "`/cfai accounts` — list accounts (masked tokens)\n"
        "`/cfai add <name> <account_id> <api_token> [priority]`\n"
        "`/cfai remove <name>`\n"
        "`/cfai enable|disable <name>`\n"
        "`/cfai priority <name> <n>`\n"
        "`/cfai model` — list models + default\n"
        "`/cfai model set <alias|model_id>`\n"
        "`/cfai test` — ping default model (auto-rotate)\n"
        "`/cfai test <account>` — test one account\n"
        "`/cfai test model <model> [account]`\n"
        "\n"
        "Seed from file: `python scripts/seed_cloudflare_ai.py --file /path/to/config.yaml`"
    )
