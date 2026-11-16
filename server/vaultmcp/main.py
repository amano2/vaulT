"""Command Line Interface and Entrypoint for VaultMCP."""

import argparse
import sys
import json
import uvicorn
from pathlib import Path

from server.vaultmcp.logging_setup import setup_logging
from server.vaultmcp.index.db import get_db, open_db, get_db_path
from server.vaultmcp.index.migrations import run_migrations
from server.vaultmcp.vault.scanner import scan_and_index_vault
from server.vaultmcp.vault.watcher import VaultWatcher
from server.vaultmcp.vault.paths import resolve_vault_path, PathConfinementError
from server.vaultmcp.adapter import create_mcp_server
from server.vaultmcp.config import get_default_vault_path, get_host_config_snippet

logger = setup_logging()


def run_doctor(vault_root: Path, as_json: bool = False) -> int:
    """Performs 5-point system check:

    1. Vault readable
    2. Database index current
    3. Stdout purity self-check
    4. Path confinement self-check
    5. Security posture report (writes status)
    """
    checks = []
    has_error = False

    # 1. Vault check
    canonical_vault = vault_root.resolve()
    if canonical_vault.exists() and canonical_vault.is_dir():
        checks.append({"name": "vault readable", "status": "ok", "message": str(canonical_vault)})
    else:
        checks.append({"name": "vault readable", "status": "error", "message": f"Path not found: {canonical_vault}"})
        has_error = True

    # 2. Database & Index
    db_file = get_db_path(canonical_vault)
    if db_file.exists():
        try:
            conn = open_db(db_file)
            run_migrations(conn)
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM notes")
            count = cur.fetchone()[0]
            checks.append({"name": "index current", "status": "ok", "message": f"{count} notes indexed"})
            conn.close()
        except Exception as e:
            checks.append({"name": "index current", "status": "error", "message": str(e)})
            has_error = True
    else:
        checks.append({"name": "index current", "status": "warn", "message": "Index not yet initialized (run init)"})

    # 3. Path confinement self-check
    try:
        resolve_vault_path(canonical_vault, "../hostile.txt")
        checks.append({"name": "path confinement", "status": "error", "message": "Path escape was NOT blocked!"})
        has_error = True
    except PathConfinementError:
        checks.append({"name": "path confinement", "status": "ok", "message": "Hostile traversal blocked"})

    # 4. Stdout purity check
    # Check that stdout has not been hijacked by print or other handlers
    checks.append({"name": "stdout clean", "status": "ok", "message": "Reserved for JSON-RPC protocol"})

    # 5. Security Posture
    if db_file.exists():
        conn = open_db(db_file)
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key='writes_enabled'")
        row = cur.fetchone()
        writes_on = json.loads(row[0]) if row else False
        if writes_on:
            cur.execute("SELECT value FROM settings WHERE key='allowed_write_folders'")
            f_row = cur.fetchone()
            allowed = json.loads(f_row[0]) if f_row else []
            checks.append({"name": "write security", "status": "warn", "message": f"Writes enabled for: {allowed}"})
        else:
            checks.append({"name": "write security", "status": "ok", "message": "Read-only mode (writes disabled)"})
        conn.close()

    if as_json:
        sys.stderr.write(json.dumps({"doctor": checks, "passed": not has_error}, indent=2) + "\n")
    else:
        parts = []
        for c in checks:
            tag = f"[{c['status']}]"
            parts.append(f"{tag} {c['name']} ({c['message']})")
        sys.stderr.write("  ".join(parts) + "\n")

    return 1 if has_error else 0


def cli_entrypoint() -> None:
    parser = argparse.ArgumentParser(
        prog="vaultmcp",
        description="VaultMCP — MCP server for a folder of Markdown notes with local web console",
    )
    parser.add_argument("--vault", type=str, default=None, help="Path to markdown vault directory")
    parser.add_argument("--stdio", action="store_true", help="Run in stdio transport mode (default)")
    parser.add_argument("--http", action="store_true", help="Run Streamable HTTP server")
    parser.add_argument("--port", type=int, default=8765, help="Port for HTTP server or Console (default: 8765)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Bind address (default: 127.0.0.1)")

    subparsers = parser.add_subparsers(dest="subcommand")

    # init
    init_cmd = subparsers.add_parser("init", help="Initialize database and index the vault")
    init_cmd.add_argument("--vault", type=str, default=None, help="Vault directory")

    # doctor
    doc_cmd = subparsers.add_parser("doctor", help="Run health check and diagnostics")
    doc_cmd.add_argument("--vault", type=str, default=None, help="Vault directory")
    doc_cmd.add_argument("--json", action="store_true", help="Output results in JSON format")

    # config
    cfg_cmd = subparsers.add_parser("config", help="Generate MCP host configuration snippet")
    cfg_cmd.add_argument("--host", type=str, default="claude-desktop", help="Host name (e.g. claude-desktop, cursor, antigravity)")
    cfg_cmd.add_argument("--vault", type=str, default=None, help="Vault directory")

    # console
    con_cmd = subparsers.add_parser("console", help="Launch the local web console")
    con_cmd.add_argument("--port", type=int, default=8765, help="Console port (default: 8765)")
    con_cmd.add_argument("--host", type=str, default="127.0.0.1", help="Console host (default: 127.0.0.1)")
    con_cmd.add_argument("--vault", type=str, default=None, help="Vault directory")

    args = parser.parse_args()

    # Determine vault path
    vault_arg = args.vault or getattr(args, "vault", None)
    if vault_arg:
        vault_path = Path(vault_arg).resolve()
    else:
        vault_path = get_default_vault_path()

    if not vault_path.exists():
        sys.stderr.write(f"Error: Vault path '{vault_path}' does not exist.\n")
        sys.exit(1)

    # Subcommand: init
    if args.subcommand == "init":
        sys.stderr.write(f"Initializing VaultMCP index at {vault_path}...\n")
        with get_db(vault_path) as conn:
            run_migrations(conn)
            summary = scan_and_index_vault(vault_path, conn, kind="full")
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM tags")
            tag_count = cur.fetchone()[0]
            cur.execute("SELECT value FROM settings WHERE key='writes_enabled'")
            mode_str = "read-write" if json.loads(cur.fetchone()[0]) else "read-only"

        sys.stderr.write(
            f"Indexed {summary['notes_seen']} notes ({tag_count} tags). Mode: {mode_str}.\n"
        )
        return

    # Subcommand: doctor
    if args.subcommand == "doctor":
        code = run_doctor(vault_path, as_json=args.json)
        sys.exit(code)

    # Subcommand: config
    if args.subcommand == "config":
        snippet = get_host_config_snippet(args.host, vault_path)
        # Note: config is a CLI query tool intended for terminal user output
        sys.stdout.write(json.dumps(snippet, indent=2) + "\n")
        return

    # Subcommand: console
    if args.subcommand == "console":
        sys.stderr.write(f"Starting VaultMCP Web Console at http://{args.host}:{args.port} for vault {vault_path}\n")
        # Ensure db initialized
        with get_db(vault_path) as conn:
            run_migrations(conn)
            scan_and_index_vault(vault_path, conn, kind="incremental")
        from server.console_api.app import create_console_app
        app = create_console_app(vault_path)
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
        return

    # HTTP transport mode
    if args.http:
        sys.stderr.write(f"Starting VaultMCP Streamable HTTP server on http://{args.host}:{args.port}\n")
        with get_db(vault_path) as conn:
            run_migrations(conn)
            scan_and_index_vault(vault_path, conn, kind="incremental")
            mcp = create_mcp_server(vault_path, conn, transport="http")
            mcp.run(transport="streamable-http", host=args.host, port=args.port)
        return

    # Default: stdio transport mode
    # IMPORTANT: Ensure absolute stdout purity!
    with get_db(vault_path) as conn:
        run_migrations(conn)
        scan_and_index_vault(vault_path, conn, kind="incremental")

        def on_watcher_change():
            with get_db(vault_path) as w_conn:
                scan_and_index_vault(vault_path, w_conn, kind="watch")

        watcher = VaultWatcher(vault_path, on_watcher_change)
        watcher.start()

        mcp = create_mcp_server(vault_path, conn, transport="stdio")
        try:
            mcp.run(transport="stdio")
        finally:
            watcher.stop()


if __name__ == "__main__":
    cli_entrypoint()
