"""Backup creation, retention pruning, and restore management."""

from pathlib import Path
import sqlite3
import hashlib
import datetime
import shutil
import logging
from typing import Any

from server.vaultmcp.vault.paths import resolve_vault_path, normalize_rel_path, get_vault_rel_path

logger = logging.getLogger("vaultmcp")
MAX_BACKUPS_PER_NOTE = 20


def create_backup(
    vault_root: Path,
    conn: sqlite3.Connection,
    rel_note_path: str,
    reason: str = "append",
) -> int:
    """Creates a timestamped snapshot of a note file before modification.

    Stores the backup under .vaultmcp/backups/<timestamp>/<path> and
    records the event in the backups table. Prunes versions older than 20.
    Returns the newly created backup_id.
    """
    clean_path = normalize_rel_path(rel_note_path)
    full_path = resolve_vault_path(vault_root, clean_path)

    if not full_path.exists():
        raise FileNotFoundError(f"Cannot backup non-existent note: {clean_path}")

    content_bytes = full_path.read_bytes()
    sha256 = hashlib.sha256(content_bytes).hexdigest()
    size_bytes = len(content_bytes)

    timestamp_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    backup_rel_path = f".vaultmcp/backups/{timestamp_str}/{clean_path}"
    backup_full_path = vault_root / backup_rel_path
    backup_full_path.parent.mkdir(parents=True, exist_ok=True)

    # Copy file to backup destination
    shutil.copy2(full_path, backup_full_path)

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO backups (note_path, backup_path, reason, size_bytes, sha256)
        VALUES (?, ?, ?, ?, ?)
        """,
        (clean_path, backup_rel_path, reason, size_bytes, sha256),
    )
    backup_id = cur.lastrowid

    # Prune older backups for this note beyond the last 20
    cur.execute(
        """
        SELECT id, backup_path FROM backups
        WHERE note_path = ?
        ORDER BY created_at DESC
        LIMIT -1 OFFSET ?
        """,
        (clean_path, MAX_BACKUPS_PER_NOTE),
    )
    old_backups = cur.fetchall()
    for old_row in old_backups:
        old_id = old_row["id"]
        old_file = vault_root / old_row["backup_path"]
        try:
            if old_file.exists():
                old_file.unlink()
        except Exception as e:
            logger.warning("Failed to delete pruned backup file %s: %s", old_file, str(e))
        cur.execute("DELETE FROM backups WHERE id = ?", (old_id,))

    conn.commit()
    return backup_id


def restore_backup(
    vault_root: Path,
    conn: sqlite3.Connection,
    backup_id: int,
) -> dict[str, Any]:
    """Restores a note from a previous backup snapshot.

    Before overwriting, takes a snapshot of current note state with reason='restore'.
    """
    cur = conn.cursor()
    cur.execute("SELECT id, note_path, backup_path FROM backups WHERE id = ?", (backup_id,))
    backup_row = cur.fetchone()
    if not backup_row:
        raise ValueError(f"Backup with id {backup_id} not found.")

    note_rel_path = backup_row["note_path"]
    backup_file = vault_root / backup_row["backup_path"]

    if not backup_file.exists():
        raise FileNotFoundError(f"Backup file on disk missing: {backup_row['backup_path']}")

    current_note_file = resolve_vault_path(vault_root, note_rel_path)

    # If current note exists, snapshot it before restoration
    if current_note_file.exists():
        create_backup(vault_root, conn, note_rel_path, reason="restore")

    # Restore backup content to target note
    current_note_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_file, current_note_file)

    return {
        "status": "ok",
        "note_path": note_rel_path,
        "restored_from_backup_id": backup_id,
    }
