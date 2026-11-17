"""Path resolution and strict confinement for VaultMCP.

Guarantees no file access can escape the configured vault root directory.
"""

from pathlib import Path
import os
import re

PROTECTED_DIRS = {".vaultmcp", ".git", ".obsidian", ".trash"}


class PathConfinementError(ValueError):
    """Raised when an attempted path escapes the vault or accesses protected areas."""
    pass


def normalize_rel_path(rel_path: str | Path) -> str:
    """Converts a path into a canonical vault-relative string with forward slashes."""
    p_str = str(rel_path).replace("\\", "/")
    # Strip leading slashes and redundant current-dir dots
    p_str = re.sub(r"^(?:\./|/)+", "", p_str)
    return p_str


def resolve_vault_path(vault_root: Path, user_path: str | Path) -> Path:
    """Resolves and validates a user-provided path against vault_root.

    Raises PathConfinementError on:
    - Null bytes
    - Absolute drive or root paths
    - Traversal attempts ('..', '....', etc.)
    - Resolved symlinks or paths outside the canonical vault root
    - Access to protected directories (.vaultmcp, .git, etc.)
    """
    raw_str = str(user_path)
    if "\0" in raw_str or "\\0" in raw_str:
        raise PathConfinementError("Path contains forbidden null byte.")

    # Disallow Windows drive letters, UNC, and absolute prefixes
    if re.match(r"^[a-zA-Z]:", raw_str) or raw_str.startswith(r"\\"):
        raise PathConfinementError(f"Absolute paths are rejected: {user_path}")

    # Standardize path separators to forward slash
    norm_str = raw_str.replace("\\", "/")
    if norm_str.startswith("/"):
        raise PathConfinementError(f"Absolute paths are rejected: {user_path}")

    # Reject traversal tokens (2 or more dots as a path segment)
    for part in norm_str.split("/"):
        if re.match(r"^\.{2,}$", part):
            raise PathConfinementError(f"Path traversal sequence '{part}' rejected: {user_path}")

    # Canonicalize vault root
    canonical_root = vault_root.resolve()

    # Join and resolve using normalized path
    target_path = (canonical_root / norm_str).resolve()

    # Check confinement
    try:
        rel = target_path.relative_to(canonical_root)
    except ValueError:
        raise PathConfinementError(f"Path '{user_path}' escapes vault root.")

    # Check protected directories
    for part in rel.parts:
        if part in PROTECTED_DIRS:
            raise PathConfinementError(f"Access to protected folder '{part}' is disallowed.")

    return target_path


def get_vault_rel_path(vault_root: Path, full_path: Path) -> str:
    """Returns canonical forward-slash vault-relative path from a full path."""
    canonical_root = vault_root.resolve()
    target_path = full_path.resolve()
    rel = target_path.relative_to(canonical_root)
    return normalize_rel_path(rel)
