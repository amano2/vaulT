"""Tests for write safety: disabled by default, folder scope, backups, non-overwrite."""

import json
from pathlib import Path
from server.vaultmcp.index.db import open_db
from server.vaultmcp.index.migrations import run_migrations
from server.vaultmcp.tools.write import create_note_handler, append_to_note_handler
from server.vaultmcp.vault.backup import restore_backup


def test_writes_disabled_by_default(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    db_path = tmp_path / "test.db"
    conn = open_db(db_path)
    run_migrations(conn)

    # Attempt create when writes disabled
    res = create_note_handler(vault, conn, "test.md", "hello world")
    assert "Error: Write denied: Writes are currently disabled" in res

    # Attempt append when writes disabled
    (vault / "existing.md").write_text("initial", encoding="utf-8")
    res_app = append_to_note_handler(vault, conn, "existing.md", "more")
    assert "Error: Write denied: Writes are currently disabled" in res_app

    conn.close()


def test_write_folder_scoping(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "inbox").mkdir()
    (vault / "private").mkdir()

    db_path = tmp_path / "test.db"
    conn = open_db(db_path)
    run_migrations(conn)

    # Enable writes only for 'inbox'
    cur = conn.cursor()
    cur.execute("UPDATE settings SET value = 'true' WHERE key = 'writes_enabled'")
    cur.execute("UPDATE settings SET value = ? WHERE key = 'allowed_write_folders'", (json.dumps(["inbox"]),))
    conn.commit()

    # Allowed in inbox
    res1 = create_note_handler(vault, conn, "inbox/note1.md", "# Idea\nFirst note.")
    assert "Created note 'inbox/note1.md'" in res1
    assert (vault / "inbox/note1.md").exists()

    # Denied outside inbox
    res2 = create_note_handler(vault, conn, "private/note2.md", "secret")
    assert "Error: Write denied: Folder 'private' is not in allowed_write_folders" in res2
    assert not (vault / "private/note2.md").exists()

    # Refuse overwrite
    res3 = create_note_handler(vault, conn, "inbox/note1.md", "overwrite attempt")
    assert "Error: Refusing to overwrite existing note" in res3

    # Append creates backup
    res4 = append_to_note_handler(vault, conn, "inbox/note1.md", "Appended thought.")
    assert "backup snapshot #" in res4
    updated_content = (vault / "inbox/note1.md").read_text(encoding="utf-8")
    assert "Appended thought." in updated_content

    # Check backup row in db
    cur.execute("SELECT id FROM backups WHERE note_path = 'inbox/note1.md'")
    backup_row = cur.fetchone()
    assert backup_row is not None
    backup_id = backup_row[0]

    # Test restore
    restore_res = restore_backup(vault, conn, backup_id)
    assert restore_res["status"] == "ok"
    restored_text = (vault / "inbox/note1.md").read_text(encoding="utf-8")
    assert "Appended thought." not in restored_text
    assert "First note." in restored_text

    conn.close()
