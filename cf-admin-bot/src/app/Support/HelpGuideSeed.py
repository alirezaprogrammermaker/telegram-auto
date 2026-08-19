"""Default help-guide content seeded into D1."""
from __future__ import annotations

from typing import Any

SEED_TS = "2026-08-19T00:00:00+00:00"

DEFAULT_GUIDES: list[dict[str, Any]] = [
    # --- discovery ---
    {
        "category": "discovery",
        "key": "index",
        "title": "نگاه کلی",
        "emoji": "🧺",
        "order_index": 0,
        "content": (
            "همهٔ کنترل کشف/pool/inspect/harvest/linkdir از همین ربات است.\n"
            "نقش <code>linkdir</code>: طی روز لینکدونی جدید کشف می‌کند (D1).\n"
            "تغییر پروفایل از ران بعدی اثر دارد (در صورت نیاز ریستارت).\n"
            "دیگر لازم نیست به PV اکانت‌ها پیام بدهی."
        ),
    },
    {
        "category": "discovery",
        "key": "pool",
        "title": "Pool",
        "emoji": "📦",
        "order_index": 10,
        "content": (
            "<b>Pool گروه</b>\n"
            "• وضعیت pool — شمارش raw/ok/approved\n"
            "• لیست raw / ok / approved\n"
            "• تأیید یا رد گروه با ref\n"
            "• to-promo — انتقال گروه approved به مسیر promo\n"
            "• ادغام raw: منوی <b>عملیات → ادغام pool</b>"
        ),
    },
    {
        "category": "discovery",
        "key": "inspect",
        "title": "Inspect",
        "emoji": "🔎",
        "order_index": 20,
        "content": (
            "<b>Inspect (group_inspect)</b>\n"
            "• dry_run — toggle تست بدون جوین\n"
            "• pause / resume\n"
            "• بودجه روزانه جوین (۱–۱۲)\n"
            "• dump state — وضعیت runtime از GHA"
        ),
    },
    {
        "category": "discovery",
        "key": "harvest",
        "title": "Harvest",
        "emoji": "🌾",
        "order_index": 30,
        "content": (
            "<b>Harvest (link_harvest)</b>\n"
            "• pause / resume\n"
            "• add/remove لینکدونی\n"
            "• catchup (۰–۲۰۰) — پیام‌های قدیمی"
        ),
    },
    {
        "category": "discovery",
        "key": "linkdir",
        "title": "Linkdir",
        "emoji": "🔗",
        "order_index": 40,
        "content": (
            "<b>Linkdir (کاتالوگ D1)</b>\n"
            "• شمارش کاتالوگ\n"
            "• اجرای linkdir (dispatch GHA)\n"
            "• pause / resume\n"
            "• نقش: <code>linkdir</code> یا <code>full</code>"
        ),
    },
    # --- promo ---
    {
        "category": "promo",
        "key": "index",
        "title": "نگاه کلی",
        "emoji": "📣",
        "order_index": 0,
        "content": (
            "مسیرها، dry_run، pause/resume، mode، صف و safety از همین ربات.\n"
            "ارسال واقعی روی رانر GitHub Actions.\n"
            "بعد از تغییر پروفایل در صورت نیاز از <b>عملیات → ریستارت</b> استفاده کن.\n"
            "دیگر لازم نیست به PV اکانت promo پیام بدهی."
        ),
    },
    {
        "category": "promo",
        "key": "routes",
        "title": "مسیرها",
        "emoji": "🛤",
        "order_index": 10,
        "content": (
            "<b>مسیرهای promo</b>\n"
            "• add — <code>@channel @g1,@g2</code>\n"
            "• remove / pause / resume per-route\n"
            "• mode مسیر — <code>@channel forward|copy</code>\n"
            "• group add/remove\n"
            "• لیست گروه‌ها — یک مسیر یا <code>همه</code>\n"
            "• mode سراسری — دکمه‌های mode: forward / copy\n"
            "• pause/resume سراسری — همه مسیرها"
        ),
    },
    {
        "category": "promo",
        "key": "safety",
        "title": "Safety",
        "emoji": "🛡",
        "order_index": 20,
        "content": (
            "<b>Safety / pacing</b>\n"
            "• safety پروفایل — تنظیمات ذخیره‌شده\n"
            "• safety dump — وضعیت runtime (circuit/صف) از GHA\n"
            "• delay — <code>70 190</code> (ثانیه)\n"
            "• budget — <code>daily 28 hourly 5</code>\n"
            "• windows — <code>09:30-13:00,16:00-22:00</code>\n"
            "• cooldown — دقیقه بین ارسال به یک گروه\n"
            "• tz — <code>Asia/Tehran</code>"
        ),
    },
    {
        "category": "promo",
        "key": "queue",
        "title": "صف",
        "emoji": "📥",
        "order_index": 30,
        "content": (
            "<b>صف promo</b>\n"
            "• وضعیت صف — pending count از runner\n"
            "• پاک کردن صف — clear pending\n"
            "نتیجه از GHA به همین چت برمی‌گردد."
        ),
    },
    # --- forward ---
    {
        "category": "forward",
        "key": "index",
        "title": "نگاه کلی",
        "emoji": "📨",
        "order_index": 0,
        "content": (
            "کنترل کامل <code>channel_forward</code> از همین ربات.\n"
            "ارسال واقعی روی رانر؛ بعد از تغییر پروفایل در صورت نیاز ریستارت کن.\n"
            "دیگر لازم نیست به PV اکانت forward پیام بدهی."
        ),
    },
    {
        "category": "forward",
        "key": "routes",
        "title": "مسیرها",
        "emoji": "🛤",
        "order_index": 10,
        "content": (
            "<b>مسیرهای forward</b>\n"
            "• add — <code>@source @dest</code>\n"
            "• remove / set مقصد\n"
            "• pause / resume per-route\n"
            "• mode — forward|copy\n"
            "• visibility — public|private\n"
            "• claim — مالکیت مسیر\n"
            "• dest add/remove — چند مقصد\n"
            "• import — <code>@a,@b @dest</code>"
        ),
    },
    {
        "category": "forward",
        "key": "filter",
        "title": "فیلتر",
        "emoji": "🛠",
        "order_index": 20,
        "content": (
            "<b>فیلتر متن (copy mode)</b>\n"
            "• on/off / clear\n"
            "• toggle links, mentions, hashtags\n"
            "• prefix / suffix / block\n"
            "• media filter — allow/deny types\n"
            "• dedup — on/off + window hours"
        ),
    },
    {
        "category": "forward",
        "key": "schedule",
        "title": "زمان‌بندی",
        "emoji": "🗓",
        "order_index": 30,
        "content": (
            "<b>Schedule</b>\n"
            "• on/off / clear\n"
            "• tz — <code>Asia/Tehran</code>\n"
            "• days — <code>sat,sun,mon</code>\n"
            "• hours — <code>09:00-12:00,18:00-22:00</code>\n"
            "• delivery — pin, button, sync"
        ),
    },
    {
        "category": "forward",
        "key": "queue",
        "title": "صف",
        "emoji": "📥",
        "order_index": 40,
        "content": (
            "<b>صف انتشار</b>\n"
            "• وضعیت صف / پاک کردن pending\n"
            "نتیجه از GHA به همین چت برمی‌گردد."
        ),
    },
    # --- general ---
    {
        "category": "general",
        "key": "index",
        "title": "نگاه کلی",
        "emoji": "📖",
        "order_index": 0,
        "content": (
            "ربات مدیریت <b>telegram-auto</b> — control-plane مرکزی.\n"
            "فقط ادمین با این ربات چت می‌کند؛ اکانت‌های Telethon نباید /start بزنند.\n"
            "منو: وضعیت، اکانت‌ها، کشف، تبلیغ، فوروارد، عملیات، تنظیمات، راهنما."
        ),
    },
    {
        "category": "general",
        "key": "accounts",
        "title": "اکانت‌ها",
        "emoji": "👥",
        "order_index": 10,
        "content": (
            "<b>مدیریت اکانت</b>\n"
            "• افزودن — scaffold + لاگین OTP روی GHA\n"
            "• لاگین موجود — re-login\n"
            "• enable/disable، rename، تغییر role\n"
            "• logout / delete\n"
            "• هر admin فقط اکانت‌های خودش را می‌بیند."
        ),
    },
    {
        "category": "general",
        "key": "ops",
        "title": "عملیات GHA",
        "emoji": "🛠",
        "order_index": 20,
        "content": (
            "<b>GitHub Actions</b>\n"
            "• اجرا — dispatch workflow اکانت\n"
            "• کنسل — توقف run فعال\n"
            "• ریستارت — run جدید\n"
            "• ادغام pool — merge-group-pool.yml"
        ),
    },
    {
        "category": "general",
        "key": "auth",
        "title": "دسترسی",
        "emoji": "🔐",
        "order_index": 30,
        "content": (
            "<b>احراز هویت</b>\n"
            "• مهمان: فقط /start و /whoami\n"
            "• ارتقا به admin: ارسال رمز مدیر\n"
            "• ADMIN_IDS — bootstrap admin\n"
            "• /whoami — شناسه تلگرام و نقش"
        ),
    },
]

CATEGORY_META: dict[str, dict[str, str]] = {
    "discovery": {"emoji": "🧺", "title": "کشف"},
    "promo": {"emoji": "📣", "title": "تبلیغ"},
    "forward": {"emoji": "📨", "title": "فوروارد"},
    "general": {"emoji": "📖", "title": "عمومی"},
}
