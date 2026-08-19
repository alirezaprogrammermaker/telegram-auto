# `cf-admin-bot` Overview

`cf-admin-bot` لایه control plane پروژه است. این سرویس روی Cloudflare Python Workers اجرا می‌شود و از طریق یک ربات تلگرام، مدیریت کل سیستم را ممکن می‌کند.

## Responsibilities

- مدیریت user/admin در D1
- مدیریت wizardهای تلگرامی
- scaffold و patch کردن فایل‌های repo
- dispatch و کنترل GitHub Actions
- ارائه bridge داخلی برای login، pool, cache, live commands و alerts
- نگهداری command queue، heartbeat و audit data

## Non-Responsibilities

- اجرای مستقیم Telethon sessionها
- نگهداری state بلندمدت runtime در memory
- پردازش heavy یا long-lived job

## Main Layout

- `src/entry.py`: HTTP router
- `src/app/Http/Controllers/`: webhook, menu flows, internal endpoints
- `src/app/Models/`: D1 model layer
- `src/app/Services/`: business logic and orchestration
- `src/config/`: env adapter و keyboard layout
- `src/lang/fa/`: user-facing strings
- `database/migrations/`: schema

## Controller Pattern

الگوی کلی این است:

1. `WebhookController` update را parse می‌کند.
2. `AdminController` یا `GuestController` تصمیم می‌گیرد چه feature controllerی باید پیام را consume کند.
3. feature controllerها state machine هستند و state را در `user_states` نگه می‌دارند.
4. business logic در serviceهاست، نه در controller.

## Key Services

- `AuthService`: احراز هویت و bootstrap
- `AccountService`: ownership, listing, validation
- `AccountScaffoldService`: ساخت registry/profile/workflow در GitHub
- `ProfileConfigService`: mutation module config و routeها
- `LoginOrchestratorService`: login flow
- `RunOrchestratorService`: dispatch/cancel/restart workflow
- `AssignmentService`: smart assignment

## Data Sources

- D1: state و audit
- GitHub repo: profileها و workflow definitions
- Telegram Bot API: UI surface
- GitHub Actions: execution plane

## Recommended Reading

- [`request-flows.md`](request-flows.md)
- [`d1-schema.md`](d1-schema.md)
- [`assignment-engine.md`](assignment-engine.md)
- [`../../cf-admin-bot/README.md`](../../cf-admin-bot/README.md)
