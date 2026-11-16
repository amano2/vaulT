"""Tests for database migrations vm_001, vm_002, vm_003."""

import sqlite3
from pathlib import Path
from server.vaultmcp.index.db import open_db
from server.vaultmcp.index.migrations import run_migrations


def test_migrations(tmp_path: Path):
    db_file = tmp_path / "test.db"
    conn = open_db(db_file)
    run_migrations(conn)

    # Check tables exist
    cur = conn.cursor()
    tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "notes" in tables
    assert "sections" in tables
    assert "sections_fts" in tables
    assert "tags" in tables
    assert "note_tags" in tables
    assert "links" in tables
    assert "settings" in tables
    assert "access_tokens" in tables
    assert "call_log" in tables
    assert "backups" in tables
    assert "index_runs" in tables

    # Check default settings
    cur.execute("SELECT value FROM settings WHERE key='writes_enabled'")
    row = cur.fetchone()
    assert row is not None
    assert row[0] == "false"

    conn.close()
