"""Tests for read tools: list_notes, search_notes, read_note, list_tags, get_backlinks."""

from pathlib import Path
from server.vaultmcp.index.db import open_db
from server.vaultmcp.index.migrations import run_migrations
from server.vaultmcp.vault.scanner import scan_and_index_vault
from server.vaultmcp.tools.list_notes import list_notes_handler
from server.vaultmcp.tools.search_notes import search_notes_handler
from server.vaultmcp.tools.read_note import read_note_handler
from server.vaultmcp.tools.tags import list_tags_handler
from server.vaultmcp.tools.backlinks import get_backlinks_handler


def test_read_tools_flow(tmp_path: Path):
    fixture_vault = Path("fixtures/test_vault").resolve()
    db_path = tmp_path / "read_tools.db"
    conn = open_db(db_path)
    run_migrations(conn)
    scan_and_index_vault(fixture_vault, conn, kind="full")

    # 1. list_notes
    list_out = list_notes_handler(conn)
    assert "Found" in list_out
    assert "welcome.md" in list_out

    # Filtered by folder
    folder_out = list_notes_handler(conn, folder="projects")
    assert "projects/ai.md" in folder_out
    assert "welcome.md" not in folder_out

    # 2. search_notes
    search_out = search_notes_handler(conn, query="retrieval evaluation")
    assert "projects/ai.md" in search_out
    assert "Retrieval Evaluation Metrics" in search_out

    # Tag filter in search
    tag_search_out = search_notes_handler(conn, query="evaluation", tag="ml")
    assert "projects/ai.md" in tag_search_out

    # 3. read_note full and section
    full_note = read_note_handler(fixture_vault, conn, path="welcome.md")
    assert "Welcome to the Vault" in full_note
    assert "Front Matter:" in full_note

    sec_note = read_note_handler(fixture_vault, conn, path="projects/ai.md", section="Retrieval Evaluation Metrics")
    assert "MRR" in sec_note
    assert "Retrieval Evaluation Metrics" in sec_note

    # Hostile path rejection in read_note
    hostile_read = read_note_handler(fixture_vault, conn, path="../../secret.txt")
    assert "Error: Path is outside the vault" in hostile_read

    # 4. list_tags
    tags_out = list_tags_handler(conn)
    assert "#ml" in tags_out
    assert "#welcome" in tags_out

    # Prefix filter
    pref_tags = list_tags_handler(conn, prefix="res")
    assert "#research" in pref_tags

    # 5. get_backlinks
    # Note: welcome.md links to projects/ai, projects/ai links to welcome
    bl_out = get_backlinks_handler(conn, path="projects/ai.md")
    assert "welcome.md" in bl_out

    conn.close()
