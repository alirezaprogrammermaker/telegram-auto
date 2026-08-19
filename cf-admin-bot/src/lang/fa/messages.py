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
    "menu.btn_ops": "🛠 عملیات",
    "menu.btn_settings": "⚙️ تنظیمات",
    "menu.status": (
        "📊 <b>وضعیت</b>\n"
        "────────────\n"
        "از دکمه وضعیت برای داشبورد اکانت‌ها و آخرین ران GHA استفاده کن."
    ),
    "menu.discovery": (
        "🧺 <b>کشف گروه</b>\n"
        "────────────\n"
        "وضعیت collector/inspector + راهنمای دستورات روی خودِ اکانت Telethon."
    ),
    "menu.promo": (
        "📣 <b>تبلیغ</b>\n"
        "────────────\n"
        "وضعیت اکانت‌های promo + راهنمای `/promo` روی سشن تبلیغ."
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
    "menu.unknown": (
        "دستور ناشناخته.\n"
        "/start برای منو، یا از دکمه‌های پایین استفاده کن."
    ),
    "menu.help": (
        "راهنما:\n"
        "/start — منوی اصلی\n"
        "/whoami — شناسه تلگرام\n"
        "/admins — لیست ادمین‌ها\n"
        "اکانت‌ها — افزودن، لاگین، فعال‌سازی، لاگ‌اوت، حذف\n"
        "عملیات — اجرا / کنسل / ریستارت / ادغام pool روی GHA\n"
        "وضعیت — داشبورد اکانت + آخرین ران\n"
        "کشف / تبلیغ — وضعیت نقش‌ها + راهنما (دستورات زنده روی Telethon)\n"
        "/cancel — لغو ویزارد\n"
        "رمز مدیر را فقط یک‌بار برای ارتقا بفرست."
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
        "از ربات: وضعیت پروفایل، dry_run، pause، mode، add/remove مسیر، "
        "group add، صف، safety dump، to-promo از منوی کشف.\n"
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
    "promo.profile_status": (
        "📣 <code>{account_id}</code>\n"
        "dry_run=<code>{dry_run}</code> paused=<code>{paused}</code> "
        "mode=<code>{mode}</code>\n"
        "routes={route_count}\n"
        "{routes}"
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
    # system
    "health.hint": "POST Telegram updates to /webhook",
    "error.no_token": "no_token",
    "error.unauthorized": "unauthorized",
    "error.bad_json": "bad_json",
    "error.not_found": "not_found",
}
