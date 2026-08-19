# Glossary

## Admin bot
ربات مدیریتی روی Cloudflare Worker که فقط برای ادمین‌هاست و control plane پروژه را تشکیل می‌دهد.

## Userbot
اکانت واقعی تلگرام که با Telethon اجرا می‌شود، نه BotFather bot.

## Control plane
بخشی که state، orchestration، منوها، command queue و عملیات مدیریتی را مدیریت می‌کند. در این پروژه: `cf-admin-bot` + D1.

## Execution plane
بخشی که کار واقعی را اجرا می‌کند. در این پروژه: GitHub Actions runnerها + runtimeهای Telethon.

## Account registry
فایل `config/accounts.json` که اعلام می‌کند چه اکانت‌هایی وجود دارند، workflow آن‌ها چیست، secret کدام است، و profile کجاست.

## Account profile
فایل `config/accounts/<id>.json` که مشخص می‌کند هر اکانت چه ماژول‌هایی را با چه تنظیماتی اجرا کند.

## Runtime overlay
فایل `data/<account>/modules.runtime.json` که تغییرات runtime را روی profile/base config override می‌کند.

## Forward
سیستم انتقال پیام از کانال/منبع به مقصد، با filter/schedule/dedup/delivery.

## Promo
سیستم ارسال تبلیغاتی کنترل‌شده از source channel به groupها با safety rules.

## Discovery
pipeline چندمرحله‌ای برای پیدا کردن گروه، بررسی آن، تایید، و آماده‌سازی برای promo.

## Collector
اکانتی که فقط لینک‌ها را از directory channelها جمع می‌کند.

## Inspector
اکانتی که با budget پایین گروه‌ها را join/check/leave می‌کند تا مناسب بودن آن‌ها سنجیده شود.

## Pool
مخزن مشترک group candidates که بین collectorها، inspectorها و promo flow ردوبدل می‌شود.

## Linkdir
pipeline جداگانه برای discovery/catalog که با workflow و runtime اختصاصی اجرا می‌شود، نه loader اصلی `main.py`.

## Bridge
endpointهای داخلی Worker که بین `cf-admin-bot` و runtimeها/Actions ارتباط برقرار می‌کنند.

## Live control
ارسال command فوری به userbot در حال اجرا از طریق D1 queue + polling.

## Smart assignment
انتخاب rule-based بهترین اکانت برای دریافت یک route جدید forward یا promo.

## Sticky source
قاعده‌ای در assignment engine که اگر یک source قبلا روی اکانتی بوده، همان اکانت را ترجیح می‌دهد تا churn کم شود.

## D1
دیتابیس Cloudflare که state مدیریتی پروژه را نگه می‌دارد.

## Workflow caller
فایل `.github/workflows/run-account-<id>.yml` که reusable workflow اصلی را برای یک اکانت خاص invoke می‌کند.

## Reusable workflow
workflow عمومی مثل `run-account.yml` یا `login-account.yml` که توسط workflowهای دیگر call می‌شود.
