# Multi-account GitHub Actions

Each Telegram identity runs in its **own workflow / concurrency group / data cache**.
A ban or FloodWait on one account does not stop the others.

## Layout

| Piece | Role |
|-------|------|
| `config/accounts.json` | Registry (id, workflow, secret name, enabled) |
| `config/accounts/<id>.json` | Module profile (what that account runs) |
| `.github/workflows/run-account.yml` | Reusable job (checkout, cache, session, run) |
| `.github/workflows/run-account-<id>.yml` | Per-account caller (cron + dispatch) |
| `.github/workflows/login-account.yml` | OTP login entirely on runner IP |
| `ACCOUNT_ID` + `DATA_DIR` | Isolate `data/<id>/` state |

## Secrets

Shared (all accounts):

- `API_ID`, `API_HASH`, `ADMIN_PASSWORD`, `ADMIN_IDS` (optional)
- `REPO_SECRETS_TOKEN` — PAT that can **write** repository secrets (needed for GHA login)

Per account:

| Account | Session secret | Session file |
|---------|----------------|--------------|
| elmira | `TELEGRAM_SESSION_B64` | `easy_seen.session` |
| promo1 | `TELEGRAM_SESSION_B64_PROMO1` | `promo1.session` |
| *(new)* | `TELEGRAM_SESSION_B64_<ID>` | `<id>.session` |

**Do not** create production sessions on your home PC. Use GHA login below so OTP + session save happen on the runner IP.

## Add a new account (PowerShell)

```powershell
# 1) Scaffold registry + profile + workflow caller
.\manage.ps1 account-add -Account promo2 -Role promo

# 2) Commit + push (workflow must exist on GitHub before login)
#    (ask the agent, or commit yourself, then:)
.\manage.ps1 git-push -Yes

# 3) One-time PAT for writing secrets
.\manage.ps1 login-setup
#    -> gh secret set REPO_SECRETS_TOKEN

# 4) Login on runner IP only
.\manage.ps1 login-send -Account promo2 -Phone +98912xxxxxxx -Yes
.\manage.ps1 login-otp
# if cloud password:
.\manage.ps1 login-2fa
.\manage.ps1 login-complete -Account promo2 -Yes
.\manage.ps1 login-cleanup

# 5) Enable + push + start
.\manage.ps1 account-enable -Account promo2 -Yes
# commit/push accounts.json
.\manage.ps1 gha-dispatch -Account promo2
```

Roles for `account-add`:

- `promo` — `promo_spread` only (`dry_run: true`)
- `forward` — `channel_forward` + digest
- `collector` — `link_harvest` only (read link directories)
- `inspector` — `group_inspect` only (slow join/check/leave)
- `full` — forward + promo (not for discovery)

See [group-discovery.md](group-discovery.md) for the safe collector → inspector → promo pipeline.

Disabled accounts (`enabled: false`) are skipped by the runner even if cron fires.

## Why Elmira joined local test channels

Shared `config/modules.json` used to contain sample routes. On GHA start,
`channel_forward` called `ensure_joined` and joined those sources.

Mitigations:

- committed `routes` is empty
- `auto_join: false` by default (startup will **not** join; admin `/forward add` still can)
- each account keeps its own routes in `data/<account>/modules.runtime.json`

## Login only on GitHub runners (required for production)

Different IP (home → datacenter) looks like session theft to Telegram.

Phone / OTP / 2FA are stored as **temporary secrets** (`LOGIN_PHONE`, `LOGIN_OTP`, `LOGIN_2FA`),
never as public `workflow_dispatch` inputs — **or** provided by the Cloudflare admin-bot bridge
(`ADMIN_BOT_BRIDGE_URL` + `ADMIN_BOT_BRIDGE_TOKEN`) when driving login from Telegram.

Workflow: `.github/workflows/login-account.yml`

Admin bot: `cf-admin-bot/` → menu **اکانت‌ها** (scaffold + OTP wizard).

## Monitoring

```powershell
.\manage.ps1 status-all
.\manage.ps1 gha-list-all
.\manage.ps1 gha-restart -Account elmira -Yes
.\manage.ps1 gha-restart-all -Yes
```

## Safety rules

- Never run the same session locally and on GHA at once
- Local/dev only: `SESSION_NAME=dev_seen`
- Production logins: GHA `login-account` only
- Prefer dedicated promo accounts (not Elmira) for `/promo`
- Discovery: dedicated collector/inspector accounts only — see [group-discovery.md](group-discovery.md)
