-- Rebuild accounts as owner-scoped management table (user_id = Telegram owner).
-- id = GitHub/account key (e.g. promo2), globally unique in this repo.

CREATE TABLE IF NOT EXISTS accounts_new (
  id TEXT NOT NULL,
  user_id INTEGER NOT NULL,
  label TEXT,
  role TEXT,
  phone_e164 TEXT,
  phone_mask TEXT,
  enabled INTEGER NOT NULL DEFAULT 0,
  session_name TEXT,
  session_secret TEXT,
  workflow TEXT,
  profile_path TEXT,
  github_commit_sha TEXT,
  telegram_user_id INTEGER,
  telegram_username TEXT,
  status TEXT NOT NULL DEFAULT 'scaffolded'
    CHECK (status IN ('scaffolded', 'logging_in', 'ready', 'error')),
  last_error TEXT,
  last_login_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (id)
);

-- Copy prior rows; best-effort owner from latest login_sessions.created_by
INSERT OR IGNORE INTO accounts_new (
  id, user_id, label, role, phone_e164, phone_mask, enabled,
  session_name, session_secret, workflow, profile_path, github_commit_sha,
  telegram_user_id, telegram_username, status, last_error, last_login_at,
  created_at, updated_at
)
SELECT
  a.id,
  COALESCE(
    (
      SELECT ls.created_by
      FROM login_sessions ls
      WHERE ls.account_id = a.id AND ls.created_by IS NOT NULL
      ORDER BY ls.updated_at DESC
      LIMIT 1
    ),
    0
  ) AS user_id,
  a.label,
  a.role,
  NULL,
  a.phone_mask,
  a.enabled,
  a.session_name,
  a.session_secret,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  a.status,
  a.last_error,
  NULL,
  a.created_at,
  a.updated_at
FROM accounts AS a;

DROP TABLE accounts;
ALTER TABLE accounts_new RENAME TO accounts;

CREATE INDEX IF NOT EXISTS idx_accounts_user_id ON accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_phone_e164
  ON accounts(phone_e164)
  WHERE phone_e164 IS NOT NULL AND phone_e164 != '';

CREATE INDEX IF NOT EXISTS idx_login_sessions_created_by
  ON login_sessions(created_by);
