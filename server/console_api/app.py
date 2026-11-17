"""FastAPI application for the VaultMCP Web Console.

Provides REST endpoints for vault status, configuration, tool exploration,
call audit log, token management, backups, and hosts config snippets.
Also serves the local web console SPA interface.
"""

from pathlib import Path
import json
import sqlite3
import csv
import io
import time
import contextlib
from typing import Any
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from server.vaultmcp.index.db import get_db, open_db, get_db_path
from server.vaultmcp.index.migrations import run_migrations
from server.vaultmcp.vault.scanner import scan_and_index_vault
from server.vaultmcp.vault.backup import restore_backup
from server.vaultmcp.auth import generate_secure_token
from server.vaultmcp.config import get_host_config_snippet
from server.vaultmcp.tools.list_notes import list_notes_handler
from server.vaultmcp.tools.search_notes import search_notes_handler
from server.vaultmcp.tools.read_note import read_note_handler
from server.vaultmcp.tools.tags import list_tags_handler
from server.vaultmcp.tools.backlinks import get_backlinks_handler
from server.vaultmcp.tools.write import create_note_handler, append_to_note_handler
from server.vaultmcp.adapter import record_call_log


class SettingsUpdate(BaseModel):
    writes_enabled: bool | None = None
    allowed_write_folders: list[str] | None = None
    ignore_folders: list[str] | None = None
    max_result_bytes: int | None = None


class TokenCreate(BaseModel):
    name: str
    scope: str = "read"  # 'read' or 'read_write'
    folder_prefix: str | None = None
    rate_limit_per_min: int = 120
    expires_in_days: int | None = None


class ToolCallRequest(BaseModel):
    arguments: dict[str, Any] = {}


def create_console_app(vault_root: Path, db_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="VaultMCP Console", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    canonical_vault = vault_root.resolve()
    target_db_path = db_path.resolve() if db_path else get_db_path(canonical_vault)

    # Ensure migrations are always applied
    init_conn = open_db(target_db_path)
    try:
        run_migrations(init_conn)
    finally:
        init_conn.close()

    @contextlib.contextmanager
    def _get_db():
        conn = open_db(target_db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # 1. Status
    @app.get("/api/status")
    def get_status():
        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM notes")
            note_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM tags")
            tag_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM links")
            link_count = cur.fetchone()[0]
            cur.execute("SELECT value FROM settings WHERE key='writes_enabled'")
            writes_on = json.loads(cur.fetchone()[0])

            cur.execute("SELECT started_at, finished_at, errors FROM index_runs ORDER BY id DESC LIMIT 1")
            last_run = cur.fetchone()
            last_index_time = last_run["finished_at"] if last_run else None
            errors = json.loads(last_run["errors"]) if last_run and last_run["errors"] else []

            return {
                "vault_path": str(canonical_vault),
                "notes": note_count,
                "tags": tag_count,
                "links": link_count,
                "writes_enabled": writes_on,
                "last_indexed_at": last_index_time,
                "errors": errors,
            }

    # 2. Settings
    @app.get("/api/settings")
    def get_settings():
        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM settings")
            rows = cur.fetchall()
            return {r["key"]: json.loads(r["value"]) for r in rows}

    @app.put("/api/settings")
    def update_settings(update: SettingsUpdate):
        with _get_db() as conn:
            cur = conn.cursor()
            if update.writes_enabled is not None:
                cur.execute("UPDATE settings SET value = ? WHERE key='writes_enabled'", (json.dumps(update.writes_enabled),))
            if update.allowed_write_folders is not None:
                cur.execute("UPDATE settings SET value = ? WHERE key='allowed_write_folders'", (json.dumps(update.allowed_write_folders),))
            if update.ignore_folders is not None:
                cur.execute("UPDATE settings SET value = ? WHERE key='ignore_folders'", (json.dumps(update.ignore_folders),))
            if update.max_result_bytes is not None:
                cur.execute("UPDATE settings SET value = ? WHERE key='max_result_bytes'", (json.dumps(update.max_result_bytes),))
            conn.commit()
            return {"status": "ok"}

    # 3. Reindex
    @app.post("/api/reindex")
    def trigger_reindex():
        with _get_db() as conn:
            summary = scan_and_index_vault(canonical_vault, conn, kind="full")
            return summary

    # 4. Tools Catalog & Inspector
    @app.get("/api/tools")
    def list_available_tools():
        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM settings WHERE key='writes_enabled'")
            writes_on = json.loads(cur.fetchone()[0])
            cur.execute("SELECT value FROM settings WHERE key='allowed_write_folders'")
            allowed = json.loads(cur.fetchone()[0])

        tools = [
            {
                "name": "list_notes",
                "risk": "read",
                "description": "Browse and list available markdown notes within the vault.",
                "schema": {
                    "type": "object",
                    "properties": {
                        "folder": {"type": "string", "description": "Optional folder prefix, e.g. 'projects'"},
                        "limit": {"type": "integer", "description": "1 to 200 (default 50)"},
                    },
                },
                "enabled": True,
            },
            {
                "name": "search_notes",
                "risk": "read",
                "description": "Search notes by words and return the most relevant passages.",
                "schema": {
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string", "description": "Keywords or question"},
                        "folder": {"type": "string", "description": "Optional folder prefix"},
                        "tag": {"type": "string", "description": "Optional tag filter without #"},
                        "top_k": {"type": "integer", "description": "1 to 20 (default 5)"},
                    },
                },
                "enabled": True,
            },
            {
                "name": "read_note",
                "risk": "read",
                "description": "Read the full text or a specific section of a markdown note.",
                "schema": {
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string", "description": "Vault-relative note path"},
                        "section": {"type": "string", "description": "Optional heading name"},
                    },
                },
                "enabled": True,
            },
            {
                "name": "list_tags",
                "risk": "read",
                "description": "List all unique tags in the vault along with note frequency counts.",
                "schema": {
                    "type": "object",
                    "properties": {
                        "prefix": {"type": "string", "description": "Optional tag prefix filter"},
                    },
                },
                "enabled": True,
            },
            {
                "name": "get_backlinks",
                "risk": "read",
                "description": "Find all notes that link to a target note, showing referencing context lines.",
                "schema": {
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string", "description": "Target note path"},
                    },
                },
                "enabled": True,
            },
            {
                "name": "create_note",
                "risk": "write",
                "description": "Create a new markdown note in an allowed folder (refuses to overwrite).",
                "schema": {
                    "type": "object",
                    "required": ["path", "content"],
                    "properties": {
                        "path": {"type": "string", "description": "New note path in allowed folder"},
                        "content": {"type": "string", "description": "Markdown body content"},
                    },
                },
                "enabled": writes_on,
                "disabled_reason": None if writes_on else "Writes are currently disabled in settings",
                "allowed_folders": allowed,
            },
            {
                "name": "append_to_note",
                "risk": "write",
                "description": "Append content to an existing note with automatic backup snapshot.",
                "schema": {
                    "type": "object",
                    "required": ["path", "content"],
                    "properties": {
                        "path": {"type": "string", "description": "Existing note path"},
                        "content": {"type": "string", "description": "Content to append"},
                        "heading": {"type": "string", "description": "Optional target heading"},
                    },
                },
                "enabled": writes_on,
                "disabled_reason": None if writes_on else "Writes are currently disabled in settings",
                "allowed_folders": allowed,
            },
        ]
        return tools

    # 5. Call Tool as Console
    @app.post("/api/tools/{name}/call")
    def call_tool_from_console(name: str, req: ToolCallRequest):
        start = time.perf_counter()
        args = req.arguments
        raw_request = {"jsonrpc": "2.0", "method": f"tools/call", "params": {"name": name, "arguments": args}}

        with _get_db() as conn:
            try:
                if name == "list_notes":
                    res = list_notes_handler(conn, folder=args.get("folder"), limit=int(args.get("limit", 50)))
                elif name == "search_notes":
                    res = search_notes_handler(conn, query=args.get("query", ""), folder=args.get("folder"), tag=args.get("tag"), top_k=int(args.get("top_k", 5)))
                elif name == "read_note":
                    res = read_note_handler(canonical_vault, conn, path=args.get("path", ""), section=args.get("section"))
                elif name == "list_tags":
                    res = list_tags_handler(conn, prefix=args.get("prefix"))
                elif name == "get_backlinks":
                    res = get_backlinks_handler(conn, path=args.get("path", ""))
                elif name == "create_note":
                    res = create_note_handler(canonical_vault, conn, path=args.get("path", ""), content=args.get("content", ""))
                elif name == "append_to_note":
                    res = append_to_note_handler(canonical_vault, conn, path=args.get("path", ""), content=args.get("content", ""), heading=args.get("heading"))
                else:
                    raise HTTPException(status_code=404, detail=f"Unknown tool: {name}")

                dur_ms = int((time.perf_counter() - start) * 1000)
                res_bytes = len(res.encode("utf-8"))
                risk = "write" if name in ("create_note", "append_to_note") else "read"
                status = "denied" if "Error: Write denied" in res else ("error" if res.startswith("Error:") else "ok")

                record_call_log(conn, "console", name, risk, args, status, None, dur_ms, res_bytes)

                raw_response = {
                    "jsonrpc": "2.0",
                    "result": {
                        "content": [{"type": "text", "text": res}],
                    },
                }

                return {
                    "status": status,
                    "duration_ms": dur_ms,
                    "result_bytes": res_bytes,
                    "output": res,
                    "raw_request": raw_request,
                    "raw_response": raw_response,
                }
            except Exception as e:
                dur_ms = int((time.perf_counter() - start) * 1000)
                record_call_log(conn, "console", name, "read", args, "error", str(e), dur_ms, 0)
                raise HTTPException(status_code=500, detail=str(e))

    # 6. Call Log Activity & Export
    @app.get("/api/calls")
    def get_calls(
        tool: str | None = None,
        status: str | None = None,
        transport: str | None = None,
        limit: int = 100,
    ):
        with _get_db() as conn:
            cur = conn.cursor()
            conditions = []
            params = {}
            if tool:
                conditions.append("tool = :tool")
                params["tool"] = tool
            if status:
                conditions.append("status = :status")
                params["status"] = status
            if transport:
                conditions.append("transport = :transport")
                params["transport"] = transport

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            sql = f"SELECT * FROM call_log {where} ORDER BY id DESC LIMIT :limit"
            params["limit"] = limit

            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                if r["arg_summary"]:
                    try:
                        r["arg_summary"] = json.loads(r["arg_summary"])
                    except Exception:
                        pass
            return rows

    @app.get("/api/calls/export")
    def export_calls(format: str = Query("json", pattern="^(json|csv)$")):
        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM call_log ORDER BY id DESC")
            rows = [dict(r) for r in cur.fetchall()]

            if format == "csv":
                output = io.StringIO()
                if rows:
                    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                return Response(
                    content=output.getvalue(),
                    media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=call_log.csv"},
                )
            else:
                return JSONResponse(
                    content=rows,
                    headers={"Content-Disposition": "attachment; filename=call_log.json"},
                )

    # 7. Tokens
    @app.get("/api/tokens")
    def list_tokens():
        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, name, scope, folder_prefix, rate_limit_per_min, created_at, last_used_at, expires_at, revoked_at FROM access_tokens ORDER BY id DESC")
            return [dict(r) for r in cur.fetchall()]

    @app.post("/api/tokens")
    def create_token(payload: TokenCreate):
        raw_token, token_hash = generate_secure_token()
        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO access_tokens (name, token_hash, scope, folder_prefix, rate_limit_per_min)
                VALUES (?, ?, ?, ?, ?)
                """,
                (payload.name, token_hash, payload.scope, payload.folder_prefix, payload.rate_limit_per_min),
            )
            token_id = cur.lastrowid
            return {
                "id": token_id,
                "name": payload.name,
                "scope": payload.scope,
                "raw_token": raw_token,
                "message": "Copy this token now. It will not be shown again.",
            }

    @app.delete("/api/tokens/{token_id}")
    def revoke_token(token_id: int):
        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE access_tokens SET revoked_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?", (token_id,))
            return {"status": "ok"}

    # 8. Backups and Restore
    @app.get("/api/backups")
    def list_backups():
        with _get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, note_path, backup_path, reason, size_bytes, created_at FROM backups ORDER BY id DESC LIMIT 100")
            return [dict(r) for r in cur.fetchall()]

    @app.post("/api/backups/{backup_id}/restore")
    def restore_backup_version(backup_id: int):
        with _get_db() as conn:
            res = restore_backup(canonical_vault, conn, backup_id)
            scan_and_index_vault(canonical_vault, conn, kind="incremental")
            return res

    # 9. Config Snippet
    @app.get("/api/config-snippet")
    def get_snippet(host: str = "claude-desktop"):
        return get_host_config_snippet(host, canonical_vault)

    # 10. SPA Console Web UI
    @app.get("/", response_class=HTMLResponse)
    def render_console_spa():
        return CONSOLE_HTML

    @app.get("/landing", response_class=HTMLResponse)
    def render_landing():
        landing_path = Path(__file__).resolve().parent.parent.parent / "index.html"
        if landing_path.exists():
            return landing_path.read_text(encoding="utf-8")
        return CONSOLE_HTML

    return app


CONSOLE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>VaultMCP — Console</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col">
  <!-- Header -->
  <header class="border-b border-slate-800 bg-slate-900/60 backdrop-blur sticky top-0 z-50">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
      <div class="flex items-center space-x-3">
        <span class="text-xl font-bold bg-gradient-to-r from-indigo-400 to-cyan-400 bg-clip-text text-transparent">VaultMCP</span>
        <span class="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700">v0.1</span>
        <span id="vault-path-badge" class="text-xs text-slate-400 mono truncate max-w-sm"></span>
      </div>
      <div class="flex items-center space-x-2">
        <a href="/landing" target="_blank" class="text-xs px-3 py-1.5 rounded-md bg-emerald-600/80 hover:bg-emerald-500 font-medium transition text-white">Project Showcase</a>
        <button onclick="reindexVault()" id="reindex-btn" class="text-xs px-3 py-1.5 rounded-md bg-indigo-600 hover:bg-indigo-500 font-medium transition">Reindex Vault</button>
      </div>
    </div>
  </header>

  <!-- Navigation Tabs -->
  <nav class="border-b border-slate-800 bg-slate-900/30">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex space-x-6 text-sm font-medium">
      <button onclick="switchTab('overview')" class="tab-btn py-3 border-b-2 border-indigo-500 text-indigo-400" data-tab="overview">Overview</button>
      <button onclick="switchTab('tools')" class="tab-btn py-3 border-b-2 border-transparent text-slate-400 hover:text-slate-200" data-tab="tools">Tool Explorer</button>
      <button onclick="switchTab('activity')" class="tab-btn py-3 border-b-2 border-transparent text-slate-400 hover:text-slate-200" data-tab="activity">Activity Log</button>
      <button onclick="switchTab('access')" class="tab-btn py-3 border-b-2 border-transparent text-slate-400 hover:text-slate-200" data-tab="access">Access & Tokens</button>
      <button onclick="switchTab('backups')" class="tab-btn py-3 border-b-2 border-transparent text-slate-400 hover:text-slate-200" data-tab="backups">Backups</button>
      <button onclick="switchTab('settings')" class="tab-btn py-3 border-b-2 border-transparent text-slate-400 hover:text-slate-200" data-tab="settings">Settings</button>
    </div>
  </nav>

  <!-- Main Content Areas -->
  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 flex-1 w-full">
    
    <!-- Tab 1: Overview -->
    <section id="tab-overview" class="space-y-6">
      <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div class="bg-slate-900 p-5 rounded-xl border border-slate-800">
          <div class="text-slate-400 text-xs font-medium uppercase tracking-wider">Indexed Notes</div>
          <div id="stat-notes" class="text-3xl font-bold mt-2">--</div>
        </div>
        <div class="bg-slate-900 p-5 rounded-xl border border-slate-800">
          <div class="text-slate-400 text-xs font-medium uppercase tracking-wider">Unique Tags</div>
          <div id="stat-tags" class="text-3xl font-bold mt-2">--</div>
        </div>
        <div class="bg-slate-900 p-5 rounded-xl border border-slate-800">
          <div class="text-slate-400 text-xs font-medium uppercase tracking-wider">Resolved Links</div>
          <div id="stat-links" class="text-3xl font-bold mt-2">--</div>
        </div>
        <div class="bg-slate-900 p-5 rounded-xl border border-slate-800">
          <div class="text-slate-400 text-xs font-medium uppercase tracking-wider">Write Mode</div>
          <div id="stat-mode" class="text-lg font-semibold mt-2">--</div>
        </div>
      </div>

      <div class="bg-slate-900 p-6 rounded-xl border border-slate-800">
        <h2 class="text-base font-semibold mb-4">Recent Tool Invocations</h2>
        <div id="overview-recent-calls" class="space-y-2 mono text-xs">
          Loading recent activity...
        </div>
      </div>
    </section>

    <!-- Tab 2: Tool Explorer -->
    <section id="tab-tools" class="hidden grid grid-cols-1 md:grid-cols-3 gap-6">
      <div class="bg-slate-900 p-4 rounded-xl border border-slate-800 space-y-2">
        <h2 class="text-xs uppercase tracking-wider font-semibold text-slate-400 mb-3">Available Tools</h2>
        <div id="tools-list-container" class="space-y-1">Loading tools...</div>
      </div>
      <div class="md:col-span-2 bg-slate-900 p-5 rounded-xl border border-slate-800 flex flex-col space-y-4">
        <div class="flex items-center justify-between">
          <h2 id="selected-tool-name" class="text-lg font-bold">Select a tool</h2>
          <span id="selected-tool-risk" class="text-xs px-2 py-0.5 rounded"></span>
        </div>
        <p id="selected-tool-desc" class="text-sm text-slate-400"></p>
        
        <form id="tool-exec-form" class="space-y-3" onsubmit="executeSelectedTool(event)">
          <div id="tool-params-container" class="space-y-3"></div>
          <button type="submit" id="tool-run-btn" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-md font-medium text-sm transition">Run Tool</button>
        </form>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4 flex-1">
          <div class="flex flex-col">
            <span class="text-xs font-medium text-slate-400 mb-1">Raw Request (JSON-RPC)</span>
            <pre id="tool-raw-req" class="bg-slate-950 p-3 rounded border border-slate-800 mono text-xs text-slate-300 overflow-auto flex-1 max-h-80">{}</pre>
          </div>
          <div class="flex flex-col">
            <span class="text-xs font-medium text-slate-400 mb-1">Raw Response</span>
            <pre id="tool-raw-res" class="bg-slate-950 p-3 rounded border border-slate-800 mono text-xs text-cyan-300 overflow-auto flex-1 max-h-80">No response yet.</pre>
          </div>
        </div>
      </div>
    </section>

    <!-- Tab 3: Activity Log -->
    <section id="tab-activity" class="hidden space-y-4">
      <div class="flex items-center justify-between">
        <h2 class="text-base font-semibold">Call Audit Log</h2>
        <div class="space-x-2">
          <a href="/api/calls/export?format=json" class="text-xs px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700">Export JSON</a>
          <a href="/api/calls/export?format=csv" class="text-xs px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700">Export CSV</a>
        </div>
      </div>
      <div class="overflow-x-auto bg-slate-900 rounded-xl border border-slate-800">
        <table class="w-full text-left text-xs">
          <thead class="bg-slate-950 text-slate-400 border-b border-slate-800">
            <tr>
              <th class="p-3">Time (UTC)</th>
              <th class="p-3">Transport</th>
              <th class="p-3">Tool</th>
              <th class="p-3">Risk</th>
              <th class="p-3">Status</th>
              <th class="p-3">Duration</th>
              <th class="p-3">Bytes</th>
            </tr>
          </thead>
          <tbody id="activity-table-body" class="divide-y divide-slate-800 mono"></tbody>
        </table>
      </div>
    </section>

    <!-- Tab 4: Access & Tokens -->
    <section id="tab-access" class="hidden space-y-6">
      <div class="bg-slate-900 p-6 rounded-xl border border-slate-800 space-y-4">
        <h2 class="text-base font-semibold">Generate Bearer Token (HTTP Access)</h2>
        <form onsubmit="createToken(event)" class="grid grid-cols-1 md:grid-cols-4 gap-3">
          <input id="token-name" type="text" placeholder="Token name (e.g. Remote Agent)" required class="bg-slate-950 border border-slate-800 px-3 py-2 rounded text-sm text-slate-100">
          <select id="token-scope" class="bg-slate-950 border border-slate-800 px-3 py-2 rounded text-sm text-slate-100">
            <option value="read">Scope: Read-only</option>
            <option value="read_write">Scope: Read-Write</option>
          </select>
          <input id="token-folder" type="text" placeholder="Folder prefix (optional)" class="bg-slate-950 border border-slate-800 px-3 py-2 rounded text-sm text-slate-100">
          <button type="submit" class="bg-indigo-600 hover:bg-indigo-500 rounded font-medium text-sm transition">Generate Token</button>
        </form>
        <div id="token-new-display" class="hidden p-3 bg-emerald-950/60 border border-emerald-800 rounded text-xs text-emerald-200 mono"></div>
      </div>

      <div class="bg-slate-900 p-6 rounded-xl border border-slate-800 space-y-4">
        <h2 class="text-base font-semibold">Active Tokens</h2>
        <div id="tokens-list" class="space-y-2 mono text-xs"></div>
      </div>
    </section>

    <!-- Tab 5: Backups -->
    <section id="tab-backups" class="hidden space-y-4">
      <h2 class="text-base font-semibold">Automated Pre-Write Snapshots</h2>
      <div id="backups-list" class="space-y-2"></div>
    </section>

    <!-- Tab 6: Settings -->
    <section id="tab-settings" class="hidden space-y-6">
      <div class="bg-slate-900 p-6 rounded-xl border border-slate-800 space-y-4 max-w-2xl">
        <h2 class="text-base font-semibold">Server Security Settings</h2>
        <form onsubmit="saveSettings(event)" class="space-y-4 text-sm">
          <div class="flex items-center space-x-3">
            <input id="setting-writes-enabled" type="checkbox" class="h-4 w-4 rounded bg-slate-950 border-slate-800 text-indigo-600">
            <label for="setting-writes-enabled" class="font-medium">Enable Write Tools (create_note, append_to_note)</label>
          </div>
          <div>
            <label class="block text-xs font-medium text-slate-400 mb-1">Allowed Write Folders (comma-separated)</label>
            <input id="setting-write-folders" type="text" placeholder="inbox, notes/drafts" class="w-full bg-slate-950 border border-slate-800 px-3 py-2 rounded text-slate-100">
          </div>
          <button type="submit" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded font-medium text-sm transition">Save Settings</button>
        </form>
      </div>
    </section>

  </main>

  <script>
    let allTools = [];
    let currentSelectedTool = null;

    async function fetchStatus() {
      const res = await fetch('/api/status');
      const data = await res.json();
      document.getElementById('vault-path-badge').innerText = data.vault_path;
      document.getElementById('stat-notes').innerText = data.notes;
      document.getElementById('stat-tags').innerText = data.tags;
      document.getElementById('stat-links').innerText = data.links;
      document.getElementById('stat-mode').innerText = data.writes_enabled ? 'Read-Write (Scoped)' : 'Read-Only (Default)';
      document.getElementById('stat-mode').className = data.writes_enabled ? 'text-lg font-semibold mt-2 text-amber-400' : 'text-lg font-semibold mt-2 text-emerald-400';
    }

    async function fetchRecentCalls() {
      const res = await fetch('/api/calls?limit=8');
      const calls = await res.json();
      const container = document.getElementById('overview-recent-calls');
      if (!calls.length) {
        container.innerHTML = '<span class="text-slate-500">No calls recorded yet.</span>';
        return;
      }
      container.innerHTML = calls.map(c => `
        <div class="p-2.5 rounded bg-slate-950/60 border border-slate-800/80 flex items-center justify-between">
          <div class="flex items-center space-x-3">
            <span class="px-1.5 py-0.5 rounded text-[10px] ${c.risk_class === 'write' ? 'bg-amber-950 text-amber-400 border border-amber-800' : 'bg-slate-800 text-slate-300'}">${c.risk_class}</span>
            <span class="font-medium text-slate-200">${c.tool}</span>
          </div>
          <div class="flex items-center space-x-3 text-slate-400">
            <span>${c.status}</span>
            <span>${c.duration_ms} ms</span>
            <span>${c.called_at.slice(11, 19)}</span>
          </div>
        </div>
      `).join('');
    }

    async function fetchTools() {
      const res = await fetch('/api/tools');
      allTools = await res.json();
      const container = document.getElementById('tools-list-container');
      container.innerHTML = allTools.map((t, i) => `
        <button onclick="selectTool(${i})" class="w-full text-left p-2.5 rounded hover:bg-slate-800 flex items-center justify-between text-xs transition">
          <span class="font-medium ${!t.enabled ? 'line-through text-slate-500' : 'text-slate-200'}">${t.name}</span>
          <span class="text-[10px] px-1.5 py-0.5 rounded ${t.risk === 'write' ? 'bg-amber-950 text-amber-400' : 'bg-slate-800 text-slate-400'}">${t.risk}</span>
        </button>
      `).join('');
      if (allTools.length > 0 && !currentSelectedTool) {
        selectTool(0);
      }
    }

    function selectTool(index) {
      currentSelectedTool = allTools[index];
      document.getElementById('selected-tool-name').innerText = currentSelectedTool.name;
      document.getElementById('selected-tool-desc').innerText = currentSelectedTool.description;
      const riskBadge = document.getElementById('selected-tool-risk');
      riskBadge.innerText = currentSelectedTool.risk;
      riskBadge.className = currentSelectedTool.risk === 'write' ? 'text-xs px-2 py-0.5 rounded bg-amber-950 text-amber-400 border border-amber-800' : 'text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300';

      const paramsContainer = document.getElementById('tool-params-container');
      const props = currentSelectedTool.schema.properties || {};
      paramsContainer.innerHTML = Object.entries(props).map(([key, info]) => `
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1">${key} <span class="text-slate-600">(${info.type})</span></label>
          <input type="${info.type === 'integer' ? 'number' : 'text'}" name="${key}" placeholder="${info.description || ''}" class="w-full bg-slate-950 border border-slate-800 px-3 py-2 rounded text-xs text-slate-100">
        </div>
      `).join('');
    }

    async function executeSelectedTool(e) {
      e.preventDefault();
      if (!currentSelectedTool) return;
      const formData = new FormData(e.target);
      const args = {};
      for (let [k, v] of formData.entries()) {
        if (v.trim() !== '') {
          args[k] = currentSelectedTool.schema.properties[k]?.type === 'integer' ? parseInt(v, 10) : v;
        }
      }

      document.getElementById('tool-raw-req').innerText = JSON.stringify({
        jsonrpc: '2.0',
        id: Date.now(),
        method: 'tools/call',
        params: { name: currentSelectedTool.name, arguments: args }
      }, null, 2);

      const res = await fetch(`/api/tools/${currentSelectedTool.name}/call`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ arguments: args })
      });
      const data = await res.json();
      document.getElementById('tool-raw-res').innerText = JSON.stringify(data.raw_response || data, null, 2);
      fetchStatus();
    }

    async function fetchActivity() {
      const res = await fetch('/api/calls?limit=100');
      const calls = await res.json();
      const tbody = document.getElementById('activity-table-body');
      tbody.innerHTML = calls.map(c => `
        <tr class="hover:bg-slate-900/80">
          <td class="p-3 text-slate-400">${c.called_at.slice(0, 19).replace('T', ' ')}</td>
          <td class="p-3">${c.transport}</td>
          <td class="p-3 font-semibold text-slate-200">${c.tool}</td>
          <td class="p-3"><span class="px-1.5 py-0.5 rounded text-[10px] ${c.risk_class === 'write' ? 'bg-amber-950 text-amber-400' : 'bg-slate-800 text-slate-400'}">${c.risk_class}</span></td>
          <td class="p-3 text-${c.status === 'ok' ? 'emerald' : (c.status === 'denied' ? 'amber' : 'rose')}-400">${c.status}</td>
          <td class="p-3 text-slate-400">${c.duration_ms} ms</td>
          <td class="p-3 text-slate-400">${c.result_bytes} B</td>
        </tr>
      `).join('');
    }

    async function fetchTokens() {
      const res = await fetch('/api/tokens');
      const tokens = await res.json();
      const container = document.getElementById('tokens-list');
      if (!tokens.length) {
        container.innerHTML = '<span class="text-slate-500">No active tokens generated.</span>';
        return;
      }
      container.innerHTML = tokens.map(t => `
        <div class="p-3 rounded bg-slate-950 border border-slate-800 flex items-center justify-between">
          <div>
            <div class="font-bold text-slate-200">${t.name} <span class="text-xs font-normal text-slate-400">(${t.scope})</span></div>
            <div class="text-[11px] text-slate-500">Folder: ${t.folder_prefix || 'Whole vault'} · Created: ${t.created_at.slice(0, 10)}</div>
          </div>
          ${t.revoked_at ? '<span class="text-rose-400 text-xs">Revoked</span>' : `<button onclick="revokeToken(${t.id})" class="text-xs px-2.5 py-1 bg-rose-950 text-rose-300 hover:bg-rose-900 rounded border border-rose-800">Revoke</button>`}
        </div>
      `).join('');
    }

    async function createToken(e) {
      e.preventDefault();
      const name = document.getElementById('token-name').value;
      const scope = document.getElementById('token-scope').value;
      const folder_prefix = document.getElementById('token-folder').value || null;
      const res = await fetch('/api/tokens', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, scope, folder_prefix })
      });
      const data = await res.json();
      const display = document.getElementById('token-new-display');
      display.classList.remove('hidden');
      display.innerText = `Token created: ${data.raw_token}\\n\\n${data.message}`;
      fetchTokens();
    }

    async function revokeToken(id) {
      if (!confirm('Revoke this access token?')) return;
      await fetch(`/api/tokens/${id}`, { method: 'DELETE' });
      fetchTokens();
    }

    async function fetchBackups() {
      const res = await fetch('/api/backups');
      const backups = await res.json();
      const container = document.getElementById('backups-list');
      if (!backups.length) {
        container.innerHTML = '<span class="text-slate-500 text-xs">No backups created yet.</span>';
        return;
      }
      container.innerHTML = backups.map(b => `
        <div class="p-3 bg-slate-900 border border-slate-800 rounded-lg flex items-center justify-between text-xs">
          <div>
            <div class="font-bold text-slate-200 mono">${b.note_path}</div>
            <div class="text-slate-400 text-[11px] mono">Reason: ${b.reason} · Size: ${b.size_bytes} B · Created: ${b.created_at.slice(0, 19).replace('T', ' ')}</div>
          </div>
          <button onclick="restoreBackup(${b.id})" class="px-3 py-1.5 bg-amber-600 hover:bg-amber-500 rounded font-medium text-slate-950 transition">Restore</button>
        </div>
      `).join('');
    }

    async function restoreBackup(id) {
      if (!confirm('Restore note from this backup snapshot?')) return;
      const res = await fetch(`/api/backups/${id}/restore`, { method: 'POST' });
      alert('Note successfully restored!');
      fetchBackups();
    }

    async function fetchSettings() {
      const res = await fetch('/api/settings');
      const s = await res.json();
      document.getElementById('setting-writes-enabled').checked = !!s.writes_enabled;
      document.getElementById('setting-write-folders').value = (s.allowed_write_folders || []).join(', ');
    }

    async function saveSettings(e) {
      e.preventDefault();
      const writes_enabled = document.getElementById('setting-writes-enabled').checked;
      const foldersStr = document.getElementById('setting-write-folders').value;
      const allowed_write_folders = foldersStr.split(',').map(s => s.trim()).filter(Boolean);
      await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ writes_enabled, allowed_write_folders })
      });
      alert('Settings saved successfully!');
      fetchStatus();
      fetchTools();
    }

    async function reindexVault() {
      const btn = document.getElementById('reindex-btn');
      btn.innerText = 'Indexing...';
      await fetch('/api/reindex', { method: 'POST' });
      btn.innerText = 'Reindex Vault';
      fetchStatus();
      fetchTools();
    }

    function switchTab(name) {
      document.querySelectorAll('section[id^="tab-"]').forEach(el => el.classList.add('hidden'));
      document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('border-indigo-500', 'text-indigo-400');
        btn.classList.add('border-transparent', 'text-slate-400');
      });
      const activeSec = document.getElementById('tab-' + name);
      if (activeSec) activeSec.classList.remove('hidden');
      const activeBtn = document.querySelector(`.tab-btn[data-tab="${name}"]`);
      if (activeBtn) {
        activeBtn.classList.remove('border-transparent', 'text-slate-400');
        activeBtn.classList.add('border-indigo-500', 'text-indigo-400');
      }

      if (name === 'overview') { fetchStatus(); fetchRecentCalls(); }
      if (name === 'tools') fetchTools();
      if (name === 'activity') fetchActivity();
      if (name === 'access') fetchTokens();
      if (name === 'backups') fetchBackups();
      if (name === 'settings') fetchSettings();
    }

    // Initialize
    fetchStatus();
    fetchRecentCalls();
  </script>
</body>
</html>
"""
