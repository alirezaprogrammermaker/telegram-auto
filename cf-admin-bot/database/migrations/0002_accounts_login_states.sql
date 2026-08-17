-- Accounts mirror + login wizard state (Laravel-style)

CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY,
  label TEXT,
  role TEXT,
  enabled INTEGER NOT NULL DEFAULT 0,
  session_name TEXT,
  session_secret TEXT,
  phone_mask TEXT,
  status TEXT NOT NULL DEFAULT 'scaffolded'
    CHECK (status IN ('scaffolded', 'logging_in', 'ready', 'error')),
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS login_sessions (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  role TEXT,
  phone TEXT,
  otp TEXT,
  twofa TEXT,
  status TEXT NOT NULL DEFAULT 'drafting'
    CHECK (status IN (
      'drafting',
      'scaffolding',
      'sending',
      'awaiting_otp',
      'awaiting_2fa',
      'completing',
      'done',
      'failed',
      'cancelled'
    )),
  created_by INTEGER,
  github_run_id TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_login_sessions_account
  ON login_sessions(account_id);

CREATE INDEX IF NOT EXISTS idx_login_sessions_status
  ON login_sessions(status);

CREATE TABLE IF NOT EXISTS user_states (
  telegram_id INTEGER PRIMARY KEY,
  state TEXT NOT NULL DEFAULT 'idle',
  context_json TEXT,
  updated_at TEXT NOT NULL
);
