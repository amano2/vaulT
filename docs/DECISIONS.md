# VaultMCP — Architectural Decisions & Assumptions Log

## Precedence Rule
`BACKEND-SCHEMA.md` > `TRD.md` > `PRD.md` > `UI-UX.md`.

## Key Decisions & Logged Assumptions
1. **MCP SDK 2.x Integration (`adapter.py`)**:
   - The MCP Python SDK installed is `2.3.0`.
   - `from mcp.server import MCPServer` is used as per TRD 4.1.
   - MCP SDK imports are isolated strictly to `server/vaultmcp/adapter.py`.
2. **Stdout Purity Invariant**:
   - Stdio transport uses JSON-RPC over stdin/stdout.
   - All server logging (`logging.getLogger("vaultmcp")`) uses stderr handlers only. No `print()` calls in stdio code.
3. **Database & Storage**:
   - SQLite 3 with WAL mode, foreign keys ON, and FTS5 enabled.
   - Stored at `<vault>/.vaultmcp/vaultmcp.db`.
   - `.vaultmcp/` is strictly excluded from scanner, search, and tool paths.
4. **Path Confinement**:
   - Normalized vault-relative paths with forward slashes.
   - Every file access is resolved against `vault_root.resolve()`; any path escaping vault root or attempting traversal is rejected with actionable error messages.
5. **Write Safety & Backups**:
   - Default: `writes_enabled = false`.
   - Only folders explicitly listed in `allowed_write_folders` (e.g. `inbox/`) can be written to.
   - No file deletion tool exists.
   - `create_note` refuses to overwrite existing files.
   - `append_to_note` always creates a snapshot in `<vault>/.vaultmcp/backups/<timestamp>/` before modifying the file.
6. **Console UI Delivery**:
   - Single-port FastAPI server runs console API and serves the single-page application (SPA) static console at `127.0.0.1:8765`.
   - High accessibility standards (WCAG 2.2 AA).
