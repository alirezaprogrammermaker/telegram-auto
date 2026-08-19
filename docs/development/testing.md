# Testing And Verification

این پروژه تست واحد سراسری و یکنواخت ندارد، پس verification باید بر اساس نوع تغییر انجام شود.

## For Python Runtime Changes

- syntax check فایل‌های تغییرکرده
- اگر ماژول جدید/تغییر ماژول دادی، config loading و startup path را بررسی کن
- اگر route logic تغییر کرده، با یک profile تستی verify کن

## For `cf-admin-bot` Changes

- syntax check فایل‌های Python تغییرکرده
- اگر message key جدید اضافه کردی، consistency `menus.py` و `messages.py` را چک کن
- اگر state جدید اضافه کردی، cancel/back path را هم چک کن
- اگر schema عوض شد، migration + deploy را verify کن

## For Workflow Changes

- env/secret names را دوباره match کن
- caller workflow و reusable workflow را با هم بررسی کن
- مطمئن شو account id و session secret nameها align هستند

## Existing Test/Research Areas

- `tests/translation/`: benchmark translation providers
- `tests/cloudflare_ai/`: Cloudflare AI evaluation harness

این‌ها بیشتر tooling/experiment هستند و معادل integration test کامل پروژه نیستند.

## Practical Rule

هر تغییری که دادی باید حداقل یکی از این سه مورد را داشته باشد:

1. syntax verification
2. focused manual flow verification
3. deploy/runtime verification اگر تغییر production-facing بوده
