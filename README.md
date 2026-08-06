# Telegram Auto

ماژولار user-client با Telethon. هر قابلیت یک ماژول اختیاری است؛ اگر ماژولی نباشد یا خطا بدهد، برنامه ادامه می‌دهد.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

`.env` را با `API_ID` / `API_HASH` / `PHONE` پر کن.

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
| `channel_forward` | پست‌های کانال مبدأ را به کانال شما فوروارد می‌کند |
| `auto_reply` | جواب خودکار به پیام خصوصی (پیش‌فرض خاموش) |

### channel_forward

```json
"channel_forward": {
  "enabled": true,
  "sources": ["@source_channel"],
  "destination": "@your_channel",
  "delay_seconds": 1.5,
  "forward_mode": "forward",
  "album_wait_seconds": 1.2
}
```

- اکانت باید عضو کانال مبدأ باشد و در کانال مقصد حق ارسال داشته باشد.
- `forward_mode`: `forward` (با برچسب فوروارد) یا `copy` (بدون فوروارد).
- آلبوم‌های چندرسانه‌ای پشتیبانی می‌شوند.

### افزودن ماژول جدید

1. پوشه `modules/<name>/module.py` با کلاسی که از `BaseModule` ارث می‌برد
2. ثبت در `app/loader.py` → `MODULE_REGISTRY`
3. بخش تنظیمات در `config/modules.json` با `"enabled": true/false`

اگر import یا `start()` ماژول شکست بخورد، فقط همان ماژول رد می‌شود.

## Safety notes

- این client غیررسمی (userbot) است؛ اتوماسیون زیاد ریسک محدودیت/بن دارد.
- برای فوروارد: تأخیر (`delay_seconds`) را خیلی کم نگذار.
- Secretها (`.env`, `*.session`) در گیت نیستند.

## Legacy

`reply_bot.py` حذف شده؛ معادل آن ماژول `auto_reply` است (در صورت نیاز روشن کن).
