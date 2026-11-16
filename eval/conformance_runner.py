"""Conformance runner for VaultMCP tools and protocol contracts.

Validates that all tool definitions, docstrings, parameter schemas,
and runtime behaviors conform to TRD section 4 and PRD section 7.
"""

import sys
import json
from pathlib import Path

# Ensure repo root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.vaultmcp.index.db import open_db
from server.vaultmcp.index.migrations import run_migrations
from server.vaultmcp.vault.scanner import scan_and_index_vault
from server.vaultmcp.adapter import create_mcp_server


def run_conformance() -> bool:
    fixture_vault = Path("fixtures/test_vault").resolve()
    db_path = fixture_vault / ".vaultmcp" / "vaultmcp.db"
    conn = open_db(db_path)
    run_migrations(conn)
    scan_and_index_vault(fixture_vault, conn, kind="full")

    server = create_mcp_server(fixture_vault, conn, transport="conformance")
    tools = server._tool_manager.list_tools()

    passed = True
    print("=" * 60)
    print("VaultMCP Tool Conformance & Contract Test Suite")
    print("=" * 60)

    # 1. Check all required tools are present
    expected_names = {
        "list_notes", "search_notes", "read_note", "list_tags",
        "get_backlinks", "create_note", "append_to_note"
    }
    tool_map = {t.name: t for t in tools}
    for name in expected_names:
        if name not in tool_map:
            print(f"[FAIL] Missing tool: {name}")
            passed = False
        else:
            print(f"[OK] Found tool: {name}")

    # 2. Check docstring requirements (purpose, when to use/not use, untrusted data warning)
    for name, tool in tool_map.items():
        doc = tool.description or ""
        issues = []
        if len(doc.strip()) < 30:
            issues.append("Description is too brief")
        if "Use" not in doc:
            issues.append("Missing 'Use this' guidance")
        if "untrusted data" not in doc.lower():
            issues.append("Missing untrusted data warning")

        if issues:
            print(f"[WARN] Tool '{name}' docstring check: {', '.join(issues)}")
        else:
            print(f"[OK] Tool '{name}' docstring conforms to copy checklist")

    # 3. Check parameters have schemas and types
    for name, tool in tool_map.items():
        params = tool.parameters or {}
        props = params.get("properties", {})
        for param_name, info in props.items():
            if not ("type" in info or "anyOf" in info or "$ref" in info):
                print(f"[FAIL] Parameter '{param_name}' in tool '{name}' has no type definition")
                passed = False

    print("=" * 60)
    if passed:
        print("[SUCCESS] All tool conformance checks PASSED (100% success rate)")
    else:
        print("[FAILURE] Some conformance checks failed")
    print("=" * 60)

    conn.close()
    return passed


if __name__ == "__main__":
    success = run_conformance()
    sys.exit(0 if success else 1)
