# قابلیت‌های کامل سیستم telegram-auto
> تاریخ: ۱۴۰۳/۰۵/۲۹ — وضعیت زنده

---

## بخش اول — قابلیت‌های userbot (اکانت‌های Telethon)

### ماژول ۱: auto_reply
**کار:** دروازه ادمین از طریق DM تلگرام + پاسخ خودکار به غیرادمین‌ها

| قابلیت | دستور DM |
|--------|----------|
| ورود با رمز | `<رمز>` یا `/login <رمز>` |
| خروج از حالت ادمین | `/logout` |
| لیست دستورات | `/help` / `/commands` |
| وضعیت ماژول‌ها | `/modules` / `/module list` |
| روشن/خاموش ماژول | `/module on\|off\|reload <name>` |
| آمار فوروارد | `/stats` |
| خلاصه فوری | `/digest` |
| تغییر متن پاسخ | `/config reply <text>` |
| مدیریت whitelist | `/config whitelist add\|remove <id>` |
| پاسخ خودکار با cooldown | (خودکار) |

---

### ماژول ۲: channel_forward
**کار:** فوروارد چند-مسیره با فیلتر، زمان‌بندی، dedup، صف

| قابلیت | دستور DM |
|--------|----------|
| وضعیت مسیرها | `/forward status` / `/forward mine` |
| افزودن مسیر | `/forward add <source> <dest>` |
| حذف مسیر | `/forward remove <source>` |
| تغییر مقصد | `/forward set <source> <dest>` |
| حالت copy/forward | `/forward mode <source> copy\|forward` |
| Visibility | `/forward visibility <source> public\|private` |
| گرفتن مالکیت | `/forward claim <source>` |
| توقف/ادامه | `/forward pause\|resume <source>` |
| چند مقصد | `/forward dest add\|remove <source> <dest>` |
| فیلتر لینک | `/forward filter <source> links on\|off` |
| فیلتر mention | `/forward filter <source> mentions on\|off` |
| فیلتر hashtag | `/forward filter <source> hashtags on\|off` |
| فیلتر id عددی | `/forward filter <source> ids on\|off` |
| prefix/suffix ثابت | `/forward filter <source> prefix\|suffix <text>` |
| blocklist کلمه | `/forward filter <source> block add\|remove <word>` |
| فیلتر regex | `/forward regex <source> on\|set <pattern>` |
| allow-list | `/forward allow <source> on\|add\|clear` |
| زمان‌بندی | `/forward schedule <source> on\|off\|tz\|days\|hours` |
| فیلتر رسانه | `/forward media <source> on\|allow photo,video` |
| deduplication | `/forward dedup <source> on\|off [hours]` |
| pin/button/sync | `/forward delivery <source> pin\|button\|sync ...` |
| dryrun | `/forward dryrun on\|off` |
| جایگزینی لینک | `/forward link <source> set <from> <to>` |
| import دسته‌ای | `/forward import @a,@b <dest>` |
| وضعیت صف | `/forward queue [clear]` |

---

### ماژول ۳: promo_spread
**کار:** ارسال تبلیغاتی به گروه‌ها با safety کامل (delay، budget، circuit breaker)

| قابلیت | دستور DM |
|--------|----------|
| وضعیت | `/promo status\|help` |
| افزودن مسیر | `/promo add @channel @g1,@g2` |
| حذف مسیر | `/promo remove @channel` |
| مدیریت گروه | `/promo group add\|remove @channel @group` |
| dryrun | `/promo dryrun on\|off` |
| توقف/ادامه | `/promo pause\|resume` |
| وضعیت صف | `/promo queue` |
| تنظیم delay | `/promo safety delay <min> <max>` |
| سقف ارسال | `/promo safety budget <hourly> <daily>` |
| بازه ساعت | `/promo safety windows <...>` |

---

### ماژول ۴: link_harvest
**کار:** جمع‌آوری لینک گروه از کانال‌های لینکدونی → group pool

| قابلیت | دستور DM |
|--------|----------|
| وضعیت | `/harvest status\|help` |
| افزودن لینکدونی | `/harvest add @channel` |
| حذف لینکدونی | `/harvest remove @channel` |
| توقف/ادامه | `/harvest pause\|resume` |
| تنظیم catch-up | `/harvest catchup <n>` |

---

### ماژول ۵: group_inspect
**کار:** بازرسی آهسته گروه‌های pool — جوین، بررسی، ثبت نتیجه، خروج

| قابلیت | دستور DM |
|--------|----------|
| وضعیت | `/inspect status\|help` |
| dryrun | `/inspect dryrun on\|off` |
| توقف/ادامه | `/inspect pause\|resume` |
| budget روزانه | `/inspect budget <1-12>` |

---

### ماژول ۶: group_pool (مشترک)
**کار:** استخر مشترک گروه‌های کشف‌شده (raw→inspected→approved)

| قابلیت | دستور DM |
|--------|----------|
| آمار pool | `/pool status\|help` |
| لیست بر اساس وضعیت | `/pool list [raw\|inspected_ok\|rejected\|approved]` |
| تأیید گروه | `/pool approve <ref>` |
| رد گروه | `/pool reject <ref>` |
| انتقال به promo | `/pool to-promo <source_channel> <ref>` |

---

### ماژول ۷: digest
**کار:** خلاصه روزانه آمار به ادمین در ساعت مشخص

| قابلیت | دستور DM |
|--------|----------|
| دریافت فوری | `/digest` / `/digest now` |
| ارسال خودکار روزانه | (هر شب ۲۳:۰۰) |

---

### قابلیت‌های زیرساخت userbot

| قابلیت | فایل |
|--------|------|
| Multi-account (ایزولاسیون کامل داده) | `app/paths.py` |
| آمار روزانه (۶۰ روز نگهداری) | `app/stats.py` |
| ارسال هشدار به cf-admin-bot | `app/control_plane_alert.py` |
| Bridge HTTP به Cloudflare Worker | `app/bridge_client.py` |
| Poll دستور از bridge هر ۳۰ ثانیه | `app/command_poller.py` |
| Heartbeat زنده هر ۶۰ ثانیه | `app/command_poller.py` |
| Sync گروه‌های promo (batch) | `app/promo_group_sync.py` |

---

## بخش دوم — قابلیت‌های ربات مدیریتی (cf-admin-bot)

### ✅ پیاده‌سازی‌شده

| بخش | قابلیت‌ها |
|-----|-----------|
| **اکانت‌ها** | افزودن، لاگین (OTP+2FA)، لیست، فعال/غیرفعال، rename، تغییر role، logout، حذف |
| **عملیات GHA** | dispatch، cancel، restart، merge pool |
| **وضعیت** | داشبورد اکانت‌ها + آخرین run GHA |
| **کشف — pool** | وضعیت، لیست (raw/ok/rejected/approved)، approve، reject، انتقال به promo |
| **کشف — inspect** | dryrun toggle، pause/resume، budget، dump |
| **کشف — harvest** | pause/resume، add/remove directory، catchup |
| **کشف — linkdir** | counts، run، pause/resume |
| **تبلیغ** | وضعیت، dryrun، pause/resume، mode، route add/remove/pause/resume، گروه add/remove، queue، safety dump |
| **تبلیغ — safety** | delay، budget، windows، cooldown، timezone |
| **فوروارد** | setup wizard، وضعیت، dryrun، pause/resume، auto-join، route add/remove/set/pause/resume/mode/visibility/claim، dest add/remove، فیلتر کامل، زمان‌بندی، media، dedup، delivery، import، queue |
| **کنترل زنده** | ping، module on/off/reload، config_patch، pause_route، resume_route، flush_queue، heartbeat |
| **وضعیت زنده** | heartbeat اکانت، وضعیت ماژول‌ها، تاریخچه دستورات |
| **تنظیمات** | لیست ادمین‌ها، demote، stats dump، module on/off/reload |
| **راهنما** | HelpController (راهنمای دسته‌بندی‌شده) |

---

## بخش سوم — GAP آنالیز (چه چیزی هنوز در ربات مدیریتی نیست)

### ❌ GAP های اصلی

| قابلیت userbot | وضعیت در ربات | اولویت |
|----------------|---------------|--------|
| `/config reply <text>` — تغییر متن پاسخ خودکار | ❌ ندارد | متوسط |
| `/config whitelist add/remove` — لیست سفید پیام | ❌ ندارد | پایین |
| `/forward dryrun on/off` — دستور مستقیم در ربات | ❌ ندارد (فقط از طریق کنترل زنده) | متوسط |
| `/forward allow <source>` — allow-list کلمه | ❌ ندارد | متوسط |
| `/forward regex <source>` — فیلتر regex | ❌ ندارد | متوسط |
| `/forward link <source>` — جایگزینی لینک | ❌ ندارد | پایین |
| `/forward delivery` — pin/button/sync | ❌ ندارد | پایین |
| `/pool list` — لیست‌بندی در ربات | ✅ دارد (از طریق GHA) | — |
| `/stats` — آمار روزانه اکانت | ❌ ندارد (فقط stats_dump از GHA) | بالا |
| `/digest` — خلاصه فوری از ربات | ❌ ندارد | متوسط |
| مشاهده وضعیت صف forward در ربات | ❌ ندارد (فقط از GHA cache) | متوسط |
| مشاهده وضعیت صف promo در ربات | ❌ ندارد (فقط از GHA cache) | متوسط |
| مشاهده لاگ زنده | ❌ ندارد (در هیچ جا) | پایین |
| `/promo safety cooldown` / `timezone` از ربات | ❌ ندارد (فقط delay/budget/windows) | پایین |
| تنظیم `auto_reply.cooldown_seconds` از ربات | ❌ ندارد | پایین |
| تنظیم `promo mode` per-route از ربات | ✅ دارد | — |
| کنترل `group_pool` approve/reject از ربات | ✅ دارد (از طریق GHA pool-admin) | — |
| sync گروه‌های promo (promo_group_sync) | ❌ trigger دستی از ربات نیست | متوسط |
| مشاهده وضعیت circuit breaker promo | ❌ ندارد | متوسط |
| اعمال `/forward import` از ربات | ✅ دارد (ForwardController) | — |
| مشاهده آمار linkdir (counts) در ربات | ✅ دارد | — |
| مدیریت `group_inspect` budget از ربات | ✅ دارد | — |
| تنظیم `promo_spread` per-group cooldown از ربات | ❌ ندارد | پایین |

---

### اولویت‌بندی GAP ها

#### اولویت بالا
1. **آمار زنده (`/stats`) در پنل** — مشاهده forwarded/blocked/queued بدون نیاز به GHA
2. **وضعیت صف‌ها در پنل** — forward queue و promo queue count

#### اولویت متوسط
3. **تریگر `promo_group_sync`** — sync گروه‌های جدید بدون نیاز به GHA dispatch دستی
4. **`/config reply` و whitelist** — تنظیم auto_reply از ربات
5. **`/forward allow` و `regex`** — فیلترهای پیشرفته از ربات
6. **`/digest` فوری** — خلاصه آمار از ربات
7. **وضعیت circuit breaker promo** — مشاهده وضعیت ایمنی

#### اولویت پایین
8. **`/forward delivery`، `link`** — قابلیت‌های نادر
9. **`/config whitelist`** — نادر
10. **تنظیم `cooldown_seconds` auto_reply** — نادر
