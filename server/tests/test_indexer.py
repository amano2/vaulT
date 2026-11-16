"""Tests for vault scanner, markdown parser, and FTS5 indexing."""

from pathlib import Path
from server.vaultmcp.index.db import open_db
from server.vaultmcp.index.migrations import run_migrations
from server.vaultmcp.vault.scanner import scan_and_index_vault
from server.vaultmcp.vault.parser import parse_markdown


def test_parse_markdown():
    content = """---
title: Sample Note
tags: [alpha, beta]
---
# First Heading
Content in first section with #inline_tag and [[TargetNote]].

## Second Heading
More content here.
"""
    parsed = parse_markdown("sub/sample.md", content, "2026-11-15T00:00:00Z")
    assert parsed.title == "Sample Note"
    assert parsed.folder == "sub"
    assert parsed.parse_error is None
    assert len(parsed.sections) == 2
    assert parsed.sections[0].heading == "First Heading"
    assert parsed.sections[0].level == 1
    assert parsed.sections[1].heading == "Second Heading"
    assert parsed.sections[1].level == 2

    # Tags check
    tag_names = {t.name for t in parsed.tags}
    assert "alpha" in tag_names
    assert "beta" in tag_names
    assert "inline_tag" in tag_names

    # Links check
    assert len(parsed.links) == 1
    assert parsed.links[0].target_text == "TargetNote"
    assert parsed.links[0].kind == "wiki"


def test_scan_and_index_fixture_vault(tmp_path: Path):
    fixture_vault = Path("fixtures/test_vault").resolve()
    assert fixture_vault.exists()

    db_path = tmp_path / "test_vault.db"
    conn = open_db(db_path)
    run_migrations(conn)

    # First full scan
    summary = scan_and_index_vault(fixture_vault, conn, kind="full")
    assert summary["notes_seen"] >= 5
    assert summary["notes_changed"] >= 5

    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM notes")
    assert cur.fetchone()[0] >= 5

    # Check FTS5 index contains entries
    cur.execute("SELECT count(*) FROM sections_fts")
    assert cur.fetchone()[0] > 0

    # Check parse error was recorded for bad front matter note
    cur.execute("SELECT parse_error FROM notes WHERE path LIKE '%bad_frontmatter.md%'")
    row = cur.fetchone()
    assert row is not None
    assert row[0] is not None  # error recorded

    # Check backlinks / links
    cur.execute("SELECT count(*) FROM links")
    assert cur.fetchone()[0] > 0

    # Incremental scan with no changes
    summary2 = scan_and_index_vault(fixture_vault, conn, kind="incremental")
    assert summary2["notes_changed"] == 0

    conn.close()
