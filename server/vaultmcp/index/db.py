"""Database connection management and Pragmas for VaultMCP."""

import sqlite3
from pathlib import Path
from typing import Generator
import contextlib


def get_db_path(vault_root: Path) -> Path:
    """Returns the path to the sqlite database in .vaultmcp/vaultmcp.db."""
    dot_dir = vault_root / ".vaultmcp"
    dot_dir.mkdir(parents=True, exist_ok=True)
    return dot_dir / "vaultmcp.db"


def open_db(db_path: Path) -> sqlite3.Connection:
    """Opens a connection to SQLite with WAL mode, foreign keys, and row factory."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextlib.contextmanager
def get_db(vault_root: Path) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for obtaining a database connection."""
    db_path = get_db_path(vault_root)
    conn = open_db(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
