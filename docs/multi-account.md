# Multi-account GitHub Actions

Each Telegram identity runs in its **own workflow / concurrency group / data cache**.
A ban or FloodWait on one account does not stop the others.

## Layout

| Piece | Role |
|-------|------|
| `config/accounts.json` | Registry (id, workflow, secret name, enabled) |
| `config/accounts/<id>.json` | Module profile (what that account runs) |
| `.github/workflows/run-account.yml` | Reusable job (checkout, cache, session, run) |
| `.github/workflows/run-account-elmira.yml` | Elmira caller (forward) |
| `.github/workflows/run-account-promo1.yml` | Promo worker caller |
| `ACCOUNT_ID` + `DATA_DIR` | Isolate `data/<id>/` state |

## Secrets

Shared (all accounts):

- `API_ID`, `API_HASH`, `ADMIN_PASSWORD`, `ADMIN_IDS` (optional)

Per account:

| Account | Session secret | Session file |
|---------|----------------|--------------|
| elmira | `TELEGRAM_SESSION_B64` | `easy_seen.session` |
| promo1 | `TELEGRAM_SESSION_B64_PROMO1` | `promo1.session` |

Export a session:

```bash
# login with SESSION_NAME=promo1 in .env first
python scripts/export_session_b64.py promo1
# paste into GitHub secret TELEGRAM_SESSION_B64_PROMO1
```

## Enable promo1

1. Login locally with a **dedicated** promo phone (`SESSION_NAME=promo1`)
2. Set GitHub secret `TELEGRAM_SESSION_B64_PROMO1`
3. Set `"enabled": true` for promo1 in `config/accounts.json`
4. `Actions → run-account-promo1 → Run workflow`
5. In Telegram DM to that account: `/promo add …` (dry_run starts on)

## Monitoring

Use `manage.ps1` (English menu / CLI):

```powershell
.\manage.ps1 status-all
.\manage.ps1 gha-list-all
.\manage.ps1 gha-restart -Account elmira -Yes
.\manage.ps1 gha-restart-all -Yes
```

## Safety rules

- Never run the same session locally and on GHA at once
- Local/dev: `SESSION_NAME=dev_seen`, no `ACCOUNT_ID` or `ACCOUNT_ID=dev`
- Production accounts only on their workflows
