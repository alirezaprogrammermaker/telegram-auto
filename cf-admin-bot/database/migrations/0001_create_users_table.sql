-- Create users table (Laravel-style migration naming)
CREATE TABLE IF NOT EXISTS users (
  telegram_id INTEGER PRIMARY KEY,
  chat_id INTEGER NOT NULL,
  username TEXT,
  first_name TEXT,
  last_name TEXT,
  role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_seen_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
