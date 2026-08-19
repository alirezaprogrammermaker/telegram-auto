# Env And Secrets

این فایل ماتریس اصلی env varها و secretهاست. سعی کن اطلاعات secret را فقط همین‌جا canonical نگه داری.

## Local Userbot

فایل: `.env`

| Key | Purpose |
|---|---|
| `API_ID` | Telegram API id |
| `API_HASH` | Telegram API hash |
| `PHONE` | شماره برای login |
| `ADMIN_PASSWORD` | رمز مدیر |
| `ADMIN_IDS` | ادمین‌های دائمی |
| `SESSION_NAME` | نام session |
| `LOG_LEVEL` | سطح لاگ |
| `MAX_RUNTIME_SECONDS` | سقف runtime |
| `FLOOD_SLEEP_THRESHOLD` | رفتار FloodWait |
| `ACCOUNT_ID` | اکانت فعال |
| `DATA_DIR` | مسیر data |
| `ADMIN_BOT_BRIDGE_URL` | آدرس bridge |
| `ADMIN_BOT_BRIDGE_TOKEN` | توکن bridge |

## Cloudflare Worker Secrets

تنظیم با `npx wrangler secret put ...`

| Key | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | توکن BotFather ادمین‌بات |
| `WEBHOOK_SECRET` | secret header برای webhook |
| `ADMIN_PASSWORD` | رمز ورود ادمین |
| `ADMIN_IDS` | bootstrap admin ids |
| `GITHUB_TOKEN` | PAT برای repo files/actions |
| `GITHUB_REPO` | `owner/repo` |
| `GITHUB_BRANCH` | branch اصلی |
| `BRIDGE_TOKEN` | bearer token endpointهای `/internal/*` |

## GitHub Actions Repo Secrets

| Key | Purpose |
|---|---|
| `API_ID` | Telegram API id |
| `API_HASH` | Telegram API hash |
| `ADMIN_PASSWORD` | رمز مدیر runtime |
| `ADMIN_IDS` | ادمین‌های دائمی runtime |
| `ADMIN_BOT_BRIDGE_URL` | آدرس Worker |
| `ADMIN_BOT_BRIDGE_TOKEN` | همان `BRIDGE_TOKEN` |
| `REPO_SECRETS_TOKEN` | برای نوشتن secretهای session/login |
| `TELEGRAM_SESSION_B64*` | session base64 per account |
| `LOGIN_PHONE` | secret موقت login |
| `LOGIN_OTP` | secret موقت login |
| `LOGIN_2FA` | secret موقت login |

## Per-Account Session Secrets

برای هر اکانت معمولا یک secret session مستقل وجود دارد:

- `TELEGRAM_SESSION_B64`
- `TELEGRAM_SESSION_B64_PROMO1`
- `TELEGRAM_SESSION_B64_FORWARDER`
- ...

نام دقیق secret در `config/accounts.json` و D1 account metadata هم ثبت می‌شود.

## Rules

- هیچ session file یا `.env` نباید commit شود.
- secretهای Worker و GitHub باید جدا در نظر گرفته شوند، حتی اگر مقدار مشترک دارند.
- اگر `BRIDGE_TOKEN` لو رفت، هم Worker و هم GitHub secret مرتبط باید rotate شوند.
- تغییر نام secret یک اکانت باید با `config/accounts.json` و metadata مربوط sync شود.
