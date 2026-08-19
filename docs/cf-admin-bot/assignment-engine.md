# Smart Assignment Engine

Smart Assignment Engine برای این ساخته شده که وقتی admin یک route جدید forward یا promo اضافه می‌کند، لازم نباشد خودش اکانت مناسب را دستی انتخاب کند.

## Goal

- انتخاب بهترین اکانت compatible
- توزیع load بین accountها
- ترجیح حفظ source روی همان اکانت قبلی
- ثبت audit trail برای توسعه‌های بعدی

## Main Files

- `cf-admin-bot/src/app/Http/Controllers/AssignmentController.py`
- `cf-admin-bot/src/app/Services/AssignmentService.py`
- `cf-admin-bot/src/app/Services/RuleEngine.py`
- `cf-admin-bot/src/app/Support/AssignmentRules.py`
- `cf-admin-bot/src/app/Models/Assignment.py`
- `cf-admin-bot/database/migrations/0008_assignments.sql`

## Request Flow

1. admin از منوی `🏭 تخصیص هوشمند` وارد می‌شود
2. source و target/groups را می‌دهد
3. controller از service یک preview می‌گیرد
4. `AssignmentService` context را می‌سازد:
   - account list
   - active assignments
   - heartbeat state
   - sticky source lookup
5. `RuleEngine` accountها را score می‌کند
6. اکانت با بیشترین score برنده می‌شود
7. route به profile برنده patch می‌شود
8. record در `assignments` نوشته می‌شود
9. workflow برنده dispatch می‌شود

## Built-in Rules

### Hard filters
- `StatusRule`: فقط اکانت `ready` و `enabled`
- `RoleMatchRule`: فقط role سازگار
- `CapacityRule`: اکانت به سقف route نرسیده باشد

### Soft preferences
- `StickySourceRule`: source قبلی روی همان اکانت بماند
- `LoadBalanceRule`: اکانت با load کمتر امتیاز بیشتر بگیرد
- `HeartbeatRule`: heartbeat تازه‌تر ترجیح داده شود
- `TotalLoadRule`: بار کلی توزیع شود

## Scoring

فرمول کلی:

`sum(rule.weight * rule.score) / sum(weights)`

hard filterها قبل از weighted average اجرا می‌شوند و اگر fail شوند، آن اکانت اصلا وارد ranking نهایی نمی‌شود.

## Assignment Record

در جدول `assignments` این موارد ثبت می‌شود:

- owner user
- chosen account
- task type
- source
- target
- score snapshot
- status
- timestamps

این جدول هم برای audit مفید است هم برای featureهای آینده مثل analytics، balancing بهتر، یا reassignment.

## Extending The Engine

برای اضافه کردن rule جدید:

1. یک کلاس جدید از `BaseRule` بساز
2. `weight` بده
3. `score(account, context)` را پیاده‌سازی کن
4. در `RuleEngine.default()` آن را register کن

اگر later خواستی AI اضافه کنی، بهترین entrypoint معمولا `AssignmentService.assign_forward()` و `assign_promo()` است.
