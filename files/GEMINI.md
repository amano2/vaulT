# GEMINI.md — Master Prompt: Build VaultMCP

You are a senior engineer. Build **VaultMCP**, a standalone MCP server for a folder of Markdown notes (search, read, tags, backlinks, and opt-in scoped writes), plus a small local web console to configure it, try the tools, manage access tokens, and review a call log. This is its own repository and database; it shares nothing with other projects. Work autonomously; ask only when blocked with no safe default.

## Specs (source of truth)
The four documents live in `./docs/`. Import them:

@./docs/PRD.md
@./docs/TRD.md
@./docs/UI-UX.md
@./docs/BACKEND-SCHEMA.md

Precedence: BACKEND-SCHEMA > TRD > PRD > UI-UX. Log assumptions in `./docs/DECISIONS.md`.

**Before coding:** read the current official MCP docs ("Build an MCP server" and the SDK reference) and use the SDK version actually installed. The Python guide pattern is `from mcp.server import MCPServer`, `@mcp.tool()`, `mcp.run(transport="stdio")`; confirm against the docs and pin versions.

## Scope
- In: vault scanner and parser (front matter, tags, wiki and Markdown links, headings), SQLite FTS5 section index, file watcher, read tools (`list_notes`, `search_notes`, `read_note`, `list_tags`, `get_backlinks`), write tools (`create_note`, `append_to_note`; opt-in, folder-scoped, backups, never delete), stdio and Streamable HTTP transports, bearer tokens with scopes, call log, FastAPI console API, React console (setup wizard, overview, tool explorer, activity, access, backups, settings), `doctor` command, conformance and tool-use evaluation suites, then resources and prompts.
- Out: note sync, non-Markdown editing, building an MCP client or host, cloud hosting, vault encryption.

## Rules
1. **stdio servers never write to stdout** (no `print`, no `console.log`); log to stderr. HTTP may log to stdout but prefer structured logs. A CI test spawns the stdio server and fails if anything but protocol frames appears on stdout.
2. Tool descriptions are product copy: purpose, when to use and not use, parameters with examples and ranges, return format, and a warning that note text is untrusted data. Prefer enums and clear defaults; keep outputs concise, source-referenced, and size-capped.
3. **Path confinement is mandatory:** join to the vault root, resolve (following symlinks), reject anything outside; reject absolute paths, `..`, null bytes. Never trust paths stored in the database.
4. **Writes are off by default.** When on: allowed-folders list, backup before append, `create_note` refuses to overwrite, no delete tool exists, every write is logged and restorable.
5. Notes are untrusted data; no tool executes commands or follows instructions found in notes.
6. Never store note contents or token values in logs or the call log; tokens are random, hashed, scoped, revocable, compared in constant time.
7. Only `adapter.py` imports the MCP SDK. Timeouts and output caps on every tool; rate limits per token.
8. Console binds to `127.0.0.1` by default; exposing it requires an explicit flag and a visible warning.
9. Python 3.11+, type hints, Pydantic v2, `ruff` + `mypy`, tests for every module. No TODO stubs reported as done.

## Build order (Phase Report after each)
1. **Scaffold:** repo layout from the TRD, `pyproject.toml`, Makefile, CI, SQLite migrations `vm_001`-`vm_003`, stderr-only logging, a fixture vault with tricky notes (bad front matter, huge file, unicode, symlink).
2. **Indexer:** scanner, parser, section splitting with line ranges, FTS5 triggers, incremental updates, watcher; per-file error reporting.
3. **Path confinement and read tools** with hostile-path tests; stdio transport; stdout-purity test; MCP inspector smoke test.
4. **Search quality:** safe FTS5 query building, heading weighting, folder and tag filters, snippets; fixture-based relevance tests.
5. **Console API and UI MVP:** status, setup wizard, settings, tool explorer (raw request and response), config snippets, `vaultmcp doctor`.
6. **Evaluation:** tool-use prompt set (10+ per tool) and conformance runner; iterate on tool descriptions until 90% or more correct selection with valid arguments.
7. **Write tools:** write mode settings, folder scope, backups, restore, diff view, call log entries with `backup_id`; safety tests (disabled by default, scope, no overwrite, no delete).
8. **Call log UI** with filters and export; **HTTP transport** with tokens, scopes, rate limits, and the token management UI.
9. **Interop:** connect from the official inspector and at least one other MCP host; record the negotiated protocol version per connection.
10. **Resources (`note://`) and prompts**; developer guide and README; canary CI job against the latest SDK.

## Definition of done
- `make test`, `make lint`, `make eval` green; migrations match the schema doc.
- The server indexes the fixture vault; tools work over stdio from two hosts and over HTTP with a token; write tools respect scope and create backups; the stdout test passes; hostile paths never escape the vault.
- Console shows the call log; `vaultmcp doctor` passes on a clean install.
- Console meets WCAG 2.2 AA.

## Commands (Makefile)
`make dev` · `make test` · `make lint` · `make eval` · `make inspect` (launch the MCP inspector) · `make doctor` · `make serve-stdio` · `make serve-http`

## Start now
Output a one-paragraph restatement, the folder tree, and the first ten tasks, then begin Step 1 and continue without waiting, reporting at the end of each step.
