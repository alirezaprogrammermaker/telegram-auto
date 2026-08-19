# Runbooks

این فایل برای عملیات تکراری و بازیابی خطاهای رایج است.

## Add A New Account

1. scaffold اکانت
2. commit/push workflow و profile
3. login روی GitHub runner
4. enable account
5. dispatch workflow account

برای جزئیات کامل:
- [`../multi-account.md`](../multi-account.md)

## Change An Account Role

1. role را از پنل یا scaffold/update تغییر بده
2. profile اکانت را بررسی کن
3. اگر workflow یا expected module set تغییر کرده، dispatch/restart انجام بده

## Add A Forward Route

دو مسیر وجود دارد:

### دستی
- از `ForwardController`
- اکانت را خودت انتخاب می‌کنی

### هوشمند
- از `AssignmentController`
- engine اکانت مناسب را انتخاب می‌کند

## Add A Promo Route

مثل forward:
- دستی از `PanelController`
- یا هوشمند از `AssignmentController`

## Recover Failed Login

1. `login_sessions` و status اکانت را چک کن
2. workflow `login-account.yml` را ببین
3. صحت `BRIDGE_TOKEN`, `ADMIN_BOT_BRIDGE_URL`, `REPO_SECRETS_TOKEN` و secretهای موقت را بررسی کن
4. اگر session خراب شده، login را دوباره از اول انجام بده

## Recover Bridge Failure

علائم:
- commandها poll نمی‌شوند
- heartbeat به‌روزرسانی نمی‌شود
- login workflow credential دریافت نمی‌کند

چک‌ها:
- Worker deploy سالم است
- `BRIDGE_TOKEN` دو طرف برابر است
- `ADMIN_BOT_BRIDGE_URL` درست است
- endpointهای `/internal/*` در Worker فعال هستند

## Apply New D1 Migrations

1. migration جدید بساز
2. SQL را review کن
3. `npx wrangler d1 migrations apply telegram-admin-db --remote`
4. اگر feature روی schema جدید تکیه دارد، بعد از migration deploy کن

## Drift Between D1 And Git Profile

به‌طور کلی:
- routeها و module config در Git-backed profiles هستند
- ownership/state/audit در D1 هستند

اگر drift دیدی:
- اول مشخص کن source of truth کدام سمت است
- اگر config مشکل دارد، profile را patch کن
- اگر audit/state مشکل دارد، D1 row را repair کن

## Restart Policy

- برای config changeهای durable، dispatch/restart مناسب است
- برای action فوری، live command مناسب‌تر است
- وقتی unsure هستی، اول ببین change باید durable باشد یا ephemeral
