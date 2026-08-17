from __future__ import annotations

MESSAGES: dict[str, str] = {
    # auth / guest
    "auth.welcome_guest": (
        "👋 <b>ربات مدیر telegram-auto</b>\n"
        "────────────\n"
        "برای ورود، <b>رمز مدیر</b> را بفرست.\n"
        "chat_id: <code>{chat_id}</code>\n\n"
        "تا وقتی وارد نشدی فقط `/start` و `/whoami` فعال است."
    ),
    "auth.welcome_admin": (
        "✅ سلام <b>{name}</b> — نقش: <code>admin</code>\n"
        "────────────\n"
        "از منوی پایین یک بخش را انتخاب کن.\n"
        "اکانت‌های Telethon لازم نیست این ربات را استارت کنند."
    ),
    "auth.promoted": "✅ رمز درست بود. نقش تو الان <b>admin</b> است.",
    "auth.denied": "🔒 دسترسی ندارید.\nبرای مدیر شدن، رمز مدیر را بفرستید.",
    "auth.whoami": (
        "user_id=<code>{user_id}</code>\n"
        "chat_id=<code>{chat_id}</code>\n"
        "role=<code>{role}</code>"
    ),
    # menus
    "menu.btn_status": "📊 وضعیت",
    "menu.btn_accounts": "👥 اکانت‌ها",
    "menu.btn_discovery": "🧺 کشف",
    "menu.btn_promo": "📣 تبلیغ",
    "menu.btn_ops": "🛠 عملیات",
    "menu.btn_settings": "⚙️ تنظیمات",
    "menu.status": (
        "📊 <b>وضعیت</b>\n"
        "────────────\n"
        "فعلاً اسکلت کنترل‌پنل است.\n"
        "بعداً وضعیت GHA / pool / اکانت‌ها اینجا می‌آید."
    ),
    "menu.discovery": (
        "🧺 <b>کشف گروه</b>\n"
        "────────────\n"
        "• Collector — خواندن لینکدونی\n"
        "• Inspector — جوین آهسته + چک ضداسپم\n"
        "• Pool — raw / ok / approved / rejected"
    ),
    "menu.promo": (
        "📣 <b>تبلیغ</b>\n"
        "────────────\n"
        "مسیرها، صف، dry-run، بودجه ارسال"
    ),
    "menu.ops": (
        "🛠 <b>عملیات</b>\n"
        "────────────\n"
        "Dispatch / Restart / Cancel / Merge pool"
    ),
    "menu.settings_header": (
        "⚙️ <b>تنظیمات</b>\n"
        "────────────\n"
        "کاربران: {total} | ادمین: {admin} | عادی: {user}\n\n"
        "<b>ادمین‌ها:</b>"
    ),
    "menu.settings_no_admins": "— هنوز ادمینی نیست",
    "menu.settings_admin_line": "• {label} (<code>{telegram_id}</code>)",
    "menu.unknown": (
        "دستور ناشناخته.\n"
        "/start برای منو، یا از دکمه‌های پایین استفاده کن."
    ),
    "menu.help": (
        "راهنما:\n"
        "/start — منوی اصلی\n"
        "/whoami — شناسه تلگرام\n"
        "/admins — لیست ادمین‌ها\n"
        "اکانت‌ها — افزودن و لاگین روی GHA\n"
        "/cancel — لغو ویزارد\n"
        "رمز مدیر را فقط یک‌بار برای ارتقا بفرست."
    ),
    # accounts wizard
    "accounts.menu": (
        "👥 <b>اکانت‌ها</b>\n"
        "────────────\n"
        "لاگین واقعی فقط روی GitHub Actions (IP رانر) انجام می‌شود.\n"
        "یک گزینه را انتخاب کن."
    ),
    "accounts.btn_list": "📋 لیست",
    "accounts.btn_add": "➕ افزودن",
    "accounts.btn_login": "🔑 لاگین موجود",
    "accounts.btn_cancel": "❌ انصراف",
    "accounts.btn_back": "⬅️ منوی اصلی",
    "accounts.btn_confirm": "✅ تأیید و ارسال OTP",
    "accounts.btn_check_run": "🔄 وضعیت GHA",
    "accounts.btn_need_2fa": "🔐 دارم 2FA",
    "accounts.role_promo": "promo",
    "accounts.role_forward": "forward",
    "accounts.role_collector": "collector",
    "accounts.role_inspector": "inspector",
    "accounts.role_full": "full",
    "accounts.list_header": "📋 <b>اکانت‌های رجیستری</b>\n────────────",
    "accounts.list_empty": "هنوز اکانتی در رجیستری نیست.",
    "accounts.list_line": (
        "• <code>{id}</code> — {label}\n"
        "  enabled={enabled} | status={status} | {phone}"
    ),
    "accounts.ask_id": (
        "شناسه اکانت را بفرست.\n"
        "فرمت: حروف کوچک انگلیسی، شروع با حرف، حداکثر ۳۲ کاراکتر.\n"
        "مثال: <code>promo2</code>\n\n"
        "/cancel برای انصراف"
    ),
    "accounts.ask_role": "نقش اکانت را انتخاب کن:",
    "accounts.ask_phone": (
        "شماره را با کد کشور بفرست (E.164).\n"
        "مثال: <code>+98912xxxxxxx</code>\n\n"
        "/cancel برای انصراف"
    ),
    "accounts.ask_login_id": (
        "شناسه اکانتی که از قبل scaffold شده را بفرست.\n"
        "مثال: <code>promo1</code>\n\n"
        "/cancel برای انصراف"
    ),
    "accounts.confirm": (
        "تأیید نهایی:\n"
        "• id: <code>{account_id}</code>\n"
        "• role: <code>{role}</code>\n"
        "• phone: <code>{phone}</code>\n\n"
        "با تأیید: scaffold روی GitHub + ارسال OTP روی رانر."
    ),
    "accounts.confirm_login": (
        "لاگین اکانت موجود:\n"
        "• id: <code>{account_id}</code>\n"
        "• phone: <code>{phone}</code>\n\n"
        "با تأیید فقط OTP روی رانر ارسال می‌شود (بدون scaffold)."
    ),
    "accounts.sending": (
        "⏳ در حال scaffold/دیسپچ send برای <code>{account_id}</code>...\n"
        "کد تلگرام را همین‌جا بفرست وقتی رسید."
    ),
    "accounts.await_otp": (
        "✅ درخواست OTP ثبت شد برای <code>{account_id}</code> ({phone}).\n"
        "کد را همین‌جا بفرست.\n"
        "اگر اکانت رمز ابری دارد بعداً «دارم 2FA» را بزن.\n"
        "run: {run_id}"
    ),
    "accounts.otp_saved": (
        "OTP ذخیره شد. در حال complete روی GHA برای <code>{account_id}</code>..."
    ),
    "accounts.ask_2fa": (
        "رمز ابری / 2FA تلگرام را بفرست.\n"
        "فقط در همین چت؛ بعد از لاگین پاک می‌شود.\n"
        "/cancel برای انصراف"
    ),
    "accounts.twofa_saved": (
        "2FA ذخیره شد. دوباره complete برای <code>{account_id}</code> دیسپچ شد."
    ),
    "accounts.run_status": (
        "GHA status=<code>{status}</code> conclusion=<code>{conclusion}</code>\n"
        "{url}"
    ),
    "accounts.done": (
        "✅ لاگین موفق برای <code>{account_id}</code>.\n"
        "سشن‌سکرت باید ست شده باشد.\n"
        "برای اجرا: enable در accounts.json + push + dispatch."
    ),
    "accounts.failed": (
        "❌ لاگین ناموفق برای <code>{account_id}</code>.\n"
        "جزئیات: {error}\n"
        "اگر خطای 2FA بود، «دارم 2FA» را بزن و دوباره تلاش کن."
    ),
    "accounts.cancelled": "ویزارد اکانت لغو شد.",
    "accounts.invalid_id": "شناسه نامعتبر است. مثال معتبر: <code>promo2</code>",
    "accounts.invalid_role": "نقش نامعتبر است. از دکمه‌ها استفاده کن.",
    "accounts.invalid_phone": "شماره نامعتبر است. مثال: <code>+98912xxxxxxx</code>",
    "accounts.invalid_otp": "کد OTP نامعتبر است (۴ تا ۸ رقم).",
    "accounts.invalid_2fa": "رمز 2FA خالی است.",
    "accounts.missing_github": (
        "تنظیمات GitHub ناقص است.\n"
        "روی Worker این سکرت‌ها لازم است: "
        "<code>GITHUB_TOKEN</code>, <code>GITHUB_REPO</code>, <code>BRIDGE_TOKEN</code>"
    ),
    "accounts.account_missing": "این اکانت در <code>config/accounts.json</code> نیست.",
    "accounts.exists": "این اکانت از قبل هست. برای لاگین از «لاگین موجود» استفاده کن.",
    "accounts.error": "خطا: {error}",
    "accounts.no_session": "سشن لاگین فعالی نیست. از منوی اکانت‌ها شروع کن.",
    # system
    "health.hint": "POST Telegram updates to /webhook",
    "error.no_token": "no_token",
    "error.unauthorized": "unauthorized",
    "error.bad_json": "bad_json",
    "error.not_found": "not_found",
}
