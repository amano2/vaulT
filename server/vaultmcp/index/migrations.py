"""Database migrations runner for VaultMCP.

Implements migrations vm_001, vm_002, vm_003 matching BACKEND-SCHEMA.md.
"""

import sqlite3
import json
import logging

logger = logging.getLogger("vaultmcp")

VM_001_SQL = """
-- Migration vm_001: Notes, sections, FTS5 virtual table, triggers, tags, links
CREATE TABLE IF NOT EXISTS notes (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  path         TEXT NOT NULL UNIQUE,
  title        TEXT NOT NULL,
  folder       TEXT NOT NULL,
  front_matter TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(front_matter)),
  size_bytes   INTEGER NOT NULL,
  content_hash TEXT NOT NULL,
  modified_at  TEXT NOT NULL,
  indexed_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  parse_error  TEXT
);
CREATE INDEX IF NOT EXISTS idx_notes_folder ON notes(folder);
CREATE INDEX IF NOT EXISTS idx_notes_modified ON notes(modified_at DESC);

CREATE TABLE IF NOT EXISTS sections (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  note_id     INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
  ordinal     INTEGER NOT NULL,
  heading     TEXT NOT NULL DEFAULT '',
  level       INTEGER NOT NULL DEFAULT 0,
  line_start  INTEGER NOT NULL,
  line_end    INTEGER NOT NULL,
  body        TEXT NOT NULL,
  UNIQUE (note_id, ordinal)
);

-- Full-text index over sections (BM25 ranking)
CREATE VIRTUAL TABLE IF NOT EXISTS sections_fts USING fts5(
  heading, body, content='sections', content_rowid='id', tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS sections_ai AFTER INSERT ON sections BEGIN
  INSERT INTO sections_fts(rowid, heading, body) VALUES (new.id, new.heading, new.body);
END;
CREATE TRIGGER IF NOT EXISTS sections_ad AFTER DELETE ON sections BEGIN
  INSERT INTO sections_fts(sections_fts, rowid, heading, body) VALUES ('delete', old.id, old.heading, old.body);
END;
CREATE TRIGGER IF NOT EXISTS sections_au AFTER UPDATE ON sections BEGIN
  INSERT INTO sections_fts(sections_fts, rowid, heading, body) VALUES ('delete', old.id, old.heading, old.body);
  INSERT INTO sections_fts(rowid, heading, body) VALUES (new.id, new.heading, new.body);
END;

CREATE TABLE IF NOT EXISTS tags (
  id    INTEGER PRIMARY KEY AUTOINCREMENT,
  name  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS note_tags (
  note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
  tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  source  TEXT NOT NULL CHECK (source IN ('inline','front_matter')),
  PRIMARY KEY (note_id, tag_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS links (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  source_note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
  target_text    TEXT NOT NULL,
  target_note_id INTEGER REFERENCES notes(id) ON DELETE SET NULL,
  kind           TEXT NOT NULL CHECK (kind IN ('wiki','markdown')),
  line           INTEGER NOT NULL,
  context        TEXT
);
CREATE INDEX IF NOT EXISTS idx_links_target ON links(target_note_id);
CREATE INDEX IF NOT EXISTS idx_links_source ON links(source_note_id);
"""

VM_002_SQL = """
-- Migration vm_002: Settings, tokens, call log, backups
CREATE TABLE IF NOT EXISTS settings (
  key    TEXT PRIMARY KEY,
  value  TEXT NOT NULL CHECK (json_valid(value))
);

CREATE TABLE IF NOT EXISTS access_tokens (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  name               TEXT NOT NULL,
  token_hash         TEXT NOT NULL UNIQUE,
  scope              TEXT NOT NULL CHECK (scope IN ('read','read_write')),
  folder_prefix      TEXT,
  rate_limit_per_min INTEGER NOT NULL DEFAULT 120,
  created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  last_used_at       TEXT,
  expires_at         TEXT,
  revoked_at         TEXT
);

CREATE TABLE IF NOT EXISTS backups (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  note_path   TEXT NOT NULL,
  backup_path TEXT NOT NULL,
  reason      TEXT NOT NULL CHECK (reason IN ('append','restore','manual')),
  size_bytes  INTEGER NOT NULL,
  sha256      TEXT NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_backups_note ON backups(note_path, created_at DESC);

CREATE TABLE IF NOT EXISTS call_log (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  called_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  transport        TEXT NOT NULL CHECK (transport IN ('stdio','http','console')),
  client_name      TEXT,
  client_version   TEXT,
  protocol_version TEXT,
  token_id         INTEGER REFERENCES access_tokens(id) ON DELETE SET NULL,
  tool             TEXT NOT NULL,
  risk_class       TEXT NOT NULL CHECK (risk_class IN ('read','write')),
  arg_summary      TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(arg_summary)),
  status           TEXT NOT NULL CHECK (status IN ('ok','error','denied','rate_limited','timeout')),
  error_class      TEXT,
  duration_ms      INTEGER,
  result_bytes     INTEGER,
  truncated        INTEGER NOT NULL DEFAULT 0 CHECK (truncated IN (0,1)),
  backup_id        INTEGER REFERENCES backups(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_calls_time ON call_log(called_at DESC);
CREATE INDEX IF NOT EXISTS idx_calls_tool ON call_log(tool, status);
"""

VM_003_SQL = """
-- Migration vm_003: index_runs
CREATE TABLE IF NOT EXISTS index_runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  kind          TEXT NOT NULL CHECK (kind IN ('full','incremental','watch')),
  started_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  finished_at   TEXT,
  notes_seen    INTEGER NOT NULL DEFAULT 0,
  notes_changed INTEGER NOT NULL DEFAULT 0,
  errors        TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(errors))
);
"""

DEFAULT_SETTINGS = {
    "writes_enabled": False,
    "max_result_bytes": 20480,
    "ignore_folders": [".obsidian", ".trash", ".git", ".vaultmcp"],
    "allowed_write_folders": [],
    "rate_limits": {"default_per_min": 120},
}


def run_migrations(conn: sqlite3.Connection) -> None:
    """Executes migrations vm_001, vm_002, vm_003 and seeds initial settings."""
    conn.execute("CREATE TABLE IF NOT EXISTS _migrations (id TEXT PRIMARY KEY, applied_at TEXT);")

    cur = conn.cursor()
    applied = {row[0] for row in cur.execute("SELECT id FROM _migrations").fetchall()}

    if "vm_001" not in applied:
        logger.info("Applying migration vm_001...")
        cur.executescript(VM_001_SQL)
        cur.execute("INSERT INTO _migrations (id, applied_at) VALUES ('vm_001', strftime('%Y-%m-%dT%H:%M:%fZ','now'));")

    if "vm_002" not in applied:
        logger.info("Applying migration vm_002...")
        cur.executescript(VM_002_SQL)
        # Seed default settings
        for key, val in DEFAULT_SETTINGS.items():
            cur.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?);",
                (key, json.dumps(val)),
            )
        cur.execute("INSERT INTO _migrations (id, applied_at) VALUES ('vm_002', strftime('%Y-%m-%dT%H:%M:%fZ','now'));")

    if "vm_003" not in applied:
        logger.info("Applying migration vm_003...")
        cur.executescript(VM_003_SQL)
        cur.execute("INSERT INTO _migrations (id, applied_at) VALUES ('vm_003', strftime('%Y-%m-%dT%H:%M:%fZ','now'));")

    conn.commit()
