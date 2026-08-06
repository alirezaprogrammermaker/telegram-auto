# Telegram Auto

ماژولار user-client با Telethon. هر قابلیت یک ماژول اختیاری است؛ اگر ماژولی نباشد یا خطا بدهد، برنامه ادامه می‌دهد.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

`.env` را با `API_ID` / `API_HASH` / `PHONE` / `ADMIN_PASSWORD` پر کن.

### Login

```bash
python login.py send
python login.py sign_in <OTP>
# اگر 2FA داری:
python login.py sign_in <OTP> <password>
```

### Run

```bash
python main.py
```

فقط یک instance همزمان مجاز است (قفل `telegram_auto.lock`).

## Modules

پیکربندی: `config/modules.json`

| Module | توضیح |
|--------|--------|
| `channel_forward` | پست‌های کانال مبدأ را به کانال مقصد کپی/فوروارد می‌کند |
| `auto_reply` | جواب خودکار فقط برای کاربرانی که با کلمه رمز مدیر شده‌اند |

### auto_reply (admin unlock)

1. کاربر کلمه رمز (`ADMIN_PASSWORD` در `.env`) را در چت خصوصی می‌فرستد.
2. دسترسی مدیر ذخیره می‌شود در `data/admins.json`.
3. بعد از آن به پیام‌هایش جواب داده می‌شود.
4. برای خروج: `/logout`

رمز را در گیت نگذار؛ فقط در `.env` یا GitHub Secret.

### channel_forward

```json
"channel_forward": {
  "enabled": true,
  "sources": ["@source_channel"],
  "destination": "@your_channel",
  "delay_seconds": 1.5,
  "forward_mode": "copy"
}
```

## Keyboards / دکمه‌ها

| قابلیت | روی user account (Telethon فعلی) | روی Bot API |
|--------|-----------------------------------|-------------|
| Reply Keyboard / Inline Keyboard | عملاً مناسب نیست؛ طراحی تلگرام برای ربات است | کامل پشتیبانی می‌شود |
| Callback دکمه | نیاز به bot دارد | بله |
| typing / پاسخ متنی / فوروارد | بله | بله |

اگر منوی دکمه‌ای می‌خواهی، باید یک **ربات BotFather** جدا بسازی یا کنار این user-client اضافه کنی. با اکانت کاربری فعلی، کیبورد حرفه‌ای قابل اتکا نیست.

## GitHub Actions (هر ۶ ساعت)

هدف: job زمان‌بندی‌شده که **شروع می‌شود، چند ساعت گوش می‌دهد، تمیز خارج می‌شود** — نه سرور همیشه روشن.

### مدل اجرا

- هر job حداکثر **۶ ساعت** روی runner گیت‌هاب می‌ماند (`timeout-minutes: 360`)
- قبل از kill سخت، با `MAX_RUNTIME_SECONDS=21000` (~۵ ساعت و ۵۰ دقیقه) تمیز قطع می‌شود
- cron `0 */6 * * *` هر ۶ ساعت دوباره روشن می‌کند
- برای **بدون سقف دقیقه**: ریپو باید **public** باشد (runner استاندارد روی public رایگان است). روی private سهمیه ماهانه محدود است و job ممکن است زود قطع شود

### Secrets

| Secret | مقدار |
|--------|--------|
| `API_ID` | همان `.env` |
| `API_HASH` | همان `.env` |
| `ADMIN_PASSWORD` | رمز مدیر |
| `TELEGRAM_SESSION_B64` | خروجی `python scripts/export_session_b64.py` |

کد public است؛ Secretها در Settings → Actions می‌مانند و در ریپو commit نمی‌شوند.

### اجرا

- خودکار: هر ۶ ساعت
- دستی: Actions → `run-every-6h` → Run workflow
- همزمان با workflow، `main.py` لوکال را روشن نکن (همان سشن باطل می‌شود)

فایل: `.github/workflows/run-every-6h.yml`

## افزودن ماژول جدید

1. `modules/<name>/module.py` از `BaseModule`
2. ثبت در `app/loader.py` → `MODULE_REGISTRY`
3. تنظیمات در `config/modules.json`

## Safety

- userbot غیررسمی است؛ اتوماسیون زیاد ریسک محدودیت دارد.
- `.env`, `*.session`, `data/` در گیت نیستند.
