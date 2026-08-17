# Telegram Admin Bot (Cloudflare Python Workers)

Control-plane bot for `telegram-auto`. Only **you** talk to this bot.
Telethon accounts should **not** `/start` it.

Read [HOW_WE_BUILT.md](HOW_WE_BUILT.md) for setup history and Windows/Pyodide deploy workaround.

## Live

- Worker: https://telegram-admin-bot.social-panel.workers.dev
- Webhook: `POST /webhook`
- Health: `GET /health`
- Bridge: `GET /internal/login/<account_id>?action=send|complete` (Bearer `BRIDGE_TOKEN`)

## Laravel-like layout

```text
cf-admin-bot/
  src/entry.py
  src/app/
    Models/          # User, Account, LoginSession, UserState + QueryBuilder
    Services/        # Telegram, Auth, GitHub, Scaffold, LoginOrchestrator
    Http/Controllers # Webhook / Guest / Admin / Accounts / InternalLogin
    Support/         # Lang __(), Env
  src/config/        # BotConfig, menus
  src/lang/fa/       # ALL user-facing Persian strings
  database/migrations/
```

Design rules:

- Controllers stay thin; business logic in Services/Models
- No duplicated copy — use `__("key")` from `lang/fa`
- Keyboard structure in `config/menus.py`; labels from lang
- D1 access via Model/QueryBuilder
- Production Telegram login only on GitHub Actions (runner IP)

## Accounts / login (first feature)

From the bot: **اکانت‌ها** → افزودن یا لاگین موجود.

1. Wizard collects `account_id` / role / phone (and later OTP / 2FA)
2. Bot scaffolds files on `master` via GitHub Git Data API (add flow)
3. Phone/OTP/2FA stay in D1 (`login_sessions`) — never logged
4. Bot dispatches `login-account.yml`
5. Workflow pulls credentials from this Worker bridge (or falls back to `LOGIN_*` secrets for `manage.ps1`)

## Secrets

Worker (`npx wrangler secret put ...`):

```bash
npx wrangler secret put TELEGRAM_BOT_TOKEN
npx wrangler secret put WEBHOOK_SECRET
npx wrangler secret put ADMIN_PASSWORD
npx wrangler secret put GITHUB_TOKEN          # PAT: contents + actions on the repo
npx wrangler secret put GITHUB_REPO           # owner/repo (optional if default set)
npx wrangler secret put GITHUB_BRANCH         # default master
npx wrangler secret put BRIDGE_TOKEN          # shared with GitHub secret below
# optional:
npx wrangler secret put ADMIN_IDS
```

GitHub repo secrets:

```bash
gh secret set ADMIN_BOT_BRIDGE_URL --body "https://telegram-admin-bot.social-panel.workers.dev"
gh secret set ADMIN_BOT_BRIDGE_TOKEN   # same value as Worker BRIDGE_TOKEN
# already required for session export:
# REPO_SECRETS_TOKEN
```

## Users (D1)

- DB: `telegram-admin-db` → `env.DB`
- Tables: `users`, `accounts`, `login_sessions`, `user_states`
- Message bot → upsert `role=user`
- Send correct `ADMIN_PASSWORD` → `role=admin`

## Deploy (Windows-friendly)

```bash
cd cf-admin-bot
npm install
uv sync
npm run deploy
npx wrangler d1 migrations apply telegram-admin-db --remote
```

## Main keyboard

Labels come from `lang/fa/messages.py` (`menu.btn_*`).
Accounts submenu: list / add / login existing / cancel.
