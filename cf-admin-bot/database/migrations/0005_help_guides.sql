-- Dynamic help guides (category + key)
CREATE TABLE IF NOT EXISTS help_guides (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category TEXT NOT NULL,
  key TEXT NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  emoji TEXT NOT NULL DEFAULT '📄',
  order_index INTEGER NOT NULL DEFAULT 0,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(category, key)
);

CREATE INDEX IF NOT EXISTS idx_help_guides_category
  ON help_guides(category, is_active, order_index);
