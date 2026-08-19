-- Command queue: cf-admin-bot enqueues commands; userbot polls and acks them.
-- Enables real-time bidirectional control without changing GitHub Actions infra.

CREATE TABLE IF NOT EXISTS commands (
  id          TEXT PRIMARY KEY,
  account_id  TEXT NOT NULL,
  type        TEXT NOT NULL,
  -- config_patch | module_on | module_off | module_reload
  -- pause_route | resume_route | flush_queue | ping
  payload     TEXT,                        -- JSON string
  status      TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'acked', 'done', 'failed', 'expired')),
  result      TEXT,                        -- JSON string (from userbot)
  issued_by   TEXT,                        -- 'admin' | 'agent' | telegram user_id
  created_at  TEXT NOT NULL,
  acked_at    TEXT,
  done_at     TEXT,
  ttl_seconds INTEGER NOT NULL DEFAULT 300
);

CREATE INDEX IF NOT EXISTS idx_commands_account_status
  ON commands(account_id, status, created_at);

CREATE INDEX IF NOT EXISTS idx_commands_created
  ON commands(created_at);

-- Heartbeat / live status table: userbot pushes every N seconds.
CREATE TABLE IF NOT EXISTS account_heartbeats (
  account_id   TEXT PRIMARY KEY,
  status       TEXT NOT NULL DEFAULT 'running',
  -- running | idle | error | stopping
  modules_json TEXT,    -- JSON: {"module_name": "running"|"stopped"}
  meta_json    TEXT,    -- arbitrary extra info (version, uptime, etc.)
  updated_at   TEXT NOT NULL
);
