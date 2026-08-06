# Telegram Auto — «Easy free seen»

یک **user-client** تلگرام روی Telethon. با اکانت شخصی کار می‌کند (نه ربات BotFather)، و هر قابلیت یک ماژول مستقل است: اگر ماژولی خطا بدهد یا خاموش باشد، بقیهٔ برنامه به کارش ادامه می‌دهد.

- زبان: Python 3.12+
- کتابخانه: [Telethon](https://docs.telethon.dev) (MTProto)
- اجرا: لوکال، VPS، یا GitHub Actions

---

## فهرست

- [ساختار پروژه](#ساختار-پروژه)
- [راه‌اندازی سریع](#راهاندازی-سریع)
- [لاگین](#لاگین)
- [ماژول‌ها](#ماژولها)
- [دستورات مدیر](#دستورات-مدیر)
- [مالکیت و حریم خصوصی مسیرها](#مالکیت-و-حریم-خصوصی-مسیرها)
- [اجرا روی GitHub Actions](#اجرا-روی-github-actions)
- [ایمنی در برابر محدودیت و بن](#ایمنی-در-برابر-محدودیت-و-بن)
- [افزودن ماژول جدید](#افزودن-ماژول-جدید)
- [عیب‌یابی](#عیبیابی)
- [امنیت](#امنیت)

---

## ساختار پروژه

```
main.py                     ورودی برنامه: اتصال، لود ماژول‌ها، اجرا تا توقف
login.py                    لاگین OTP و رمز دومرحله‌ای
app/
  config.py                 خواندن .env و config/modules.json
  client.py                 ساخت TelegramClient با تنظیمات ضد فلاد
  loader.py                 رجیستری ماژول‌ها و ایزوله‌سازی خطا
  runtime.py                روشن/خاموش/ری‌لود ماژول‌ها + ذخیرهٔ کانفیگ
  base.py                   قرارداد BaseModule
  singleton.py              قفل تک‌نمونه‌بودن (telegram_auto.lock)
  logging_setup.py          لاگ کنسول + فایل چرخشی در logs/
  storage.py                خواندن/نوشتن امن JSON
  progress.py               پیام پیشرفت قابل ویرایش برای دستورات طولانی
  stats.py                  آمار روزانه در data/stats.json
modules/
  auto_reply/module.py      پاسخ خودکار + پنل دستورات مدیر
  channel_forward/
    module.py               فوروارد/کپی بین کانال‌ها
    filters.py              فیلتر متن و بلاک‌لیست کلمات
    schedule.py             زمان‌بندی هفتگی با منطقهٔ زمانی
    queue.py                صف انتشار برای خارج از بازهٔ مجاز
    access.py               مالکیت و public/private بودن مسیرها
scripts/
  export_session_b64.py     تبدیل فایل سشن به base64 برای Secret
  set_github_secrets.py     ست کردن Secretهای گیت‌هاب از .env
config/modules.json         تنظیمات ماژول‌ها (قابل ویرایش از داخل چت)
data/                       وضعیت زمان اجرا (گیت‌نشده)
logs/                       لاگ‌ها (گیت‌نشده)
```

---

## راه‌اندازی سریع

```bash
python -m venv .venv
.venv\Scripts\activate        # ویندوز
pip install -r requirements.txt
copy .env.example .env         # لینوکس: cp .env.example .env
```

`.env` را پر کن:

| کلید | لازم | توضیح |
|------|------|-------|
| `API_ID` | بله | از [my.telegram.org](https://my.telegram.org) |
| `API_HASH` | بله | از my.telegram.org |
| `PHONE` | برای لاگین | با کد کشور، مثل `+98912...` |
| `ADMIN_PASSWORD` | بله | کلمه رمزی که با آن مدیر می‌شوی |
| `SESSION_NAME` | اختیاری | پیش‌فرض `easy_seen` |
| `ADMIN_IDS` | اختیاری | آیدی‌های عددی مدیر دائمی، با کاما |
| `LOG_LEVEL` | اختیاری | پیش‌فرض `INFO` |
| `MAX_RUNTIME_SECONDS` | اختیاری | خروج تمیز بعد از این مدت؛ `0` یعنی بی‌نهایت |
| `FLOOD_SLEEP_THRESHOLD` | اختیاری | تا این تعداد ثانیه، FloodWait را خودش صبر می‌کند (پیش‌فرض `120`) |

سپس:

```bash
python main.py
```

فقط **یک نمونه** همزمان مجاز است؛ قفل `telegram_auto.lock` جلوی اجرای دوم را می‌گیرد.

---

## لاگین

```bash
python login.py send             # ارسال کد به تلگرام
python login.py sign_in 12345    # وارد کردن کد
python login.py sign_in 12345 <رمز-دومرحله‌ای>   # اگر 2FA داری
```

خروجی JSON است و فایل `easy_seen.session` ساخته می‌شود. این فایل = دسترسی کامل به اکانت؛ هرگز commit نکن (در `.gitignore` هست).

---

## ماژول‌ها

تنظیمات در `config/modules.json`. هر ماژول کلید `enabled` دارد.

### `auto_reply`

فقط به مدیرها جواب می‌دهد. کسی که رمز را در چت خصوصی بفرستد مدیر می‌شود و در `data/admins.json` ذخیره می‌شود.

```json
"auto_reply": {
  "enabled": true,
  "reply_text": "سلام! پیام‌ات رسید ✓",
  "cooldown_seconds": 0,
  "require_admin": true,
  "show_typing": true,
  "typing_seconds": 1.5,
  "skip_media_only": true,
  "allow_saved_messages": true,
  "delete_password_message": true,
  "send_help_on_login": true,
  "logout_command": "/logout",
  "admins_file": "data/admins.json"
}
```

| کلید | کار |
|------|-----|
| `require_admin` | اگر `false` باشد به همه جواب می‌دهد (توصیه نمی‌شود) |
| `cooldown_seconds` | حداقل فاصله بین دو پاسخ به یک نفر |
| `show_typing` | نمایش «در حال نوشتن…» قبل از پاسخ |
| `skip_media_only` | نادیده‌گرفتن پیام‌های بدون متن |
| `delete_password_message` | پاک‌کردن پیام حاوی رمز بعد از ورود |

رمز از `ADMIN_PASSWORD` در محیط خوانده می‌شود و اگر نبود از `admin_password` در کانفیگ. پیام‌ها Seen می‌شوند.

**مدیر دائمی:** آیدی‌های داخل `ADMIN_IDS` همیشه مدیرند و با `/logout` خارج نمی‌شوند. این برای اجرای ابری لازم است، چون آنجا `data/` هر بار خالی شروع می‌شود.

### `channel_forward`

هر پست کانال مبدأ را به مقصد می‌برد. چند مسیر مستقل پشتیبانی می‌شود.

```json
"channel_forward": {
  "enabled": true,
  "delay_seconds": 1.5,
  "forward_mode": "copy",
  "album_wait_seconds": 1.2,
  "skip_silent": false,
  "routes": [
    {
      "source": "@channe_l_1",
      "destination": "@channe_l_2",
      "enabled": true,
      "forward_mode": "copy",
      "owner_id": null,
      "visibility": "public",
      "filter": {
        "enabled": true,
        "remove_links": false,
        "remove_mentions": false,
        "remove_hashtags": false,
        "remove_ids": false,
        "prefix": "",
        "suffix": "",
        "collapse_whitespace": true,
        "block_enabled": false,
        "block_words": []
      },
      "schedule": {
        "enabled": false,
        "timezone": "Asia/Tehran",
        "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        "windows": []
      }
    }
  ]
}
```

- `forward_mode: copy` پست را بازنشر می‌کند بدون برچسب «Forwarded from» — یعنی نام کانال مبدأ دیده نمی‌شود. `forward` برچسب را نگه می‌دارد.
- اگر فیلتر روشن باشد، ارسال به‌اجبار `copy` می‌شود، چون متن باید قابل ویرایش باشد.
- آلبوم‌ها با `album_wait_seconds` جمع و یک‌جا فرستاده می‌شوند.
- خارج از بازهٔ زمان‌بندی، پست‌ها در `data/publish_queue.json` صف می‌شوند و سر بازهٔ مجاز منتشر می‌گردند.
- هنگام شروع، عضویت در مبدأ و حق پست در مقصد بررسی می‌شود.

---

## دستورات مدیر

همه در **چت خصوصی** با اکانت برنامه. اول رمز را بفرست تا مدیر شوی.

### عمومی

| دستور | کار |
|-------|-----|
| `<کلمه رمز>` | فعال‌سازی دسترسی مدیر |
| `/login` | راهنمای ورود |
| `/login <رمز>` | ورود با رمز |
| `/logout` | خروج از حالت مدیر |
| `/help` | لیست کامل دستورات |
| `/stats` | آمار امروز و دیروز (فقط مسیرهای قابل‌مشاهدهٔ تو) |

### مدیریت ماژول

| دستور | کار |
|-------|-----|
| `/modules` | وضعیت همهٔ ماژول‌ها |
| `/module on <name>` | روشن کردن |
| `/module off <name>` | خاموش کردن |
| `/module reload <name>` | ری‌لود با کانفیگ جدید |

`auto_reply` محافظت‌شده است و از داخل چت نمی‌شود خاموشش کرد (وگرنه راه برگشت بسته می‌شود).

### مسیرهای فوروارد

| دستور | کار |
|-------|-----|
| `/forward status` | مسیرهای قابل‌مشاهده + تست دسترسی |
| `/forward mine` | فقط مسیرهای خودت |
| `/forward add <مبدأ> <مقصد>` | افزودن مسیر (خصوصی برای خودت) |
| `/forward remove <مبدأ>` | حذف مسیر |
| `/forward set <مبدأ> <مقصد>` | تغییر مقصد |
| `/forward mode <مبدأ> copy\|forward` | حالت ارسال |
| `/forward visibility <مبدأ> public\|private` | عمومی/خصوصی کردن |
| `/forward claim <مبدأ>` | مالک شدن مسیر بدون مالک |

### فیلتر متن

| دستور | کار |
|-------|-----|
| `/forward filter <مبدأ>` | نمایش وضعیت فیلتر |
| `/forward filter <مبدأ> on\|off` | روشن/خاموش |
| `/forward filter <مبدأ> links on\|off` | حذف لینک‌ها |
| `/forward filter <مبدأ> mentions on\|off` | حذف منشن‌ها |
| `/forward filter <مبدأ> hashtags on\|off` | حذف هشتگ‌ها |
| `/forward filter <مبدأ> ids on\|off` | حذف آیدی عددی |
| `/forward filter <مبدأ> prefix <متن\|off>` | متن ابتدای پست (`\n` = خط جدید) |
| `/forward filter <مبدأ> suffix <متن\|off>` | متن انتهای پست |
| `/forward filter <مبدأ> block on\|off` | بلاک‌لیست کلمات |
| `/forward filter <مبدأ> block add\|remove <کلمه>` | مدیریت کلمات |
| `/forward filter <مبدأ> block clear` | پاک‌کردن لیست |
| `/forward filter <مبدأ> clear` | ریست کل فیلتر |

پستی که شامل کلمهٔ بلاک‌شده باشد اصلاً ارسال نمی‌شود و در آمار `blocked` ثبت می‌گردد.

### زمان‌بندی

| دستور | کار |
|-------|-----|
| `/forward schedule <مبدأ>` | نمایش وضعیت |
| `/forward schedule <مبدأ> on\|off` | روشن/خاموش |
| `/forward schedule <مبدأ> tz Asia/Tehran` | منطقهٔ زمانی |
| `/forward schedule <مبدأ> days sat,sun,mon` | روزهای مجاز |
| `/forward schedule <مبدأ> hours 09:00-12:00,18:00-22:00` | بازه‌های ساعت |
| `/forward schedule <مبدأ> clear` | ریست |

برای روشن‌کردن زمان‌بندی اول باید حداقل یک بازهٔ ساعت تعریف شود.

---

## مالکیت و حریم خصوصی مسیرها

هر مسیر یک `owner_id` و یک `visibility` دارد.

- مسیری که با `/forward add` می‌سازی **خصوصی** است و فقط خودت می‌بینی
- مدیرهای دیگر آن را در `status`، `filter`، `schedule` و آمار مسیرها نمی‌بینند
- با `public` کردن، بقیه می‌بینند ولی **فقط مالک** می‌تواند ویرایش یا حذف کند
- مسیرهای قدیمی بدون مالک، عمومی حساب می‌شوند تا کسی با `/forward claim` مالکشان شود

---

## اجرا روی GitHub Actions

فایل: `.github/workflows/run-every-6h.yml`

### چرا public

روی مخزن **public**، runnerهای استاندارد گیت‌هاب **رایگان و بدون سقف دقیقه** هستند. روی private از سهمیهٔ ماهانه (۲۰۰۰ دقیقه در پلن Free) کم می‌شود و خیلی زود تمام می‌شود.

### مدل پیوستگی

| محدودیت | مقدار |
|---------|-------|
| حداکثر عمر هر job | ۶ ساعت (سقف گیت‌هاب) |
| خروج تمیز برنامه | `MAX_RUNTIME_SECONDS=21000` ≈ ۵ساعت و ۵۰ دقیقه |
| cron | هر ۱۰ دقیقه |

روش کار: گروه `concurrency` با `cancel-in-progress: false` اجازه می‌دهد فقط **یک run فعال** باشد و run بعدی در **صف** بماند. گیت‌هاب همیشه یک run معلق نگه می‌دارد. لحظه‌ای که run فعال تمام شد یا کنسل شد، همان run معلق بلافاصله شروع می‌شود.

یعنی وقفه = فقط زمان راه‌اندازی job (حدود ۱ تا ۴ دقیقه)، نه انتظار تا cron بعدی.

### Secrets

در `Settings → Secrets and variables → Actions`:

| Secret | مقدار |
|--------|--------|
| `API_ID` | همان `.env` |
| `API_HASH` | همان `.env` |
| `ADMIN_PASSWORD` | رمز مدیر |
| `TELEGRAM_SESSION_B64` | خروجی `python scripts/export_session_b64.py` |
| `ADMIN_IDS` | اختیاری، آیدی عددی مدیر دائمی |

میان‌بر برای ست‌کردن همه از روی `.env` و فایل سشن:

```bash
python scripts/set_github_secrets.py
```

کد public است، ولی Secretها هرگز در مخزن نیستند و در لاگ‌ها ماسک می‌شوند.

### اجرا

- خودکار: cron هر ۱۰ دقیقه یک standby می‌سازد
- دستی: `Actions → run-every-6h → Run workflow`
- یا: `gh workflow run run-every-6h.yml`

### محدودیت‌های واقعی

- گیت‌هاب گاهی jobهای طولانی را زودتر از ۶ ساعت می‌بندد؛ روی «۶ ساعت کامل» حساب نکن
- زمان‌بندی cron ممکن است چند دقیقه تأخیر بخورد
- اگر مخزن ۶۰ روز هیچ فعالیتی نداشته باشد، گیت‌هاب workflowهای زمان‌بندی‌شده را غیرفعال می‌کند
- هر run روی یک IP دیتاسنتر متفاوت اجرا می‌شود (بخش بعد را بخوان)

> **هرگز** همزمان با run فعال، `main.py` را لوکال اجرا نکن. تلگرام سشنی را که هم‌زمان از دو IP استفاده شود باطل می‌کند و باید دوباره لاگین کنی (`AuthKeyDuplicatedError`).

---

## ایمنی در برابر محدودیت و بن

اکانت کاربری (userbot) رسماً توسط تلگرام پشتیبانی نمی‌شود. این پروژه چند محافظ دارد، ولی ریسک صفر نمی‌شود.

### محافظت‌های داخل کد

- **FloodWait**: خطاهای فلاد در هر دو ماژول گرفته می‌شوند و برنامه به‌جای تلاش دوباره، همان مدت صبر می‌کند. آستانهٔ صبر خودکار Telethon روی `FLOOD_SLEEP_THRESHOLD` (پیش‌فرض ۱۲۰ ثانیه) تنظیم شده
- **فاصلهٔ بین ارسال‌ها**: `delay_seconds` بین پیام‌ها رعایت می‌شود
- **fingerprint ثابت**: `device_model` و `app_version` بین همهٔ لاگین‌ها ثابت‌اند؛ تغییر مداوم آن‌ها علامت مشکوکی است
- **خاموشی تمیز**: سیگنال `SIGTERM` (که هنگام کنسل شدن job فرستاده می‌شود) به قطع اتصال مرتب تبدیل می‌شود، نه قطع ناگهانی
- **تک‌نمونه**: قفل فایل جلوی دو اتصال هم‌زمان روی یک ماشین را می‌گیرد

### کارهایی که خودت باید رعایت کنی

- به گروه/کانالی که عضو نیستی پیام انبوه نده؛ مبدأ باید کانالی باشد که واقعاً عضوش هستی
- `cooldown_seconds` را صفر نگذار اگر `require_admin` را خاموش کردی
- تعداد مسیرها و حجم فوروارد را ناگهانی بالا نبر؛ رشد تدریجی کم‌ریسک‌تر است
- محتوای اسپم، تبلیغ انبوه یا کپی کانال‌های دیگر بدون اجازه، گزارش کاربران را بالا می‌برد — گزارش کاربر مهم‌ترین دلیل بن است، نه خود اتوماسیون

### ریسک خاص GitHub Actions

هر run روی یک ماشین و **IP متفاوت** در دیتاسنتر اجرا می‌شود. اگر runها زیاد قطع و وصل شوند، تلگرام یک الگوی «ورود مکرر از IPهای مختلف دیتاسنتری» می‌بیند که برای اکانت‌های تازه یا بدون شماره معتبر، ریسک محدودیت دارد.

برای کم‌کردن این ریسک:

- cron را از این کمتر نکن (هر ۱۰ دقیقه فقط یک standby می‌سازد، نه یک اتصال جدید)
- اگر اکانت پیام هشدار گرفت، چند روز فقط لوکال اجرا کن
- برای استفادهٔ جدی و بلندمدت، یک VPS با IP ثابت پایدارتر و کم‌ریسک‌تر از Actions است

---

## افزودن ماژول جدید

1. پوشهٔ `modules/<name>/` بساز و در `module.py` کلاسی از `BaseModule` ارث ببر:

```python
from app.base import BaseModule

class MyModule(BaseModule):
    name = "my_module"

    async def start(self) -> None:
        ...   # ثبت هندلرها

    async def stop(self) -> None:
        ...   # پاک‌سازی
```

2. در `app/loader.py` به `MODULE_REGISTRY` اضافه کن.
3. در `config/modules.json` تنظیماتش را با `"enabled": true` بگذار.

خطای `start` ماژول توسط loader گرفته می‌شود و بقیهٔ برنامه سالم می‌ماند.

---

## عیب‌یابی

| نشانه | علت | راه‌حل |
|-------|-----|--------|
| `AuthKeyDuplicatedError` | سشن هم‌زمان از دو IP استفاده شده | فایل `.session` را پاک کن، دوباره `login.py` را اجرا کن، بعد Secret را با `set_github_secrets.py` به‌روز کن |
| `Another instance is already running` | قفل باقی‌مانده از اجرای قبلی | پروسهٔ قبلی را ببند یا `telegram_auto.lock` را پاک کن |
| `Session is not authorized` | فایل سشن نیست یا باطل شده | `python login.py send` سپس `sign_in` |
| اکانت آفلاین است ولی workflow سبز است | مرحلهٔ `Run app` هنوز به اتصال نرسیده | ۱ تا ۴ دقیقه صبر کن؛ لاگ job را ببین |
| بعد از restart باید دوباره رمز بفرستم | `data/admins.json` روی runner خالی است | آیدی عددی خودت را در Secret `ADMIN_IDS` بگذار |
| `channel_forward.routes is empty` | هیچ مسیری تعریف نشده | `/forward add @src @dst` |
| منطقهٔ زمانی روی ویندوز کار نمی‌کند | دیتابیس tz ندارد | `pip install tzdata` (در `requirements.txt` هست) |

لاگ‌ها: کنسول و `logs/app.log` (چرخشی، ۳ نسخهٔ پشتیبان).

---

## امنیت

- `.env`، `*.session`، `data/` و `logs/` در `.gitignore` هستند و نباید commit شوند
- فایل سشن معادل دسترسی کامل به اکانت است؛ مثل رمز با آن رفتار کن
- اگر سشن جایی لو رفت: در تلگرام → Settings → Devices → Terminate، سپس دوباره لاگین کن و Secret را عوض کن
- مخزن public است؛ قبل از هر commit مطمئن شو مقدار حساسی داخل کد یا کانفیگ ننوشته‌ای
