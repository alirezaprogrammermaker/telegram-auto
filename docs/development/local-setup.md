# Local Setup

این راهنما برای توسعه‌دهنده‌ای است که می‌خواهد هم روی runtime اصلی و هم روی `cf-admin-bot` کار کند.

## 1. Root Userbot App

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

بعد `.env` را پر کن و در صورت نیاز:

```bash
python login.py send
python login.py sign_in 12345
python main.py
```

## 2. `cf-admin-bot`

```bash
cd cf-admin-bot
npm install
uv sync
```

برای deploy/dev نیاز به secretهای Worker داری.

## 3. Required Context To Understand Before Editing

- [`../architecture/system-overview.md`](../architecture/system-overview.md)
- [`../configuration/config-sources.md`](../configuration/config-sources.md)
- [`../cf-admin-bot/request-flows.md`](../cf-admin-bot/request-flows.md)

## 4. Safe Development Habits

- session production را همزمان لوکال و روی GHA اجرا نکن
- تغییر متن UI را در `lang/fa/messages.py` انجام بده
- منطق business را تا جای ممکن در serviceها نگه دار
- قبل از migration جدید، جدول‌های فعلی را در docs/schema ببین

## 5. When Working On Which Part

### feature مربوط به runtime userbot
- `app/`
- `modules/`
- `config/`

### feature مربوط به admin UI/control plane
- `cf-admin-bot/src/app/Http/Controllers/`
- `cf-admin-bot/src/app/Services/`
- `cf-admin-bot/src/lang/fa/messages.py`

### feature مربوط به orchestration/deploy
- `.github/workflows/`
- `scripts/`
- `cf-admin-bot/wrangler.jsonc`
