# Configuration Sources

یکی از مهم‌ترین چیزهایی که باید در این پروژه بدانی این است که همه تنظیمات در یک محل نیستند. این فایل مشخص می‌کند هر نوع تنظیم کجا زندگی می‌کند و ترتیب precedence آن چیست.

## Source Of Truth By Category

| Category | Main location | Owner |
|---|---|---|
| Base module defaults | `config/modules.json` | repo |
| Account registry | `config/accounts.json` | repo |
| Account-specific profile | `config/accounts/<id>.json` | repo |
| Runtime overrides | `data/<account>/modules.runtime.json` | runtime/userbot |
| Local secrets | `.env` | operator |
| Worker secrets | `wrangler secret put ...` | operator |
| GitHub Actions secrets | repo secrets | operator |
| Control-plane state | D1 tables in `cf-admin-bot` | admin bot |

## Config Precedence In Userbot Runtime

وقتی `main.py` اجرا می‌شود، config تقریبا با این ترتیب شکل می‌گیرد:

1. env vars از `.env` یا GitHub Actions
2. defaults از `config/modules.json`
3. overlay اکانت از `config/accounts/<id>.json`
4. اگر وجود داشته باشد: `data/<account>/modules.runtime.json`

پس runtime overlay آخرین لایه است و می‌تواند تغییرات live را حتی بعد از restart نگه دارد.

## Files And What They Mean

### `config/modules.json`
- default همه ماژول‌ها
- مناسب تعریف baseline behavior
- نباید برای routeهای production account-specific به آن تکیه کرد

### `config/accounts.json`
- registry همه اکانت‌ها
- شامل `id`, `enabled`, `workflow`, `session_secret`, `profile`
- admin bot از این فایل برای scaffold/enable/disable استفاده می‌کند

### `config/accounts/<id>.json`
- profile واقعی آن اکانت
- تعیین می‌کند کدام moduleها enabled هستند
- routeهای forward/promo معمولا اینجا patch می‌شوند

### `data/<account>/modules.runtime.json`
- overrideهای runtime
- برای تغییراتی که از داخل runtime یا live command اعمال می‌شوند
- این فایل durable است ولی در git نیست

### D1 tables
- UI state، ownership، audit trail و orchestration را نگه می‌دارند
- routeها به‌طور مستقیم در D1 source of truth نیستند؛ بیشترشان در profileهای git-backed هستند

## Which Layer To Change

### می‌خواهی default یک ماژول را برای همه عوض کنی
`config/modules.json`

### می‌خواهی رفتار یک اکانت خاص را عوض کنی
`config/accounts/<id>.json`

### می‌خواهی اکانت جدید اضافه کنی
`config/accounts.json` + `config/accounts/<id>.json` + workflow caller

### می‌خواهی state مدیریتی را عوض کنی
D1 migration/model/service

### می‌خواهی تغییر فوری روی runtime زنده بدهی
live command یا runtime overlay

## Important Split: Git-backed Config vs D1 State

### Git-backed config
- account registry
- profileها
- workflow definitions

### D1 state
- `users`
- `accounts`
- `login_sessions`
- `user_states`
- `commands`
- `account_heartbeats`
- `forward_jobs`
- `assignments`
- `help_guides`
- `linkdir_*`

این جداسازی مهم است: profile mutation از طریق GitHub API انجام می‌شود، ولی control plane و audit/state در D1 می‌مانند.
