# Linkdir finders (experiment)

Short-batch discovery pipeline for the shared لینکدونی catalog. **Not** a
long-running loader module — it is invoked by the `run-linkdir-*` GitHub
Actions batches and `linkdir-catalog-refresh`.

## Pipeline

```
search → snowball → rerank → verify_postable → mark_stale → export_promo_ready
```

- **search** — Telegram contacts search per query shard (`fa` / `en` /
  `niche`), enriched + ranked + upserted into the catalog.
- **snowball** — reads high-rank seed groups and harvests the invite links
  / @usernames their members post (peek-only, no joins by default).
- **rerank** — re-profiles active/review/stale rows so verdicts stay honest.
- **verify_postable** — limited experimental joins that resolve unknown
  `members_can_send` flags, then leave. Time-boxed by
  `verify_postable.experiment_until` and by `safety.daily_joins`.

## Shared pool (data/pool)

- `linkdir_catalog.json` — the living catalog (local cache; D1 is the source
  of truth when `ADMIN_BOT_BRIDGE_URL` + `ADMIN_BOT_BRIDGE_TOKEN` are set).
- `linkdir_promo_ready.json` — slim export promo accounts consume.
- `linkdir_safety_<collector>.json` — per-collector rate/circuit budgets.
- `group_pool.json` — **legacy** pool for the disabled `link_harvest`
  module. It is empty by design and is *not* part of this pipeline.

All batch writers funnel their snapshots through the serialized
`pool-merge.yml` job (one shared Actions cache key, last-writer-wins
removed), so concurrent collectors can no longer discard each other's
updates.

## Staleness & promo gating

- Items older than `catalog.stale_hours` become `status=stale` and lose
  `promo_ready` — except high-rank active items (`rank >=
  catalog.stale_rank_grace`), which survive one extra sweep.
- `promo_ready` requires `members_can_send is True` (or `postable is True`)
  plus verdict `keep` (or `review` for below-keep-bar groups that still
  allow member posting).
