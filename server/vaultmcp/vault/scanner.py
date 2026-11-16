"""Vault scanner and incremental indexer for VaultMCP."""

import os
from pathlib import Path
import json
import sqlite3
import datetime
import logging
from typing import Any

from server.vaultmcp.vault.paths import normalize_rel_path, PROTECTED_DIRS
from server.vaultmcp.vault.parser import parse_markdown, ParsedNote

logger = logging.getLogger("vaultmcp")


def get_ignore_folders(conn: sqlite3.Connection) -> set[str]:
    """Retrieves ignore folders list from settings table."""
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key='ignore_folders'")
    row = cur.fetchone()
    if row:
        try:
            return set(json.loads(row[0]))
        except Exception:
            pass
    return set(PROTECTED_DIRS)


def scan_and_index_vault(vault_root: Path, conn: sqlite3.Connection, kind: str = "full") -> dict[str, Any]:
    """Scans the vault directory and performs an incremental index into SQLite.

    Returns summary dictionary with stats and errors.
    """
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    ignore_folders = get_ignore_folders(conn)
    cur = conn.cursor()

    # Pre-fetch existing notes for incremental comparison
    cur.execute("SELECT id, path, content_hash, modified_at FROM notes")
    existing_notes = {row["path"]: dict(row) for row in cur.fetchall()}

    notes_seen = 0
    notes_changed = 0
    errors: list[dict[str, str]] = []
    seen_paths: set[str] = set()

    canonical_root = vault_root.resolve()

    for root, dirs, files in os.walk(canonical_root):
        rel_root = Path(root).relative_to(canonical_root)
        parts = rel_root.parts

        # Skip ignored directories
        if any(part in ignore_folders or part in PROTECTED_DIRS for part in parts):
            continue

        # Prune dirs in-place to avoid descending into ignored directories
        dirs[:] = [d for d in dirs if d not in ignore_folders and d not in PROTECTED_DIRS]

        for file_name in files:
            if not file_name.endswith(".md"):
                continue

            full_file_path = Path(root) / file_name
            rel_path = normalize_rel_path(full_file_path.relative_to(canonical_root))
            seen_paths.add(rel_path)
            notes_seen += 1

            try:
                stat = full_file_path.stat()
                mtime_iso = datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.timezone.utc).isoformat()
                size_bytes = stat.st_size

                # Fast check if file is unchanged (mtime match)
                existing = existing_notes.get(rel_path)
                if existing and existing["modified_at"] == mtime_iso and kind != "full":
                    continue

                # Read and check content
                try:
                    content = full_file_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    content = full_file_path.read_text(encoding="utf-8", errors="replace")

                parsed = parse_markdown(rel_path, content, mtime_iso, size_bytes)

                # Check if hash is unchanged
                if existing and existing["content_hash"] == parsed.content_hash and kind != "full":
                    # Update mtime if different
                    if existing["modified_at"] != mtime_iso:
                        cur.execute("UPDATE notes SET modified_at = ? WHERE id = ?", (mtime_iso, existing["id"]))
                    continue

                # File has changed or is new
                notes_changed += 1
                _index_single_note(conn, parsed)

                if parsed.parse_error:
                    errors.append({"path": rel_path, "message": parsed.parse_error})

            except Exception as e:
                logger.error("Error indexing %s: %s", rel_path, str(e))
                errors.append({"path": rel_path, "message": str(e)})

    # Delete records for removed files
    for old_path, note_data in existing_notes.items():
        if old_path not in seen_paths:
            logger.info("Removing deleted note: %s", old_path)
            cur.execute("DELETE FROM notes WHERE id = ?", (note_data["id"],))
            notes_changed += 1

    # Re-resolve links
    _resolve_links(conn)

    finished_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Record index run in telemetry table
    cur.execute(
        """
        INSERT INTO index_runs (kind, started_at, finished_at, notes_seen, notes_changed, errors)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (kind, started_at, finished_at, notes_seen, notes_changed, json.dumps(errors)),
    )
    conn.commit()

    return {
        "kind": kind,
        "notes_seen": notes_seen,
        "notes_changed": notes_changed,
        "errors": errors,
        "started_at": started_at,
        "finished_at": finished_at,
    }


def _index_single_note(conn: sqlite3.Connection, note: ParsedNote) -> None:
    """Inserts or updates a single parsed note within a transaction."""
    cur = conn.cursor()

    # Check if note already exists to clear old child rows
    cur.execute("SELECT id FROM notes WHERE path = ?", (note.path,))
    row = cur.fetchone()

    if row:
        note_id = row[0]
        cur.execute(
            """
            UPDATE notes
            SET title = ?, folder = ?, front_matter = ?, size_bytes = ?, content_hash = ?, modified_at = ?, indexed_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'), parse_error = ?
            WHERE id = ?
            """,
            (
                note.title,
                note.folder,
                json.dumps(note.front_matter),
                note.size_bytes,
                note.content_hash,
                note.modified_at,
                note.parse_error,
                note_id,
            ),
        )
        cur.execute("DELETE FROM sections WHERE note_id = ?", (note_id,))
        cur.execute("DELETE FROM note_tags WHERE note_id = ?", (note_id,))
        cur.execute("DELETE FROM links WHERE source_note_id = ?", (note_id,))
    else:
        cur.execute(
            """
            INSERT INTO notes (path, title, folder, front_matter, size_bytes, content_hash, modified_at, parse_error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                note.path,
                note.title,
                note.folder,
                json.dumps(note.front_matter),
                note.size_bytes,
                note.content_hash,
                note.modified_at,
                note.parse_error,
            ),
        )
        note_id = cur.lastrowid

    # Insert sections (Triggers automatically update sections_fts!)
    for sec in note.sections:
        cur.execute(
            """
            INSERT INTO sections (note_id, ordinal, heading, level, line_start, line_end, body)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (note_id, sec.ordinal, sec.heading, sec.level, sec.line_start, sec.line_end, sec.body),
        )

    # Insert tags
    for tag in note.tags:
        cur.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag.name,))
        cur.execute("SELECT id FROM tags WHERE name = ?", (tag.name,))
        tag_id = cur.fetchone()[0]
        cur.execute(
            "INSERT OR IGNORE INTO note_tags (note_id, tag_id, source) VALUES (?, ?, ?)",
            (note_id, tag_id, tag.source),
        )

    # Insert links
    for link in note.links:
        cur.execute(
            """
            INSERT INTO links (source_note_id, target_text, target_note_id, kind, line, context)
            VALUES (?, ?, NULL, ?, ?, ?)
            """,
            (note_id, link.target_text, link.kind, link.line, link.context),
        )


def _resolve_links(conn: sqlite3.Connection) -> None:
    """Resolves links.target_note_id for all unresolved links."""
    cur = conn.cursor()

    # Pre-fetch notes index for matching: by path, path without .md, and title
    cur.execute("SELECT id, path, title FROM notes")
    all_notes = cur.fetchall()

    by_path = {n["path"].lower(): n["id"] for n in all_notes}
    by_path_no_ext = {
        n["path"][:-3].lower() if n["path"].endswith(".md") else n["path"].lower(): n["id"] for n in all_notes
    }
    by_title = {n["title"].lower(): n["id"] for n in all_notes}

    # Fetch unresolved links
    cur.execute("SELECT id, target_text, source_note_id FROM links WHERE target_note_id IS NULL")
    unresolved = cur.fetchall()

    for link_row in unresolved:
        target = link_row["target_text"].strip().lower()
        target_no_ext = target[:-3] if target.endswith(".md") else target

        matched_id = None
        if target in by_path:
            matched_id = by_path[target]
        elif target_no_ext in by_path_no_ext:
            matched_id = by_path_no_ext[target_no_ext]
        elif target in by_title:
            matched_id = by_title[target]

        if matched_id:
            cur.execute("UPDATE links SET target_note_id = ? WHERE id = ?", (matched_id, link_row["id"]))
