# Project Docs

این پوشه برای این ساخته شده که یک توسعه‌دهنده یا agent جدید بدون خواندن کل مخزن،
سریع بفهمد پروژه از چه بخش‌هایی تشکیل شده، هر تغییر باید کجا انجام شود، و هر داده
یا تنظیم از کجا می‌آید.

## Start Here

1. اگر تازه وارد پروژه شده‌ای، اول این فایل را بخوان.
2. بعد [`architecture/system-overview.md`](architecture/system-overview.md) را بخوان.
3. اگر قرار است روی تنظیمات یا deploy کار کنی، برو به بخش `configuration/` و `operations/`.
4. اگر قرار است روی پنل مدیریتی کار کنی، برو به `cf-admin-bot/`.

## Structure

### Architecture
- [`architecture/system-overview.md`](architecture/system-overview.md): نمای کلی سیستم، اجزا و ارتباط‌ها
- [`architecture/component-map.md`](architecture/component-map.md): هر پوشه و فایل مهم چه مسئولیتی دارد
- [`architecture/glossary.md`](architecture/glossary.md): واژه‌نامه مفاهیم دامنه پروژه

### Configuration
- [`configuration/config-sources.md`](configuration/config-sources.md): منبع هر تنظیم، اولویت لود، و owner آن
- [`configuration/env-and-secrets.md`](configuration/env-and-secrets.md): env vars و secrets در لوکال، GitHub Actions و Cloudflare

### Admin Bot
- [`cf-admin-bot/overview.md`](cf-admin-bot/overview.md): معماری و نقش `cf-admin-bot`
- [`cf-admin-bot/request-flows.md`](cf-admin-bot/request-flows.md): جریان‌های اصلی webhook، منوها، bridge و GitHub Actions
- [`cf-admin-bot/d1-schema.md`](cf-admin-bot/d1-schema.md): توضیح جدول‌های D1 و نقش هرکدام
- [`cf-admin-bot/assignment-engine.md`](cf-admin-bot/assignment-engine.md): موتور Smart Assignment و منطق انتخاب اکانت

### Operations
- [`operations/github-actions-workflows.md`](operations/github-actions-workflows.md): نقشه workflowها و کاربرد هرکدام
- [`operations/runbooks.md`](operations/runbooks.md): کارهای رایج عملیاتی و بازیابی خطاها
- [`multi-account.md`](multi-account.md): راهنمای چنداکانتی فعلی
- [`group-discovery.md`](group-discovery.md): راهنمای discovery / collector / inspector / promo

### Development
- [`development/local-setup.md`](development/local-setup.md): setup کامل برای کار روی هر دو بخش پروژه
- [`development/testing.md`](development/testing.md): راهنمای تست و verification

## Suggested Reading By Task

### می‌خواهم فقط پروژه را بفهمم
- [`architecture/system-overview.md`](architecture/system-overview.md)
- [`architecture/component-map.md`](architecture/component-map.md)
- [`architecture/glossary.md`](architecture/glossary.md)

### می‌خواهم یک قابلیت جدید به userbot اضافه کنم
- [`architecture/component-map.md`](architecture/component-map.md)
- [`configuration/config-sources.md`](configuration/config-sources.md)
- [`development/local-setup.md`](development/local-setup.md)
- [`README.md`](../README.md)

### می‌خواهم روی `cf-admin-bot` کار کنم
- [`cf-admin-bot/overview.md`](cf-admin-bot/overview.md)
- [`cf-admin-bot/request-flows.md`](cf-admin-bot/request-flows.md)
- [`cf-admin-bot/d1-schema.md`](cf-admin-bot/d1-schema.md)
- [`cf-admin-bot/README.md`](../cf-admin-bot/README.md)

### می‌خواهم deploy یا عملیات اجرایی انجام دهم
- [`configuration/env-and-secrets.md`](configuration/env-and-secrets.md)
- [`operations/github-actions-workflows.md`](operations/github-actions-workflows.md)
- [`operations/runbooks.md`](operations/runbooks.md)

## Documentation Rules

- READMEهای سطح بالا فقط خلاصه بدهند و به docs لینک کنند.
- اطلاعات مربوط به secretها فقط در یک محل canonical نوشته شود.
- اگر رفتار یک feature عوض شد، نزدیک‌ترین فایل docs همان feature باید به‌روزرسانی شود.
- فایل‌های historical مثل [`cf-admin-bot/HOW_WE_BUILT.md`](../cf-admin-bot/HOW_WE_BUILT.md) منبع setup اصلی نیستند؛ فقط برای context و محدودیت‌های گذشته‌اند.
