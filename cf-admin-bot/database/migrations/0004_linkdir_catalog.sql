-- Link-directory discovery catalog (shared source of truth for collectors).
-- Telethon stays on runners; Worker only stores metadata via bridge.

CREATE TABLE IF NOT EXISTS linkdir_items (
  key TEXT PRIMARY KEY,
  ref TEXT NOT NULL,
  username TEXT,
  chat_id INTEGER,
  invite_hash TEXT,
  title TEXT,
  about TEXT,
  kind TEXT,
  is_channel INTEGER NOT NULL DEFAULT 0,
  is_group INTEGER NOT NULL DEFAULT 0,
  broadcast INTEGER NOT NULL DEFAULT 0,
  megagroup INTEGER NOT NULL DEFAULT 0,
  gigagroup INTEGER NOT NULL DEFAULT 0,
  members_can_send INTEGER,
  postable INTEGER,
  participants INTEGER,
  identity_score REAL,
  quality_score REAL,
  rank_score REAL,
  verdict TEXT NOT NULL DEFAULT 'junk'
    CHECK (verdict IN ('keep', 'review', 'junk')),
  status TEXT NOT NULL DEFAULT 'junk'
    CHECK (status IN ('active', 'review', 'junk', 'stale')),
  promo_ready INTEGER NOT NULL DEFAULT 0,
  seed_only INTEGER NOT NULL DEFAULT 0,
  reasons_json TEXT,
  gates_json TEXT,
  activity_json TEXT,
  methods_json TEXT,
  queries_json TEXT,
  parent_seed TEXT,
  last_method TEXT,
  seen_count INTEGER NOT NULL DEFAULT 0,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  last_ranked_at TEXT,
  stale_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_linkdir_items_promo_ready
  ON linkdir_items(promo_ready);

CREATE INDEX IF NOT EXISTS idx_linkdir_items_verdict
  ON linkdir_items(verdict);

CREATE INDEX IF NOT EXISTS idx_linkdir_items_status
  ON linkdir_items(status);

CREATE INDEX IF NOT EXISTS idx_linkdir_items_username
  ON linkdir_items(username);

CREATE INDEX IF NOT EXISTS idx_linkdir_items_rank
  ON linkdir_items(rank_score DESC);

CREATE TABLE IF NOT EXISTS linkdir_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_key TEXT NOT NULL,
  event_type TEXT NOT NULL,
  collector_id TEXT,
  method TEXT,
  payload_json TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_linkdir_events_item
  ON linkdir_events(item_key);

CREATE INDEX IF NOT EXISTS idx_linkdir_events_created
  ON linkdir_events(created_at);

CREATE TABLE IF NOT EXISTS linkdir_collectors (
  id TEXT PRIMARY KEY,
  session_name TEXT,
  label TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'idle'
    CHECK (status IN ('idle', 'running', 'circuit', 'disabled')),
  circuit_until TEXT,
  circuit_reason TEXT,
  budgets_json TEXT,
  last_run_at TEXT,
  meta_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_linkdir_collectors_status
  ON linkdir_collectors(status);

CREATE TABLE IF NOT EXISTS linkdir_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 100,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'leased', 'done', 'failed', 'cancelled')),
  lease_owner TEXT,
  lease_until TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  done_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_linkdir_jobs_status_priority
  ON linkdir_jobs(status, priority ASC, id ASC);

CREATE TABLE IF NOT EXISTS linkdir_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  collector_id TEXT,
  steps_json TEXT,
  ok INTEGER NOT NULL DEFAULT 0,
  summary_json TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_linkdir_runs_collector
  ON linkdir_runs(collector_id);

CREATE INDEX IF NOT EXISTS idx_linkdir_runs_finished
  ON linkdir_runs(finished_at);
