# Component Map

این فایل یک نقشه سریع برای فهم ownership کد است: اگر دنبال یک رفتار هستی، معمولا باید اول به این فایل نگاه کنی.

## Root Project

### Runtime entrypoints
- `main.py`: اجرای اصلی userbot
- `login.py`: login لوکال/اسکریپتی

### Core app layer
- `app/config.py`: لود env و merge config
- `app/client.py`: ساخت `TelegramClient`
- `app/loader.py`: registry ماژول‌های اصلی
- `app/runtime.py`: enable/disable/reload/config patch در runtime
- `app/bridge_client.py`: ارتباط HTTP با `cf-admin-bot`
- `app/command_poller.py`: poll/ack/heartbeat برای live control
- `app/command_handlers.py`: اجرای commandهای دریافتی
- `app/agent_bus.py`: API سطح بالاتر برای agentها

### Modules
- `modules/auto_reply/`: دروازه admin DM
- `modules/channel_forward/`: مسیرهای فوروارد، فیلتر، schedule، queue
- `modules/promo_spread/`: ارسال تبلیغاتی با safety
- `modules/link_harvest/`: جمع‌آوری لینک‌ها
- `modules/group_inspect/`: بازرسی گروه‌ها
- `modules/group_pool/`: shared pool
- `modules/digest/`: خلاصه و آمار

### Config and state
- `config/modules.json`: base defaults
- `config/accounts.json`: account registry
- `config/accounts/*.json`: profile هر اکانت
- `data/<account>/`: runtime overlay و cache هر اکانت
- `data/pool/`: shared pool data

### Scripts and automation
- `manage.ps1`: CLI عملیاتی
- `scripts/prepare_gha_session.py`: آماده‌سازی session روی runner
- `scripts/gha_login.py`: مسیر login در GHA
- `scripts/scaffold_account.py`: scaffold اولیه اکانت

### Workflows
- `.github/workflows/run-account.yml`: reusable runner
- `.github/workflows/run-account-*.yml`: callerهای per-account
- `.github/workflows/login-account.yml`: login روی runner IP
- `.github/workflows/pool-admin.yml`: عملیات pool
- `.github/workflows/account-cache-admin.yml`: inspect/clear cache
- `.github/workflows/run-linkdir*.yml`: pipeline linkdir

## `cf-admin-bot`

### HTTP entry
- `cf-admin-bot/src/entry.py`: router نهایی Worker

### Controllers
- `WebhookController.py`: ورودی webhook
- `GuestController.py`: کاربر مهمان
- `AdminController.py`: router اصلی ادمین
- `AccountsController.py`: افزودن/لاگین/مدیریت اکانت
- `PanelController.py`: promo, discovery, status
- `ForwardController.py`: forward UI
- `OpsController.py`: dispatch/cancel/restart/merge
- `CommandController.py`: live control
- `AssignmentController.py`: smart assignment
- `HelpController.py`: راهنما

### Internal controllers
- `InternalLoginController.py`: bridge login
- `InternalPoolController.py`: گزارش pool-admin
- `InternalCacheController.py`: گزارش cache-admin
- `InternalCommandsController.py`: poll/ack/status/heartbeat
- `InternalAlertsController.py`: alert از runtime
- `InternalLinkDirController.py`: bridge مربوط به linkdir

### Models
- `Model.py`: query builder ساده D1
- `User.py`, `Account.py`, `LoginSession.py`, `UserState.py`
- `Command.py`: command queue + heartbeat model
- `LinkDir.py`: catalog models
- `HelpGuide.py`
- `Assignment.py`

### Services
- `AuthService.py`: auth و bootstrap
- `AccountService.py`: ownership و validation
- `AccountScaffoldService.py`: ساخت/patch فایل‌های GitHub
- `ProfileConfigService.py`: mutation ماژول‌ها و routeها
- `LoginOrchestratorService.py`: orchestration login
- `RunOrchestratorService.py`: dispatch/cancel/restart workflow
- `StatusService.py`: داشبورد
- `LinkDirCatalogService.py`
- `HelpGuideService.py`
- `AssignmentService.py` + `RuleEngine.py`

### Support/config/lang
- `config/bot.py`: env adapter
- `config/menus.py`: keyboard structure
- `lang/fa/messages.py`: متن‌های فارسی
- `app/Support/*.py`: helperها و formatting

## Ownership Rules

- تغییر متن UI: `lang/fa/messages.py`
- تغییر layout دکمه‌ها: `config/menus.py`
- تغییر business logic: `Services/`
- تغییر schema D1: `database/migrations/`
- تغییر bridge endpoint: `Internal*Controller.py`
- تغییر رفتار runtime userbot: `app/` یا `modules/`

## Read Next

- [`system-overview.md`](system-overview.md)
- [`glossary.md`](glossary.md)
- [`../cf-admin-bot/overview.md`](../cf-admin-bot/overview.md)
