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
        "از منوی پایین همهٔ اکانت‌ها و نقش‌ها را مدیریت کن.\n"
        "لازم نیست به PV اکانت‌های Telethon پیام بدهی."
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
    "menu.btn_forward": "📨 فوروارد",
    "menu.btn_ops": "🛠 عملیات",
    "menu.btn_help": "📖 راهنما",
    "menu.btn_settings": "⚙️ تنظیمات",
    "menu.status": (
        "📊 <b>وضعیت</b>\n"
        "────────────\n"
        "از دکمه وضعیت برای داشبورد اکانت‌ها و آخرین ران GHA استفاده کن."
    ),
    "menu.discovery": (
        "🧺 <b>کشف گروه</b>\n"
        "────────────\n"
        "مدیریت pool، inspect، harvest و linkdir — همهٔ کنترل از این ربات."
    ),
    "menu.promo": (
        "📣 <b>تبلیغ</b>\n"
        "────────────\n"
        "مدیریت مسیرها، safety، صف و پروفایل promo — از همین ربات."
    ),
    "menu.ops": (
        "🛠 <b>عملیات</b>\n"
        "────────────\n"
        "اجرا / کنسل / ریستارت روی GHA و ادغام pool."
    ),
    "menu.settings_header": (
        "⚙️ <b>تنظیمات</b>\n"
        "────────────\n"
        "کاربران: {total} | ادمین: {admin} | عادی: {user}\n\n"
        "<b>ادمین‌ها:</b>"
    ),
    "menu.settings_no_admins": "— هنوز ادمینی نیست",
    "menu.settings_admin_line": "• {label} (<code>{telegram_id}</code>)",
    # ── settings sub-actions ──────────────────────────────────────────
    "settings.btn_demote": "👤 حذف ادمین",
    "settings.btn_stats": "📊 آمار اکانت",
    "settings.btn_modules": "🔧 ماژول‌ها",
    "settings.demote_pick": (
        "👤 <b>حذف ادمین</b>\n"
        "ID یا username ادمینی که می‌خواهی به user تبدیل شود را بنویس:"
    ),
    "settings.demote_no_others": "ادمین دیگری برای حذف وجود ندارد.",
    "settings.demote_bad_id": "ID وارد شده معتبر نیست. عدد telegram_id یا @username وارد کن.",
    "settings.demote_self": "نمی‌توانی خودت را حذف کنی.",
    "settings.demote_not_admin": "این کاربر ادمین نیست.",
    "settings.demote_done": "✅ {label} (<code>{telegram_id}</code>) به user تبدیل شد.",
    "settings.stats_pick": "📊 ID اکانت را برای دریافت آمار وارد کن:",
    "settings.stats_no_accounts": "هیچ اکانتی ثبت نشده.",
    "settings.modules_pick": "🔧 ID اکانت را برای مدیریت ماژول‌ها وارد کن:",
    "settings.modules_no_accounts": "هیچ اکانتی ثبت نشده.",
    "settings.modules_ask_action": (
        "🔧 اکانت <code>{account_id}</code>\n"
        "عملیات را انتخاب کن:"
    ),
    "settings.modules_btn_on": "✅ روشن",
    "settings.modules_btn_off": "🚫 خاموش",
    "settings.modules_btn_reload": "🔄 ریلود",
    "settings.modules_reload_note": "ریلود پیکربندی (patch enabled=true)",
    "settings.modules_done": (
        "✅ <code>{account_id}</code> — ماژول‌ها: <b>{action}</b>\n{detail}"
    ),
    "menu.unknown": (
        "دستور ناشناخته.\n"
        "/start برای منو، یا از دکمه‌های پایین استفاده کن."
    ),
    "menu.help": (
        "راهنما:\n"
        "/start — منوی اصلی\n"
        "/whoami — شناسه تلگرام\n"
        "📖 راهنما — راهنمای پویا از D1\n"
        "/admins — لیست ادمین‌ها\n"
        "/cancel — لغو ویزارد"
    ),
    "help.hub_header": "📖 <b>راهنمای telegram-auto</b>",
    "help.hub_pick": "دسته را انتخاب کن:",
    "help.topic_pick": "یک موضوع را انتخاب کن:",
    "help.btn_cat_general": "❓ 📖 راهنمای عمومی",
    "help.btn_cat_discovery": "❓ 🧺 راهنمای کشف",
    "help.btn_cat_promo": "❓ 📣 راهنمای تبلیغ",
    "help.btn_cat_forward": "❓ 📨 راهنمای فوروارد",
    "help.btn_back_hub": "❓ ⬅️ دسته‌های راهنما",
    "help.btn_back_panel": "❓ ⬅️ بازگشت",
    "help.btn_back_main": "❓ ⬅️ منوی اصلی",
    "help.back_to_panel": "بازگشت به منوی {panel}.",
    "help.unknown": "موضوع نامعتبر — از دکمه‌های ❓ استفاده کن.",
    "help.empty": "راهنمایی ثبت نشده است.",
    "help.stale_keyboard": (
        "کیبورد راهنما منقضی شده.\n"
        "دوباره از منو «📖 راهنما» وارد شو."
    ),
    # accounts wizard
    "accounts.menu": (
        "👥 <b>اکانت‌های من</b>\n"
        "────────────\n"
        "فقط اکانت‌هایی که خودت ساختی اینجا دیده می‌شود.\n"
        "لاگین واقعی فقط روی GitHub Actions (IP رانر) انجام می‌شود.\n"
        "از «مدیریت» می‌توانی لاگ‌اوت یا حذف کنی."
    ),
    "accounts.btn_list": "📋 لیست",
    "accounts.btn_add": "➕ افزودن",
    "accounts.btn_login": "🔑 لاگین موجود",
    "accounts.btn_manage": "🛠 مدیریت",
    "accounts.btn_enable": "✅ فعال‌سازی",
    "accounts.btn_disable": "⏸ غیرفعال",
    "accounts.btn_rename": "✏️ تغییر نام",
    "accounts.btn_auto_label": "🪄 نامگذاری خودکار",
    "accounts.btn_change_role": "🎭 تغییر نقش",
    "accounts.btn_vacant_roles": "📭 نقش‌های خالی",
    "accounts.btn_all_roles": "📋 همه نقش‌ها",
    "accounts.btn_logout": "🚪 لاگ‌اوت",
    "accounts.btn_delete": "🗑 حذف",
    "accounts.btn_confirm_logout": "✅ تأیید لاگ‌اوت",
    "accounts.btn_confirm_delete": "⚠️ تأیید حذف دائمی",
    "accounts.btn_confirm_enable": "✅ تأیید فعال‌سازی",
    "accounts.btn_confirm_disable": "✅ تأیید غیرفعال",
    "accounts.btn_manage_back": "⬅️ بازگشت به لیست",
    "accounts.btn_cancel": "❌ انصراف",
    "accounts.btn_back": "⬅️ منوی اصلی",
    "accounts.btn_confirm": "✅ تأیید و ارسال OTP",
    "accounts.btn_check_run": "🔄 وضعیت GHA",
    "accounts.btn_need_2fa": "🔐 دارم 2FA",
    "accounts.role_promo": "promo",
    "accounts.role_forward": "forward",
    "accounts.role_collector": "collector",
    "accounts.role_inspector": "inspector",
    "accounts.role_linkdir": "linkdir",
    "accounts.role_full": "full",
    "accounts.list_header": "📋 <b>اکانت‌های تو</b>\n────────────",
    "accounts.list_empty": "هنوز اکانتی برای تو ثبت نشده. از «افزودن» شروع کن.",
    "accounts.list_line": (
        "• <code>{id}</code> — {label}\n"
        "  role={role} | enabled={enabled} | status={status} | {phone}"
    ),
    "accounts.manage_pick": (
        "🛠 <b>مدیریت اکانت</b>\n"
        "────────────\n"
        "یکی از اکانت‌هایت را انتخاب کن (یا شناسه را بفرست):"
    ),
    "accounts.manage_detail": (
        "🛠 <b>{id}</b> — {label}\n"
        "────────────\n"
        "role=<code>{role}</code> | status=<code>{status}</code>\n"
        "enabled=<code>{enabled}</code> | phone=<code>{phone}</code>\n\n"
        "• فعال/غیرفعال · تغییر نام · نامگذاری خودکار · تغییر نقش\n"
        "• لاگ‌اوت / حذف"
    ),
    "accounts.ask_rename": (
        "نام نمایشی جدید برای <code>{account_id}</code> را بفرست.\n"
        "حداکثر ۶۴ کاراکتر.\n"
        "یا «نامگذاری خودکار» را بزن.\n\n"
        "/cancel برای انصراف"
    ),
    "accounts.rename_done": (
        "✅ نام <code>{account_id}</code> شد:\n"
        "<b>{label}</b>"
    ),
    "accounts.invalid_label": "نام نامعتبر است (خالی یا بیش از ۶۴ کاراکتر).",
    "accounts.ask_role_change": (
        "نقش جدید برای <code>{account_id}</code> (فعلی: <code>{role}</code>).\n"
        "نقش‌های خالی: {vacant}\n"
        "با تغییر نقش، ماژول‌های پروفایل با قالب نقش بازنویسی می‌شود "
        "(از ران بعدی اثر دارد)."
    ),
    "accounts.vacant_none": "الان نقش خالی نداری — همه نقش‌ها حداقل یک اکانت دارند.",
    "accounts.vacant_pick": (
        "📭 نقش‌های خالی برای <code>{account_id}</code>:\n"
        "یکی را انتخاب کن (یا «همه نقش‌ها»)."
    ),
    "accounts.role_done": (
        "✅ نقش <code>{account_id}</code>: "
        "<code>{previous}</code> → <code>{role}</code>\n"
        "برچسب: <b>{label}</b>"
    ),
    "accounts.confirm_enable": (
        "فعال‌سازی <code>{account_id}</code>؟\n"
        "در accounts.json مقدار enabled=true می‌شود.\n"
        "بعد از فعال‌سازی از «عملیات → اجرا» دیسپچ کن."
    ),
    "accounts.confirm_disable": (
        "غیرفعال کردن <code>{account_id}</code>؟\n"
        "رانرهای بعدی این اکانت را skip می‌کنند (سشن حذف نمی‌شود)."
    ),
    "accounts.enable_done": (
        "✅ اکانت <code>{account_id}</code> فعال شد.\n"
        "برای اجرا: منوی عملیات → اجرا."
    ),
    "accounts.disable_done": (
        "✅ اکانت <code>{account_id}</code> غیرفعال شد."
    ),
    "accounts.confirm_logout": (
        "لاگ‌اوت <code>{account_id}</code>؟\n"
        "سشن Actions حذف می‌شود و وضعیت به scaffolded برمی‌گردد.\n"
        "می‌توانی بعداً دوباره لاگین کنی."
    ),
    "accounts.confirm_delete": (
        "⚠️ حذف دائمی <code>{account_id}</code>؟\n"
        "از D1، accounts.json، پروفایل و ورک‌فلو پاک می‌شود.\n"
        "این کار برگشت‌پذیر نیست."
    ),
    "accounts.logout_done": (
        "✅ لاگ‌اوت <code>{account_id}</code> انجام شد.\n"
        "سشن‌سکرت حذف شد؛ برای استفاده دوباره از «لاگین موجود» استفاده کن."
    ),
    "accounts.delete_done": (
        "✅ اکانت <code>{account_id}</code> حذف شد."
    ),
    "accounts.delete_partial": (
        "✅ ردیف D1 برای <code>{account_id}</code> حذف شد.\n"
        "هشدار GitHub: {error}"
    ),
    "accounts.phone_taken": (
        "این شماره قبلاً برای اکانت <code>{account_id}</code> ثبت شده.\n"
        "شماره تکراری مجاز نیست."
    ),
    "accounts.owned_by_other": (
        "اکانت <code>{account_id}</code> مال ادمین دیگری است.\n"
        "نمی‌توانی ببینی یا مدیریتش کنی."
    ),
    "accounts.not_owned": (
        "اکانت <code>{account_id}</code> مال تو نیست یا هنوز ثبت نشده."
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
    "accounts.otp_ready": (
        "✅ ارسال OTP روی GHA برای <code>{account_id}</code> موفق بود (run {run_id}).\n"
        "کد تلگرام را همین‌جا بفرست."
    ),
    "accounts.otp_saved": (
        "OTP ذخیره شد. در حال complete روی GHA برای <code>{account_id}</code>...\n"
        "نتیجه را خودکار می‌فرستم؛ لازم نیست دکمه وضعیت را بزنی."
    ),
    "accounts.ask_2fa": (
        "رمز ابری / 2FA تلگرام را بفرست.\n"
        "فقط در همین چت؛ بعد از لاگین پاک می‌شود.\n"
        "/cancel برای انصراف"
    ),
    "accounts.twofa_saved": (
        "2FA ذخیره شد. دوباره complete برای <code>{account_id}</code> دیسپچ شد.\n"
        "نتیجه را خودکار می‌فرستم."
    ),
    "accounts.hint_2fa_or_retry": (
        "اگر رمز ابری داری «دارم 2FA» را بزن، یا OTP تازه بگیر و دوباره بفرست."
    ),
    "accounts.watch_timeout": (
        "⏱ هنوز نتیجه complete برای <code>{account_id}</code> نیامد (run {run_id}).\n"
        "می‌توانی «وضعیت GHA» را بزنی یا کمی صبر کنی."
    ),
    "accounts.run_status": (
        "GHA status=<code>{status}</code> conclusion=<code>{conclusion}</code>\n"
        "{url}"
    ),
    "accounts.done": (
        "✅ لاگین موفق برای <code>{account_id}</code>.\n"
        "سشن‌سکرت باید ست شده باشد.\n"
        "بعدی: مدیریت → فعال‌سازی، سپس عملیات → اجرا."
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
    "accounts.github_unavailable": (
        "⏳ GitHub الان در دسترس نیست (قطعی موقت API).\n"
        "چند لحظه صبر کن و دوباره «تأیید و ارسال OTP» را بزن.\n"
        "دادهٔ ویزارد حفظ شده است."
    ),
    "accounts.github_unauthorized": (
        "توکن GitHub روی Worker نامعتبر است (<code>GITHUB_TOKEN</code>)."
    ),
    "accounts.github_forbidden": (
        "دسترسی GitHub کافی نیست. PAT باید contents + actions روی ریپو داشته باشد."
    ),
    "accounts.retry_confirm": (
        "می‌توانی دوباره تأیید کنی:\n"
        "• id: <code>{account_id}</code>\n"
        "• role: <code>{role}</code>\n"
        "• phone: <code>{phone}</code>"
    ),
    "accounts.ignore_step": "الان این دکمه معتبر نیست. طبق پیام قبلی ادامه بده یا /cancel.",
    "accounts.no_session": "سشن لاگین فعالی نیست. از منوی اکانت‌ها شروع کن.",
    # status / discovery / promo / ops
    "status.header": "📊 <b>وضعیت اکانت‌های تو</b>\n────────────",
    "status.line": (
        "• <code>{id}</code> [{on}] {role} | {status}\n"
        "  GHA: {run}\n"
        "  {url}"
    ),
    "status.footer": (
        "────────────\n"
        "📦 Pool: از منوی کشف → وضعیت/لیست (ورک‌فلو GHA + گزارش به همین چت).\n"
        "هشدار FloodWait/circuit هم به همین ربات می‌آید."
    ),
    "status.btn_refresh": "🔄 تازه‌سازی وضعیت",
    "discovery.header": "🧺 <b>کشف — collector / inspector / linkdir</b>\n────────────",
    "discovery.empty": "هنوز اکانت collector/inspector/linkdir مال تو ثبت نشده.",
    "discovery.help": (
        "────────────\n"
        "همهٔ کنترل کشف/pool/inspect/harvest/linkdir از همین ربات است.\n"
        "نقش <code>linkdir</code>: طی روز چند بار لینکدونی جدید کشف می‌کند (D1).\n"
        "دیگر لازم نیست به PV اکانت‌ها پیام بدهی.\n"
        "تغییر پروفایل از ران بعدی اثر دارد (در صورت نیاز ریستارت)."
    ),
    "discovery.help_full": (
        "🧺 <b>راهنمای کشف</b>\n"
        "────────────\n"
        "Pool: وضعیت/لیست/تأیید/رد/to-promo\n"
        "Inspect: dry_run، pause، بودجه، dump\n"
        "Harvest: pause، لینکدونی add/remove، catchup\n"
        "Linkdir: شمارش کاتالوگ، pause/resume، اجرای الان\n"
        "ادغام raw: عملیات → ادغام pool"
    ),
    "discovery.btn_refresh": "🔄 تازه‌سازی کشف",
    "discovery.btn_help": "📖 راهنمای کشف",
    "discovery.btn_profile_status": "📄 وضعیت پروفایل",
    "discovery.btn_pool_status": "📦 وضعیت pool",
    "discovery.btn_pool_list": "📋 لیست raw",
    "discovery.btn_pool_list_ok": "📋 لیست ok",
    "discovery.btn_pool_list_approved": "📋 لیست approved",
    "discovery.btn_pool_approve": "✅ تأیید گروه",
    "discovery.btn_pool_reject": "🗑 رد گروه",
    "discovery.btn_to_promo": "📣 to-promo",
    "discovery.btn_inspect_dry": "🔎 dry_run inspect",
    "discovery.btn_inspect_pause": "⏸ pause inspect",
    "discovery.btn_inspect_resume": "▶️ resume inspect",
    "discovery.btn_inspect_budget": "🔢 بودجه inspect",
    "discovery.btn_inspect_dump": "🛡 dump inspect",
    "discovery.btn_harvest_pause": "⏸ pause harvest",
    "discovery.btn_harvest_resume": "▶️ resume harvest",
    "discovery.btn_harvest_add": "➕ لینکدونی",
    "discovery.btn_harvest_remove": "➖ حذف لینکدونی",
    "discovery.btn_harvest_catchup": "⏫ catchup",
    "discovery.btn_linkdir_counts": "📊 کاتالوگ linkdir",
    "discovery.btn_linkdir_run": "▶️ اجرای linkdir",
    "discovery.btn_linkdir_pause": "⏸ pause linkdir",
    "discovery.btn_linkdir_resume": "▶️ resume linkdir",
    "discovery.linkdir_counts": (
        "📊 <b>کاتالوگ لینکدونی (D1)</b>\n"
        "────────────\n"
        "total=<code>{total}</code> | promo_ready=<code>{promo_ready}</code>\n"
        "keep=<code>{keep}</code> review=<code>{review}</code> junk=<code>{junk}</code>\n"
        "active=<code>{active}</code> stale=<code>{stale}</code>"
    ),
    "discovery.linkdir_run_done": (
        "▶️ جمع‌آوری linkdir برای <code>{account_id}</code> دیسپچ شد.\n"
        "run=<code>{run_id}</code> status=<code>{status}</code>\n"
        "{url}"
    ),
    "discovery.no_role_account": "اکانت مناسب این نقش نداری.",
    "discovery.ask_budget": "بودجه روزانه جوین را بفرست (۱ تا ۱۲):",
    "discovery.invalid_budget": "عدد نامعتبر — بین ۱ تا ۱۲.",
    "discovery.ask_directory": "لینکدونی را بفرست (مثل <code>@Link4you</code>):",
    "discovery.ask_catchup": "عدد catch_up را بفرست (۰ تا ۲۰۰):",
    "discovery.ask_to_promo_source": "کانال منبع promo را بفرست (مثل <code>@mychannel</code>):",
    "discovery.ask_to_promo_ref": "رفرنس گروه approved را بفرست:",
    "promo.header": "📣 <b>تبلیغ — promo</b>\n────────────",
    "promo.empty": "هنوز اکانت promo مال تو ثبت نشده.",
    "promo.help": (
        "────────────\n"
        "مسیرها، dry_run، صف و safety از همین ربات.\n"
        "ارسال واقعی روی رانر؛ بعد از تغییر پروفایل در صورت نیاز ریستارت کن."
    ),
    "promo.help_full": (
        "📣 <b>راهنمای تبلیغ</b>\n"
        "────────────\n"
        "از ربات: وضعیت پروفایل، dry_run، pause/resume (سراسری و per-route)، "
        "mode (سراسری و per-route)، add/remove مسیر، group add/remove، "
        "لیست گروه‌ها، safety view/edit، صف، safety dump (runtime)، to-promo از کشف.\n"
        "دیگر لازم نیست به PV اکانت promo پیام بدهی."
    ),
    "promo.btn_refresh": "🔄 تازه‌سازی تبلیغ",
    "promo.btn_help": "📖 راهنمای تبلیغ",
    "promo.btn_profile_status": "📄 وضعیت مسیرها",
    "promo.btn_dry": "🧪 dry_run",
    "promo.btn_pause": "⏸ pause promo",
    "promo.btn_resume": "▶️ resume promo",
    "promo.btn_mode_forward": "mode: forward",
    "promo.btn_mode_copy": "mode: copy",
    "promo.btn_route_add": "➕ مسیر",
    "promo.btn_route_remove": "➖ حذف مسیر",
    "promo.btn_group_add": "➕ گروه به مسیر",
    "promo.btn_route_pause": "⏸ pause مسیر",
    "promo.btn_route_resume": "▶️ resume مسیر",
    "promo.btn_route_mode": "mode مسیر",
    "promo.btn_group_remove": "➖ حذف گروه",
    "promo.btn_groups": "📋 لیست گروه‌ها",
    "promo.btn_safety_view": "🛡 safety پروفایل",
    "promo.btn_safety_delay": "safety delay",
    "promo.btn_safety_budget": "safety budget",
    "promo.btn_safety_windows": "safety windows",
    "promo.btn_safety_cooldown": "safety cooldown",
    "promo.btn_safety_tz": "safety tz",
    "promo.btn_queue_status": "📥 وضعیت صف",
    "promo.btn_queue_clear": "🧹 پاک کردن صف",
    "promo.btn_safety_dump": "🛡 safety dump",
    "promo.ask_route_add": (
        "فرمت:\n"
        "<code>@channel @g1,@g2</code>\n"
        "یک خط بفرست."
    ),
    "promo.ask_route_source": "منبع مسیر را بفرست (<code>@channel</code>):",
    "promo.ask_group_add": (
        "فرمت:\n"
        "<code>@channel @group</code>"
    ),
    "promo.ask_group_remove": (
        "فرمت:\n"
        "<code>@channel @group</code>"
    ),
    "promo.ask_route_mode": (
        "فرمت:\n"
        "<code>@channel forward|copy</code>"
    ),
    "promo.ask_groups": (
        "منبع مسیر را بفرست (<code>@channel</code>) یا "
        "<code>همه</code> برای همه مسیرها."
    ),
    "promo.groups_one": (
        "📋 گروه‌های <code>{source}</code>\n"
        "{lines}"
    ),
    "promo.groups_all": (
        "📋 همه مسیرها ({count})\n"
        "{lines}"
    ),
    "promo.ask_safety_delay": (
        "بازه تأخیر (ثانیه):\n"
        "<code>70 190</code>"
    ),
    "promo.ask_safety_budget": (
        "بودجه:\n"
        "<code>daily 28 hourly 5</code>"
    ),
    "promo.ask_safety_windows": (
        "بازه‌های فعال:\n"
        "<code>09:30-13:00,16:00-22:00</code>"
    ),
    "promo.ask_safety_cooldown": (
        "کول‌داون گروه (دقیقه):\n"
        "<code>50</code>"
    ),
    "promo.ask_safety_tz": (
        "منطقه زمانی:\n"
        "<code>Asia/Tehran</code>"
    ),
    "promo.safety_config": (
        "🛡 safety پروفایل / <code>{account_id}</code>\n"
        "{lines}\n\n"
        "برای وضعیت runtime (circuit/صف) از «safety dump» استفاده کن."
    ),
    "promo.safety_done": (
        "✅ safety به‌روز شد / <code>{account_id}</code>\n"
        "{lines}"
    ),
    "promo.profile_status": (
        "📣 <code>{account_id}</code>\n"
        "dry_run=<code>{dry_run}</code> paused=<code>{paused}</code> "
        "mode=<code>{mode}</code>\n"
        "routes={route_count}\n"
        "{routes}"
    ),
    "forward.header": "📨 <b>فوروارد — channel_forward</b>\n────────────",
    "forward.empty": "هنوز اکانت forward مال تو ثبت نشده.",
    "forward.help": (
        "────────────\n"
        "مسیرها، فیلتر، زمان‌بندی، media/dedup/delivery و صف از همین ربات.\n"
        "ارسال واقعی روی رانر؛ بعد از تغییر پروفایل در صورت نیاز ریستارت کن."
    ),
    "forward.help_full": (
        "📨 <b>راهنمای فوروارد</b>\n"
        "────────────\n"
        "<b>ماژول:</b> dry_run، pause/resume، auto_join\n"
        "<b>مسیر:</b> add، remove، set، pause/resume، mode، visibility، claim\n"
        "<b>مقصد:</b> dest add/remove (چند مقصد)\n"
        "<b>فیلتر:</b> on/off، links/mentions/hashtags (toggle)، prefix/suffix/block\n"
        "<b>زمان‌بندی:</b> on/off، tz، days، hours، clear\n"
        "<b>سایر:</b> media، dedup، delivery، import، صف\n\n"
        "دیگر لازم نیست به PV اکانت forward پیام بدهی."
    ),
    # ── quick-setup wizard ────────────────────────────────────────────
    "forward.btn_setup": "⚡ راه‌اندازی سریع",
    "forward.btn_jobs": "📋 جاب‌های فوروارد",
    "forward.setup_step1": (
        "⚡ <b>راه‌اندازی سریع فوروارد</b>\n"
        "────────────\n"
        "گام ۱: ID اکانت forward را وارد کن.\n"
        "<i>مثال: <code>forwarder</code></i>"
    ),
    "forward.setup_step2": (
        "✅ اکانت: <code>{account_id}</code>\n\n"
        "گام ۲: کانال مبدأ (source) را وارد کن.\n"
        "<i>مثال: <code>@source_channel</code> یا آیدی عددی</i>"
    ),
    "forward.setup_step3": (
        "✅ مبدأ: <code>{source}</code>\n\n"
        "گام ۳: کانال مقصد (destination) را وارد کن.\n"
        "<i>مثال: <code>@dest_channel</code> یا آیدی عددی</i>"
    ),
    "forward.setup_step4_filter": (
        "✅ مقصد: <code>{destination}</code>\n\n"
        "گام ۴: فیلتر لینک‌ها روشن باشد؟\n"
        "(لینک‌های خارجی از پیام‌ها حذف می‌شوند)"
    ),
    "forward.setup_btn_yes_filter": "✅ بله، لینک‌ها حذف شوند",
    "forward.setup_btn_no_filter": "❌ خیر، بدون فیلتر",
    "forward.setup_saving": "⏳ در حال ذخیره و راه‌اندازی...",
    "forward.setup_done": (
        "✅ <b>فوروارد راه‌اندازی شد!</b>\n"
        "────────────\n"
        "اکانت: <code>{account_id}</code>\n"
        "مبدأ: <code>{source}</code>\n"
        "مقصد: <code>{destination}</code>\n"
        "فیلتر لینک: {filter_links}\n\n"
        "Workflow بلافاصله trigger شد 🚀\n"
        "Job ID: <code>{job_id}</code>"
    ),
    "forward.setup_dispatch_fail": (
        "✅ تنظیمات ذخیره شد اما dispatch ناموفق بود:\n{error}\n\n"
        "Job ID: <code>{job_id}</code>\n"
        "می‌توانی دستی از منوی وضعیت trigger کنی."
    ),
    "forward.setup_no_workflow": (
        "اکانت <code>{account_id}</code> workflow ندارد.\n"
        "ابتدا از منوی اکانت‌ها آن را enable کن."
    ),
    "forward.jobs_header": (
        "📋 <b>جاب‌های فوروارد</b>\n"
        "────────────\n"
    ),
    "forward.jobs_empty": "هیچ جابی تنظیم نشده.",
    "forward.jobs_line": (
        "• <code>{job_id}</code> | <code>{account_id}</code>\n"
        "  <code>{source}</code> → <code>{destination}</code>\n"
        "  وضعیت: {status} | آخرین اجرا: {last_run}"
    ),
    "forward.btn_refresh": "🔄 تازه‌سازی فوروارد",
    "forward.btn_help": "📖 راهنمای فوروارد",
    "forward.btn_profile_status": "📄 وضعیت مسیرها",
    "forward.btn_dry": "🧪 dry_run",
    "forward.btn_pause": "⏸ pause forward",
    "forward.btn_resume": "▶️ resume forward",
    "forward.btn_auto_join_on": "auto_join: on",
    "forward.btn_auto_join_off": "auto_join: off",
    "forward.btn_route_add": "➕ مسیر",
    "forward.btn_route_remove": "➖ حذف مسیر",
    "forward.btn_route_set": "🔁 set مقصد",
    "forward.btn_route_pause": "⏸ pause مسیر",
    "forward.btn_route_resume": "▶️ resume مسیر",
    "forward.btn_route_mode": "mode مسیر",
    "forward.btn_visibility": "👁 visibility",
    "forward.btn_claim": "📌 claim مسیر",
    "forward.btn_dest_add": "➕ dest add",
    "forward.btn_dest_remove": "➖ dest remove",
    "forward.btn_filter_view": "🛠 وضعیت فیلتر",
    "forward.btn_filter_on": "فیلتر: on",
    "forward.btn_filter_off": "فیلتر: off",
    "forward.btn_filter_links": "toggle links",
    "forward.btn_filter_mentions": "toggle mentions",
    "forward.btn_filter_hashtags": "toggle hashtags",
    "forward.btn_filter_prefix": "filter prefix",
    "forward.btn_filter_suffix": "filter suffix",
    "forward.btn_filter_block": "filter block",
    "forward.btn_filter_clear": "🧹 filter clear",
    "forward.btn_schedule_view": "🗓 وضعیت schedule",
    "forward.btn_schedule_on": "schedule: on",
    "forward.btn_schedule_off": "schedule: off",
    "forward.btn_schedule_tz": "schedule tz",
    "forward.btn_schedule_days": "schedule days",
    "forward.btn_schedule_hours": "schedule hours",
    "forward.btn_schedule_clear": "🧹 schedule clear",
    "forward.btn_media": "🎬 media filter",
    "forward.btn_dedup": "🔁 dedup",
    "forward.btn_delivery": "📤 delivery",
    "forward.btn_import": "📥 import مسیرها",
    "forward.btn_queue_status": "📥 وضعیت صف",
    "forward.btn_queue_clear": "🧹 پاک کردن صف",
    "forward.ask_route_add": (
        "فرمت:\n"
        "<code>@source @dest</code>\n"
        "یک خط بفرست."
    ),
    "forward.ask_route_set": (
        "فرمت:\n"
        "<code>@source @dest</code>"
    ),
    "forward.ask_route_source": "منبع مسیر را بفرست (<code>@channel</code>):",
    "forward.ask_route_mode": (
        "فرمت:\n"
        "<code>@source forward|copy</code>"
    ),
    "forward.ask_route_visibility": (
        "فرمت:\n"
        "<code>@source public|private</code>"
    ),
    "forward.ask_dest_add": (
        "فرمت:\n"
        "<code>@source @dest</code>"
    ),
    "forward.ask_dest_remove": (
        "فرمت:\n"
        "<code>@source @dest</code>"
    ),
    "forward.ask_filter_prefix": (
        "فرمت:\n"
        "<code>@source prefix متن</code> یا <code>@source prefix off</code>"
    ),
    "forward.ask_filter_suffix": (
        "فرمت:\n"
        "<code>@source suffix متن</code> یا <code>@source suffix off</code>"
    ),
    "forward.ask_filter_block": (
        "فرمت:\n"
        "<code>@source block add کلمه</code>\n"
        "<code>@source block remove کلمه</code>\n"
        "<code>@source block on|off|clear</code>"
    ),
    "forward.ask_schedule_tz": (
        "فرمت:\n"
        "<code>@source Asia/Tehran</code>"
    ),
    "forward.ask_schedule_days": (
        "فرمت:\n"
        "<code>@source sat,sun,mon</code>"
    ),
    "forward.ask_schedule_hours": (
        "فرمت:\n"
        "<code>@source 09:00-12:00,18:00-22:00</code>"
    ),
    "forward.ask_media": (
        "دستور media را بفرست:\n"
        "<code>on|off|allow photo,video|deny sticker</code>"
    ),
    "forward.ask_dedup": (
        "دستور dedup را بفرست:\n"
        "<code>on|off [hours]</code>"
    ),
    "forward.ask_delivery": (
        "دستور delivery را بفرست:\n"
        "<code>pin on|button متن url|sync on on</code>"
    ),
    "forward.ask_import": (
        "فرمت:\n"
        "<code>@a,@b @dest</code>"
    ),
    "forward.profile_status": (
        "📨 <code>{account_id}</code>\n"
        "enabled=<code>{enabled}</code> paused=<code>{paused}</code> "
        "dry_run=<code>{dry_run}</code> auto_join=<code>{auto_join}</code>\n"
        "routes={route_count}\n"
        "{routes}"
    ),
    "forward.summary_done": (
        "✅ <code>{account_id}</code> / {kind}\n"
        "{lines}"
    ),
    "forward.media_status": "🎬 media:\n{lines}",
    "forward.dedup_status": "🔁 dedup:\n{lines}",
    "forward.delivery_status": "📤 delivery:\n{lines}",
    "forward.import_done": (
        "✅ import روی <code>{account_id}</code>: {added} مسیر جدید"
    ),
    "discovery.profile_status": (
        "📄 <code>{account_id}</code> / <code>{module}</code>\n"
        "<code>{detail}</code>"
    ),
    "panel.pick_account": "اکانت را انتخاب کن:",
    "panel.cancelled": "لغو شد.",
    "profile.patch_done": (
        "✅ پروفایل <code>{account_id}</code> / <code>{module}</code> به‌روز شد.\n"
        "<code>{detail}</code>\n"
        "اثر از ران بعدی (ریستارت در عملیات اگر فوری لازم است)."
    ),
    "pool.working": "⏳ در حال «{action}» روی pool (GHA)...",
    "pool.dispatched": (
        "✅ pool «{action}» دیسپچ شد.\n"
        "run=<code>{run_id}</code>\n"
        "نتیجه را همین‌جا می‌فرستم.\n"
        "{url}"
    ),
    "pool.ask_ref_approve": "رفرنس گروه برای approve را بفرست (@user یا لینک):",
    "pool.ask_ref_reject": "رفرنس گروه برای reject را بفرست:",
    "pool.invalid_ref": "رفرنس نامعتبر است.",
    "pool.report_error": "❌ pool {action} ناموفق: {error}\n{url}",
    "pool.report_status": (
        "📦 <b>وضعیت pool</b>\n"
        "total=<code>{total}</code>\n"
        "{counts}\n"
        "{url}"
    ),
    "pool.report_list": (
        "📋 <b>لیست pool</b> ({filter})\n"
        "{listing}\n"
        "────────────\n"
        "{counts}\n"
        "{url}"
    ),
    "pool.report_mutate": (
        "✅ pool {action}: <code>{ref}</code> → <code>{status}</code>\n"
        "{counts}\n"
        "{url}"
    ),
    "pool.report_generic": "pool {action} تمام شد.\n{url}",
    "pool.report_get": (
        "🔍 pool get: <code>{ref}</code>\n"
        "status=<code>{status}</code> title={title}\n"
        "{url}"
    ),
    "pool.report_get_missing": "گروه در pool پیدا نشد.\n{url}",
    "pool.to_promo_blocked": (
        "⛔ to-promo انجام نشد — وضعیت باید approved باشد "
        "(فعلی: <code>{status}</code>)."
    ),
    "pool.to_promo_missing_fields": "دادهٔ to-promo ناقص بود.",
    "pool.to_promo_done": (
        "✅ to-promo: <code>{source}</code> → <code>{ref}</code> "
        "روی اکانت <code>{account_id}</code>"
    ),
    "cache.working": "⏳ در حال «{action}» روی کش اکانت...",
    "cache.dispatched": (
        "✅ cache «{action}» برای <code>{account_id}</code>\n"
        "run=<code>{run_id}</code>\n"
        "{url}"
    ),
    "cache.report_error": (
        "❌ cache {action} / <code>{account_id}</code>: {error}\n{url}"
    ),
    "cache.queue_status": (
        "📥 صف <code>{queue}</code> / <code>{account_id}</code>\n"
        "pending=<code>{pending}</code>\n{url}"
    ),
    "cache.queue_cleared": (
        "🧹 صف <code>{queue}</code> / <code>{account_id}</code> "
        "پاک شد ({cleared})\n{url}"
    ),
    "cache.dump": (
        "🛡 <code>{account_id}</code> / {action}\n"
        "exists=<code>{exists}</code>\n"
        "<code>{preview}</code>\n{url}"
    ),
    "alerts.flood": (
        "🚨 <b>هشدار اکانت</b> <code>{account_id}</code> [{severity}]\n"
        "{message}"
    ),
    "ops.menu": (
        "🛠 <b>عملیات GHA</b>\n"
        "────────────\n"
        "اجرا / کنسل / ریستارت روی ورک‌فلو اکانت‌های خودت.\n"
        "ادغام pool از کش Actions (ورک‌فلو merge-group-pool)."
    ),
    "ops.btn_dispatch": "▶️ اجرا",
    "ops.btn_cancel_run": "⏹ کنسل",
    "ops.btn_restart": "🔁 ریستارت",
    "ops.btn_merge": "📦 ادغام pool",
    "ops.btn_confirm_dispatch": "✅ تأیید اجرا",
    "ops.btn_confirm_cancel": "✅ تأیید کنسل",
    "ops.btn_confirm_restart": "✅ تأیید ریستارت",
    "ops.btn_confirm_merge": "✅ تأیید ادغام pool",
    "ops.action_dispatch": "اجرا",
    "ops.action_cancel": "کنسل",
    "ops.action_restart": "ریستارت",
    "ops.action_merge": "ادغام pool",
    "ops.pick": "اکانت را برای «{action}» انتخاب کن:",
    "ops.confirm_account": "تأیید «{action}» برای <code>{account_id}</code>؟",
    "ops.confirm_merge": (
        "ادغام raw_links همه اکانت‌ها داخل group_pool روی GHA؟\n"
        "ورک‌فلو: <code>merge-group-pool.yml</code>"
    ),
    "ops.working": "⏳ در حال «{action}» روی GitHub Actions...",
    "ops.done": (
        "✅ {action} برای <code>{account_id}</code>\n"
        "run=<code>{run_id}</code> status=<code>{status}</code> "
        "conclusion=<code>{conclusion}</code>\n"
        "{url}"
    ),
    "ops.cancel_none": "ران فعالی برای <code>{account_id}</code> پیدا نشد.",
    "ops.account_disabled": (
        "اکانت <code>{account_id}</code> غیرفعال است.\n"
        "اول از مدیریت → فعال‌سازی، بعد اجرا."
    ),
    "ops.cancelled": "عملیات لغو شد.",
    # command control panel
    "cmd.btn_menu": "🎮 کنترل زنده",
    "cmd.btn_send": "📤 ارسال دستور",
    "cmd.btn_status": "📡 وضعیت زنده",
    "cmd.btn_confirm_send": "✅ تایید و ارسال",
    "cmd.menu": (
        "🎮 <b>کنترل زنده اکانت‌ها</b>\n"
        "────────────\n"
        "دستور فوری به اکانت‌های در حال اجرا بفرست.\n"
        "اکانت ظرف ≤۳۰ ثانیه دستور را اجرا می‌کند.\n\n"
        "📤 <b>ارسال دستور</b> — دستور جدید بفرست\n"
        "📡 <b>وضعیت زنده</b> — heartbeat و دستورات اخیر"
    ),
    "cmd.pick_account": "اکانت مقصد را انتخاب کن:",
    "cmd.pick_account_status": "اکانت را برای دیدن وضعیت زنده انتخاب کن:",
    "cmd.pick_type": "نوع دستور برای <code>{account_id}</code> را انتخاب کن:",
    "cmd.ask_payload": "نوع دستور: <code>{cmd_type}</code>\n\n{hint}",
    "cmd.invalid_payload": "ورودی نامعتبر.\n\n{hint}",
    "cmd.invalid_type": "نوع دستور نامعتبر است. از دکمه‌ها استفاده کن.",
    "cmd.confirm": (
        "تأیید ارسال دستور؟\n\n"
        "اکانت: <code>{account_id}</code>\n"
        "نوع: <code>{cmd_type}</code>\n"
        "payload: <code>{payload}</code>"
    ),
    "cmd.sent": (
        "✅ دستور ارسال شد!\n"
        "id: <code>{cmd_id}…</code>\n"
        "اکانت: <code>{account_id}</code>\n"
        "نوع: <code>{cmd_type}</code>\n\n"
        "اکانت ظرف ≤۳۰ ثانیه اجرا می‌کند."
    ),
    "cmd.enqueue_error": "❌ خطا در ارسال دستور: {error}",
    "cmd.cancelled": "دستور لغو شد.",
    # system
    "health.hint": "POST Telegram updates to /webhook",
    "error.no_token": "no_token",
    "error.unauthorized": "unauthorized",
    "error.bad_json": "bad_json",
    "error.not_found": "not_found",
}
