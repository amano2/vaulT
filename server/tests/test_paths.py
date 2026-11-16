"""Comprehensive tests for path confinement and directory traversal defenses."""

import pytest
from pathlib import Path
from server.vaultmcp.vault.paths import resolve_vault_path, PathConfinementError, normalize_rel_path


def test_normalize_rel_path():
    assert normalize_rel_path("folder/sub/note.md") == "folder/sub/note.md"
    assert normalize_rel_path("folder\\sub\\note.md") == "folder/sub/note.md"
    assert normalize_rel_path("./folder/note.md") == "folder/note.md"
    assert normalize_rel_path("/folder/note.md") == "folder/note.md"


def test_valid_vault_paths(tmp_path: Path):
    vault = tmp_path / "my_vault"
    vault.mkdir()
    (vault / "note.md").write_text("hello", encoding="utf-8")
    sub = vault / "sub"
    sub.mkdir()
    (sub / "nested.md").write_text("nested", encoding="utf-8")

    assert resolve_vault_path(vault, "note.md") == (vault / "note.md").resolve()
    assert resolve_vault_path(vault, "sub/nested.md") == (vault / "sub/nested.md").resolve()
    assert resolve_vault_path(vault, "./note.md") == (vault / "note.md").resolve()


def test_reject_hostile_traversal(tmp_path: Path):
    vault = tmp_path / "my_vault"
    vault.mkdir()

    hostile_attempts = [
        "../secret.txt",
        "..\\secret.txt",
        "sub/../../secret.txt",
        "....//secret.txt",
        "sub/./../../outside.md",
        "C:\\Windows\\System32\\cmd.exe",
        "/etc/passwd",
        "note.md\0.txt",
    ]

    for attempt in hostile_attempts:
        with pytest.raises(PathConfinementError):
            resolve_vault_path(vault, attempt)


def test_reject_protected_folders(tmp_path: Path):
    vault = tmp_path / "my_vault"
    vault.mkdir()
    dot_vault = vault / ".vaultmcp"
    dot_vault.mkdir()
    (dot_vault / "vaultmcp.db").write_text("data", encoding="utf-8")

    with pytest.raises(PathConfinementError):
        resolve_vault_path(vault, ".vaultmcp/vaultmcp.db")

    with pytest.raises(PathConfinementError):
        resolve_vault_path(vault, ".git/config")
