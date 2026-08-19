# D1 Schema Reference

این فایل شرح maintainer-facing جدول‌های D1 در `cf-admin-bot` است. برای SQL دقیق، migrationها را ببین:
`cf-admin-bot/database/migrations/`.

## Core Identity Tables

### `users`
- Telegram identity
- نقش `user|admin`
- metadata پایه مثل `chat_id`, `username`, timestamps

### `accounts`
- mapping اکانت‌های قابل مدیریت
- owner در `user_id`
- role اکانت، workflow، profile path، session secret name
- statusهای lifecycle مثل `scaffolded`, `logging_in`, `ready`, `error`

### `login_sessions`
- state موقت login
- phone, otp, twofa, expires_at
- GitHub run id و status

### `user_states`
- state machine چت
- state فعلی wizard
- `context_json` برای context هر wizard

## Live Control Tables

### `commands`
- صف command برای userbot
- status: `pending`, `acked`, `done`, `failed`, `expired`
- payload و result به‌صورت JSON string

### `account_heartbeats`
- آخرین وضعیت زنده هر اکانت
- `status`
- `modules_json`
- `meta_json`
- `updated_at`

## Feature Tables

### `help_guides`
- محتوای راهنمای dynamic
- category, key, title, content

### `forward_jobs`
- job-centric record برای بعضی flowهای forward setup
- account/source/destination/options

### `assignments`
- audit trail تخصیص routeهای forward/promo
- `task_type`
- `source`
- `target`
- `score_json`
- `status`

## Discovery Tables

### `linkdir_items`
catalog itemهای discovery

### `linkdir_events`
event log برای itemها

### `linkdir_collectors`
state و budget collectorها

### `linkdir_jobs`
job queue برای linkdir

### `linkdir_runs`
run history برای pipeline

## Important Relationship Notes

- `accounts.user_id` به `users.telegram_id` اشاره مفهومی دارد.
- `login_sessions.account_id`, `commands.account_id`, `account_heartbeats.account_id`, `forward_jobs.account_id`, `assignments.account_id` همگی به `accounts.id` وابسته‌اند.
- routeهای forward/promo عموما مستقیما در D1 ذخیره نمی‌شوند؛ در profileهای git-backed هستند. D1 بیشتر state و audit نگه می‌دارد.

## When To Add A New Table

جدول جدید زمانی موجه است که:

- state باید مستقل از runner باقی بماند
- audit یا ownership لازم است
- چند subsystem باید به آن داده دسترسی داشته باشند
- نگهداری آن در profile JSON مناسب نیست

اگر داده صرفا تنظیم یک اکانت است، اول بررسی کن که باید در `config/accounts/<id>.json` باشد یا نه.
