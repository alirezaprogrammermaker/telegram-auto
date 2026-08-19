# GitHub Actions Workflows

این فایل نقش هر workflow مهم را مشخص می‌کند تا توسعه‌دهنده مجبور نباشد همه فایل‌های `.github/workflows/` را بخواند.

## Account Runtime

### `run-account.yml`
- reusable workflow اصلی برای اجرای یک userbot account
- مسئول:
  - checkout
  - restore cache/data
  - restore session
  - set env
  - run `main.py`

### `run-account-<id>.yml`
- caller workflow برای هر اکانت
- account-specific inputs و concurrency
- cron و workflow_dispatch ممکن است اینجا تعریف شده باشند

## Login

### `login-account.yml`
- login روی runner IP
- secretهای موقت یا bridge را برای phone/otp/2fa استفاده می‌کند
- بعد از موفقیت، session secret اکانت را می‌نویسد

## Admin Utility Workflows

### `pool-admin.yml`
- عملیات shared pool مثل status/list/approve/reject/get
- نتیجه را به Worker report می‌کند

### `account-cache-admin.yml`
- وضعیت/پاکسازی queue و cacheهای account-specific
- نتیجه را به Worker report می‌کند

### `automation-watchdog.yml`
- هر ۱۰ دقیقه `POST /internal/automation/run` را روی cf-admin-bot صدا می‌زند
- جایگزین Worker cron (محدودیت Free plan: حداکثر ۵ cron)
- نیاز: `ADMIN_BOT_BRIDGE_URL` و `ADMIN_BOT_BRIDGE_TOKEN` در repo secrets
- `workflow_dispatch` با `user_id` اختیاری برای محدود کردن scope

### `merge-group-pool.yml`
- ادغام pool خام بین اکانت‌ها یا artifactهای مختلف

## Linkdir

### `run-linkdir.yml`
- reusable workflow برای linkdir pipeline
- برخلاف `run-account.yml`، `main.py` را اجرا نمی‌کند

### `run-linkdir-*.yml`
- callerهای مخصوص collector/linkdir accountها

## How To Think About Workflows

- اگر تغییر مربوط به اجرای بلندمدت Telethon است: `run-account*.yml`
- اگر تغییر مربوط به login است: `login-account.yml`
- اگر تغییر مربوط به admin utility است: `pool-admin.yml` یا `account-cache-admin.yml`
- اگر تغییر مربوط به discovery pipeline مستقل است: `run-linkdir*.yml`

## Safety Notes

- هر account باید workflow مخصوص خودش و concurrency جداگانه داشته باشد.
- session یک اکانت نباید همزمان در لوکال و GHA استفاده شود.
- هر تغییری در secret naming باید با registry و workflowها sync شود.
