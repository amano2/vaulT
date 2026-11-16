"""FTS5 safe query building and BM25 search execution."""

import re
import sqlite3
from typing import Any


def sanitize_fts5_query(query: str) -> str:
    """Sanitizes user input into a safe, syntax-error-free SQLite FTS5 query.

    Handles special characters, operators (OR, AND, NOT, NEAR), and tokenizes.
    """
    cleaned = re.sub(r'[\'"\(\)\*\:\^\{\}\[\]\+]', " ", query)
    tokens = [t.strip() for t in cleaned.split() if t.strip()]

    # Ignore raw boolean operator keywords as standalone tokens
    safe_tokens = []
    reserved = {"and", "or", "not", "near"}
    for tok in tokens:
        if tok.lower() in reserved:
            continue
        # Wrap each word in quotes with prefix matching
        safe_tokens.append(f'"{tok}"*')

    if not safe_tokens:
        return '""'

    return " AND ".join(safe_tokens)


def search_sections(
    conn: sqlite3.Connection,
    query: str,
    folder: str | None = None,
    tag: str | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Executes FTS5 search over note sections using BM25 ranking."""
    safe_q = sanitize_fts5_query(query)
    if safe_q == '""':
        return []

    top_k = max(1, min(20, top_k))
    clean_tag = tag.lstrip("#").lower() if tag else None
    clean_folder = folder.strip("/\\").replace("\\", "/") if folder else None

    cur = conn.cursor()
    sql = """
    SELECT n.path, s.heading, s.line_start, s.line_end,
           snippet(sections_fts, 1, '[', ']', ' ... ', 24) AS snippet,
           bm25(sections_fts, 2.0, 1.0) AS score
    FROM sections_fts
    JOIN sections s ON s.id = sections_fts.rowid
    JOIN notes n ON n.id = s.note_id
    WHERE sections_fts MATCH :query
      AND (:folder IS NULL OR n.folder = :folder OR n.folder LIKE :folder || '/%')
      AND (:tag IS NULL OR EXISTS (
          SELECT 1 FROM note_tags nt JOIN tags t ON t.id = nt.tag_id
          WHERE nt.note_id = n.id AND t.name = :tag
      ))
    ORDER BY score
    LIMIT :top_k;
    """
    try:
        cur.execute(
            sql,
            {
                "query": safe_q,
                "folder": clean_folder,
                "tag": clean_tag,
                "top_k": top_k,
            },
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        # Fallback in case of unexpected syntax edge case
        return []
