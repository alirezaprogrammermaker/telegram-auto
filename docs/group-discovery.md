# Safe multi-role group discovery

Nothing is ban-proof. This pipeline keeps **per-account activity very low** and
**never mixes jobs** on one session.

```text
link directories  →  collector(s)  →  raw pool
raw pool        →  inspector(s)  →  inspected_ok / rejected
inspected_ok    →  admin approve →  approved
approved        →  promo account →  paced sends
```

## Roles

| Role | Modules | Does | Must not |
|------|---------|------|----------|
| collector | `link_harvest` | Read link-directory channels, extract invites/@groups into pool | Join target groups, send promo |
| inspector | `group_inspect` | Very slow join → scan known antispam bots → leave | Scrape directories, send promo |
| promo | `promo_spread` | Send only to approved groups | Harvest or exploratory join |
| forward | `channel_forward` | Your real forward bot (e.g. Elmira) | Discovery / promo |

Scaffold:

```powershell
.\manage.ps1 account-add -Account collector1 -Role collector
.\manage.ps1 account-add -Account inspector1 -Role inspector
.\manage.ps1 account-add -Account promo1 -Role promo
```

Login each on GHA (`login-send` …), enable, push, dispatch.

## Overnight-safe mode (recommended first)

Only run **collectors** overnight:

1. Collector is member of `@Link4you` (or similar) — joining the *directory channel* is OK
2. `/harvest add @Link4you` then reload module
3. Leave inspector `dry_run: true` until you intentionally open real joins
4. Next day: `/pool status` + `/pool list raw`

Do **not** overnight-enable inspectors with high budgets.

## Inspector limits (defaults)

- `daily_join_budget`: 4 (hard-capped at 12)
- Delay between joins: 30 minutes … 3 hours
- `PeerFlood` / heavy `FloodWait` opens a multi-hour/day circuit
- `leave_after: true` so dialogs do not explode
- Antispam detection is **heuristic** (Combot, Rose, Shieldy, …) — not perfect

## Admin commands

```text
/harvest status|add|remove|pause|resume|catchup
/inspect status|dryrun|budget|pause|resume
/pool status|list [status]|approve <ref>|reject <ref>
/pool to-promo <source_channel> <ref>
```

`/pool to-promo` only works for **approved** refs and sets `promo_spread.auto_join=false`.

## Shared pool

- File: `data/pool/group_pool.json`
- Per-collector audit log: `data/<account>/raw_links.jsonl`
- Merge helper: `python scripts/merge_group_pool.py`
- GHA restores/saves `data/pool` with a shared cache key across account runners

## Scale idea (10–20 accounts)

- 3–5 collectors (1–2 directories each)
- 8–12 inspectors (2–4 joins/day each)
- 2–5 promo senders (low daily send budget)

Burning a collector/inspector must never take down Elmira or promo sessions.
