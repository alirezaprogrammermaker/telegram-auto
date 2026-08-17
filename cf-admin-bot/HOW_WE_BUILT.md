# How we built `cf-admin-bot`

This note documents **how the Cloudflare Python Worker Telegram admin bot was created**, what broke on Windows, and how we unblocked deploy. It is for future maintainers (and agents) so the same traps are not repeated.

## Goal

A **control-plane** Telegram bot on Cloudflare Workers:

- Admins manage `telegram-auto` from one bot chat
- Telethon user accounts do **not** need to `/start` this bot
- State lives in Cloudflare (D1), not PowerShell / chat-with-each-account

## Official docs we followed

- [Python Workers](https://developers.cloudflare.com/workers/languages/python/)
- [Python packages / pywrangler](https://developers.cloudflare.com/workers/languages/python/packages/)
- [FFI (`fetch`, bindings)](https://developers.cloudflare.com/workers/languages/python/ffi/)
- [D1 from Workers](https://developers.cloudflare.com/d1/)
- Example repos: `cloudflare/python-workers-examples` (`01-hello`, `04-query-d1`)

Stack chosen from those docs:

| Piece | Choice | Why |
|-------|--------|-----|
| Runtime | Cloudflare **Python Workers** (`python_workers` flag) | Requested; fits webhook bots |
| CLI | Wrangler 4 + `workers-runtime-sdk` | Native CF deploy |
| DB | **D1** | SQL, bindings, migrations; Laravel-like schemas |
| Secrets | `wrangler secret put` | Never commit bot token / password |
| HTTP to Telegram | `workers.fetch` → Bot API | Supported async path on Workers |

## Step-by-step creation

1. **Folder** `cf-admin-bot/` next to the Telethon monorepo (separate deployable app).
2. **Scaffold** `wrangler.jsonc`, `pyproject.toml` (`workers-py`, `workers-runtime-sdk`), `package.json`, `src/entry.py`.
3. **Bot logic (v1)** webhook `/webhook`, health `/health`, reply keyboard menus, secret header check (`X-Telegram-Bot-Api-Secret-Token`).
4. **Secrets**
   - `TELEGRAM_BOT_TOKEN`
   - `WEBHOOK_SECRET`
   - later `ADMIN_PASSWORD`, optional `ADMIN_IDS`
5. **Deploy attempt** with `uv run pywrangler deploy` (official path).
6. **D1** `telegram-admin-db`, migration `users`, binding `env.DB`.
7. **Auth** anyone messaging is stored as `user`; sending `ADMIN_PASSWORD` promotes to `admin`.

## Problems we hit (and fixes)

### 1) `pywrangler` required newer `uv`

```text
uv version at least 0.12.3 required, have 0.11.19
```

**Fix:** `uv self update` → `0.12.5`.

### 2) Pyodide Python install / probe failed on Windows

`pywrangler deploy` creates a **Pyodide** venv (`cpython-…-emscripten-wasm32-musl`). On this machine:

- Direct download of `xbuildenv-0.29.4.tar.gz` from GitHub returned **403**
- After install, `uv` probing `python.exe` failed with `ModuleNotFoundError: No module named 'python'`

**Workaround that worked:**

1. Download the release asset via **GitHub CLI** (`gh release download …`) when raw GitHub CDN 403s.
2. Skip relying on `pywrangler` for deploy on this Windows box.
3. Use **plain `npx wrangler deploy`** and **vendor** the `workers` runtime package into `python_modules/workers` (copied from `.venv/Lib/site-packages/workers`).

Helper: `npm run vendor` → `scripts/vendor-workers.mjs`  
Deploy: `npm run deploy` (= vendor + wrangler deploy)

First plain Wrangler deploy without vendoring failed with:

```text
ModuleNotFoundError: No module named 'workers'
… update to workers-py >= 1.90 or pass disable_python_external_sdk
```

After vendoring `python_modules/workers`, deploy succeeded and Worker URL came up:

`https://telegram-admin-bot.social-panel.workers.dev`

### 3) WSL unavailable as alternate build host

WSL reported `HCS_E_SERVICE_NOT_AVAILABLE`, so we could not “just build on Linux”. Windows vendoring path stayed the official local workaround.

### 4) D1 migration `fetch failed` once (network)

Remote `d1 migrations apply` failed once on connectivity; secrets/deploy still worked. Retry applied `0001_users.sql` successfully.  
Runtime also has `CREATE TABLE IF NOT EXISTS` in the User/bootstrap path so the bot is resilient if migrations lag.

### 5) Secrets in chat

Bot token and admin password were shared in chat during setup. They are stored only as **Wrangler secrets**, not in git. They should still be **rotated** in BotFather / secret store when possible.

## Current deploy recipe (Windows)

```powershell
cd cf-admin-bot
npm install
uv sync
npx wrangler secret put TELEGRAM_BOT_TOKEN
npx wrangler secret put WEBHOOK_SECRET
npx wrangler secret put ADMIN_PASSWORD
npm run deploy
# webhook (once):
# setWebhook url=…/webhook&secret_token=…
```

## Architecture direction (Laravel-like)

After the first working deploy, the code was reorganized toward a **Laravel-style** layout so updates stay cheap:

- `app/Models` — D1 models (Eloquent-ish API)
- `app/Services` — Telegram + Auth (no fat controllers)
- `app/Http/Controllers` — webhook / menus
- `config/` — keyboards & settings (structure, not copy)
- `lang/fa/` — all user-facing strings in one place
- `database/migrations/` — schema only
- `src/entry.py` — thin Worker entrypoint only

See `README.md` for the folder map after refactor.

## What we deliberately did *not* do

- Did **not** run Telethon inside the Worker (wrong runtime for long-lived user sessions)
- Did **not** commit tokens into the repo
- Did **not** require every Telethon account to `/start` the admin bot (ban / fingerprint risk)
