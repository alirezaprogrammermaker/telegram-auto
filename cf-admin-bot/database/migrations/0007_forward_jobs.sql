-- Forward jobs: tracks automated forwarding tasks created via admin bot
CREATE TABLE IF NOT EXISTS forward_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id TEXT NOT NULL,
  owner_id INTEGER NOT NULL,
  source TEXT NOT NULL,
  destination TEXT NOT NULL,
  options_json TEXT NOT NULL DEFAULT '{}',
  enabled INTEGER NOT NULL DEFAULT 1,
  auto_join INTEGER NOT NULL DEFAULT 1,
  filter_remove_links INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_dispatched_at TEXT,
  last_run_id INTEGER,
  last_run_status TEXT
);

CREATE INDEX IF NOT EXISTS idx_forward_jobs_owner
  ON forward_jobs(owner_id, enabled);

CREATE INDEX IF NOT EXISTS idx_forward_jobs_account
  ON forward_jobs(account_id);
