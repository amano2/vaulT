# VaultMCP — Backend Schema

**Standalone project 4 of 5** · Version 0.1 · 14 Nov 2026 · Database: **SQLite** (WAL mode, FTS5) stored at `<vault>/.vaultmcp/vaultmcp.db` · Companion: TRD

> Self-contained schema for the notes index, access tokens, settings, call log, and backups. The notes themselves stay as plain Markdown files; the index is rebuildable at any time. Timestamps are ISO-8601 UTC text. JSON is stored as text guarded by `json_valid`.

---

## 1. Entity overview
```
notes -< sections            (FTS5 virtual table over sections)
notes -< note_tags >- tags
notes -< links               (source note -> target path/title, resolved or not)
access_tokens                call_log                backups
settings                     index_runs
```

## 2. Setup
```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
```

## 3. Index tables
```sql
CREATE TABLE notes (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  path         TEXT NOT NULL UNIQUE,              -- vault-relative, forward slashes
  title        TEXT NOT NULL,
  folder       TEXT NOT NULL,                     -- vault-relative folder ('' for root)
  front_matter TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(front_matter)),
  size_bytes   INTEGER NOT NULL,
  content_hash TEXT NOT NULL,                     -- sha256; incremental updates
  modified_at  TEXT NOT NULL,                     -- file mtime
  indexed_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  parse_error  TEXT                               -- set if parsing failed (note still listed)
);
CREATE INDEX idx_notes_folder ON notes(folder);
CREATE INDEX idx_notes_modified ON notes(modified_at DESC);

CREATE TABLE sections (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  note_id     INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
  ordinal     INTEGER NOT NULL,                   -- order within the note
  heading     TEXT NOT NULL DEFAULT '',           -- heading text ('' for the intro before the first heading)
  level       INTEGER NOT NULL DEFAULT 0,
  line_start  INTEGER NOT NULL,
  line_end    INTEGER NOT NULL,
  body        TEXT NOT NULL,
  UNIQUE (note_id, ordinal)
);

-- Full-text index over sections (BM25 ranking)
CREATE VIRTUAL TABLE sections_fts USING fts5(
  heading, body, content='sections', content_rowid='id', tokenize='porter unicode61'
);
CREATE TRIGGER sections_ai AFTER INSERT ON sections BEGIN
  INSERT INTO sections_fts(rowid, heading, body) VALUES (new.id, new.heading, new.body);
END;
CREATE TRIGGER sections_ad AFTER DELETE ON sections BEGIN
  INSERT INTO sections_fts(sections_fts, rowid, heading, body) VALUES ('delete', old.id, old.heading, old.body);
END;
CREATE TRIGGER sections_au AFTER UPDATE ON sections BEGIN
  INSERT INTO sections_fts(sections_fts, rowid, heading, body) VALUES ('delete', old.id, old.heading, old.body);
  INSERT INTO sections_fts(rowid, heading, body) VALUES (new.id, new.heading, new.body);
END;

CREATE TABLE tags (
  id    INTEGER PRIMARY KEY AUTOINCREMENT,
  name  TEXT NOT NULL UNIQUE                      -- without leading '#', lowercase, may contain '/'
);

CREATE TABLE note_tags (
  note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
  tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  source  TEXT NOT NULL CHECK (source IN ('inline','front_matter')),
  PRIMARY KEY (note_id, tag_id)
) WITHOUT ROWID;

CREATE TABLE links (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  source_note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
  target_text   TEXT NOT NULL,                    -- as written: [[Title]] or relative path
  target_note_id INTEGER REFERENCES notes(id) ON DELETE SET NULL,   -- null if unresolved
  kind          TEXT NOT NULL CHECK (kind IN ('wiki','markdown')),
  line          INTEGER NOT NULL,
  context       TEXT                              -- the line text for backlink display
);
CREATE INDEX idx_links_target ON links(target_note_id);
CREATE INDEX idx_links_source ON links(source_note_id);

CREATE TABLE index_runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  kind          TEXT NOT NULL CHECK (kind IN ('full','incremental','watch')),
  started_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  finished_at   TEXT,
  notes_seen    INTEGER NOT NULL DEFAULT 0,
  notes_changed INTEGER NOT NULL DEFAULT 0,
  errors        TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(errors))   -- [{path, message}]
);
```

## 4. Settings, tokens, call log, backups
```sql
CREATE TABLE settings (
  key    TEXT PRIMARY KEY,                        -- vault_path, ignore_folders, writes_enabled,
  value  TEXT NOT NULL CHECK (json_valid(value))  -- allowed_write_folders, max_result_bytes, rate_limits, ...
);

CREATE TABLE access_tokens (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL,
  token_hash    TEXT NOT NULL UNIQUE,             -- hash only; the token is shown once
  scope         TEXT NOT NULL CHECK (scope IN ('read','read_write')),
  folder_prefix TEXT,                             -- null = whole vault
  rate_limit_per_min INTEGER NOT NULL DEFAULT 120,
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  last_used_at  TEXT,
  expires_at    TEXT,
  revoked_at    TEXT
);

CREATE TABLE call_log (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  called_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  transport     TEXT NOT NULL CHECK (transport IN ('stdio','http','console')),
  client_name   TEXT,                             -- from the initialize handshake
  client_version TEXT,
  protocol_version TEXT,
  token_id      INTEGER REFERENCES access_tokens(id) ON DELETE SET NULL,
  tool          TEXT NOT NULL,
  risk_class    TEXT NOT NULL CHECK (risk_class IN ('read','write')),
  arg_summary   TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(arg_summary)),  -- lengths, flags, paths; never note text
  status        TEXT NOT NULL CHECK (status IN ('ok','error','denied','rate_limited','timeout')),
  error_class   TEXT,                             -- 'invalid_args','path_outside_vault','writes_disabled','auth','internal'
  duration_ms   INTEGER,
  result_bytes  INTEGER,
  truncated     INTEGER NOT NULL DEFAULT 0 CHECK (truncated IN (0,1)),
  backup_id     INTEGER REFERENCES backups(id) ON DELETE SET NULL
);
CREATE INDEX idx_calls_time ON call_log(called_at DESC);
CREATE INDEX idx_calls_tool ON call_log(tool, status);

CREATE TABLE backups (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  note_path     TEXT NOT NULL,
  backup_path   TEXT NOT NULL,                    -- .vaultmcp/backups/<timestamp>/<path>
  reason        TEXT NOT NULL CHECK (reason IN ('append','restore','manual')),
  size_bytes    INTEGER NOT NULL,
  sha256        TEXT NOT NULL,
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_backups_note ON backups(note_path, created_at DESC);
```

## 5. Key queries
```sql
-- search_notes: BM25 over sections with optional folder and tag filters
SELECT n.path, s.heading, s.line_start, s.line_end,
       snippet(sections_fts, 1, '[', ']', ' ... ', 24) AS snippet,
       bm25(sections_fts, 2.0, 1.0) AS score            -- heading weighted higher; lower = better
FROM sections_fts
JOIN sections s ON s.id = sections_fts.rowid
JOIN notes n ON n.id = s.note_id
WHERE sections_fts MATCH :query
  AND (:folder IS NULL OR n.folder = :folder OR n.folder LIKE :folder || '/%')
  AND (:tag IS NULL OR EXISTS (SELECT 1 FROM note_tags nt JOIN tags t ON t.id = nt.tag_id
                               WHERE nt.note_id = n.id AND t.name = :tag))
ORDER BY score LIMIT :top_k;

-- get_backlinks
SELECT n.path, l.line, l.context FROM links l JOIN notes n ON n.id = l.source_note_id
WHERE l.target_note_id = (SELECT id FROM notes WHERE path = :path);

-- list_tags
SELECT t.name, count(*) AS notes FROM tags t JOIN note_tags nt ON nt.tag_id = t.id
WHERE (:prefix IS NULL OR t.name LIKE :prefix || '%') GROUP BY t.id ORDER BY notes DESC;

-- Audit: writes that succeeded without a backup (should be none for appends)
SELECT id, tool, called_at FROM call_log WHERE risk_class = 'write' AND status = 'ok'
  AND tool = 'append_to_note' AND backup_id IS NULL;
```
Search input is sanitised into a safe FTS5 query (quote terms, escape operators) before binding.

## 6. Integrity and security rules
- `notes.path` is always vault-relative; the application resolves and verifies it stays inside the vault root before any file access (database content is never trusted for file access).
- `call_log.arg_summary` stores lengths, flags, and paths only; **note contents and token values are never stored**.
- Tokens are compared by hash in constant time; revoked or expired tokens are rejected.
- Writes require `writes_enabled = true` and a path under `allowed_write_folders`; enforced in code and recorded as `denied` with `error_class` when refused.
- The index database lives in the vault's `.vaultmcp/` folder, which is excluded from indexing and from all tool paths.

## 7. Index maintenance
- Incremental update: for each changed file (hash differs) delete its sections and re-insert in one transaction; remove rows for deleted files; re-resolve links that pointed at changed titles.
- `INSERT INTO sections_fts(sections_fts) VALUES ('rebuild');` after bulk imports; `VACUUM` and `PRAGMA optimize` from the console.
- The whole database can be deleted and rebuilt from the vault; only `settings`, `access_tokens`, and `call_log` are user data worth backing up.

## 8. Retention
`call_log` kept 90 days by default (configurable, with export before purge); `backups` keep the last 20 versions per note and prune older ones; `index_runs` keep the last 100.

## 9. Performance
FTS5 with `porter unicode61` handles tens of thousands of notes comfortably; section-level rows keep passages small; WAL mode allows the watcher and queries to run together; result size caps bound memory.

## 10. Migrations
Alembic or a simple numbered SQL migration runner: `vm_001` (index tables + FTS + triggers), `vm_002` (settings, tokens, call log, backups), `vm_003` (index runs). Default settings seeded on first run: `writes_enabled=false`, `max_result_bytes=20480`, `ignore_folders=[".obsidian",".trash",".git",".vaultmcp"]`.
