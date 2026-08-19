-- Smart Assignment Engine: tracks which account owns each forward/promo route.
-- Provides audit trail, load metrics, and the sticky-source lookup for re-assignment.

CREATE TABLE IF NOT EXISTS assignments (
  id           TEXT PRIMARY KEY,
  user_id      TEXT NOT NULL,
  account_id   TEXT NOT NULL,
  task_type    TEXT NOT NULL
    CHECK (task_type IN ('forward', 'promo')),
  source       TEXT NOT NULL,           -- normalised @username or t.me/... ref
  target       TEXT,                    -- forward: destination; promo: JSON array of groups
  status       TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'paused', 'removed')),
  score_json   TEXT,                    -- JSON snapshot of per-rule scores at assignment time
  assigned_at  TEXT NOT NULL,
  removed_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_assignments_account
  ON assignments(account_id, task_type, status);

CREATE INDEX IF NOT EXISTS idx_assignments_user
  ON assignments(user_id, task_type, status);

CREATE INDEX IF NOT EXISTS idx_assignments_source
  ON assignments(source, task_type, status);
