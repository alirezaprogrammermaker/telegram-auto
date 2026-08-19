-- Automation policies and execution log for health/recovery supervision.
-- Phase 1 focuses on stale heartbeat detection, ping probes, controlled restart,
-- operator notification, and an audit trail that later automation features can reuse.

CREATE TABLE IF NOT EXISTS automation_policies (
  id                         TEXT PRIMARY KEY,
  scope_type                 TEXT NOT NULL
    CHECK (scope_type IN ('global', 'user', 'account')),
  scope_id                   TEXT NOT NULL,
  enabled                    INTEGER NOT NULL DEFAULT 1,
  warn_after_minutes         INTEGER NOT NULL DEFAULT 10,
  ping_after_minutes         INTEGER NOT NULL DEFAULT 15,
  restart_after_minutes      INTEGER NOT NULL DEFAULT 30,
  restart_cooldown_minutes   INTEGER NOT NULL DEFAULT 180,
  max_restarts_per_day       INTEGER NOT NULL DEFAULT 2,
  notify_on_warn             INTEGER NOT NULL DEFAULT 1,
  notify_on_action           INTEGER NOT NULL DEFAULT 1,
  allowed_roles_csv          TEXT,
  created_at                 TEXT NOT NULL,
  updated_at                 TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_automation_policies_scope
  ON automation_policies(scope_type, scope_id);

CREATE TABLE IF NOT EXISTS automation_runs (
  id            TEXT PRIMARY KEY,
  policy_id     TEXT,
  user_id       TEXT NOT NULL,
  account_id    TEXT NOT NULL,
  action        TEXT NOT NULL
    CHECK (action IN ('warn_stale', 'ping_probe', 'restart_account')),
  status        TEXT NOT NULL DEFAULT 'done'
    CHECK (status IN ('queued', 'done', 'failed', 'skipped')),
  reason        TEXT,
  action_key    TEXT NOT NULL,
  details_json  TEXT,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_automation_runs_action_key
  ON automation_runs(action_key);

CREATE INDEX IF NOT EXISTS idx_automation_runs_account_action_created
  ON automation_runs(account_id, action, created_at);

CREATE INDEX IF NOT EXISTS idx_automation_runs_user_created
  ON automation_runs(user_id, created_at);
