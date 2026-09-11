# telegram-auto

Private runtime repository for scheduled automation.

## Account phone numbers

Registered account phones live in the Cloudflare D1 table `accounts.phone_e164`
(full E.164). The jellymanagerbot / cf-admin-bot Telegram UI lists that full
number so you can see the real Forwarder identity.

| Location | What it stores |
|---|---|
| D1 `Account.phone_e164` | Canonical full phone shown in the admin bot |
| D1 `Account.phone_mask` | Masked copy for non-UI/log storage only |
| GitHub `TELEGRAM_SESSION_B64*` | Telethon session secret — not the phone |

See `cf-admin-bot/README.md` for the control-plane layout.
