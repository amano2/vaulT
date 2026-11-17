# 🗄️ VaultMCP

<div align="center">

[![Python](https://img.shields.io/badge/python-3.11+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://python.org)
[![MCP Protocol](https://img.shields.io/badge/MCP_Protocol-2024--11--05-blue.svg?style=flat)](https://modelcontextprotocol.io/)
[![Tests](https://img.shields.io/badge/tests-13%20passed-brightgreen.svg?style=flat)](server/tests)
[![Conformance](https://img.shields.io/badge/conformance-100%25-success.svg?style=flat)](eval/conformance_runner.py)
[![Tool-Use Eval](https://img.shields.io/badge/tool--use%20eval-100%25%20(70%2F70)-brightgreen.svg?style=flat)](eval/tool_use_eval.py)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

**A secure, production-grade Model Context Protocol (MCP) server for local Markdown note vaults (Obsidian, Foam, Logseq).**

*High-precision BM25 section search • Strict path confinement • Scoped writes with automated backups • Guaranteed stdout purity • Embedded web audit console*

[Features](#-key-features) •
[Architecture](#-architecture) •
[Quickstart](#-quickstart) •
[Obsidian Integration](#-live-obsidian-integration) •
[Interactive Workbench](#-interactive-landing-page--workbench) •
[Host Configuration](#-mcp-host-configuration) •
[Tool Reference](#-tool-reference) •
[Security Model](#-security--safety-model) •
[Evaluation](#-test--evaluation-suite)

</div>

---

## 🌟 Key Features

| Capability | Highlights |
|---|---|
| ⚡ **FTS5 Section Search** | Fast BM25 section-level passages with heading weight boosts (`H1 > H2 > H3`), folder restrictions, and tag filters. |
| 🛡️ **Zero-Trust Path Confinement** | Canonical `realpath` resolution rejects directory traversal (`../`), arbitrary symlinks, null bytes, and path tricks. |
| ✍️ **Safe Scoped Writes** | Opt-in writes (`writes_enabled = false` by default), folder confinement (`allowed_write_folders = ["inbox"]`), automated pre-write backup snapshots, and zero deletion capability. |
| 🧼 **Guaranteed Stdout Purity** | Standard output is 100% reserved for JSON-RPC framing. Logging streams strictly to standard error (`stderr`), eliminating framing corruption. |
| 🌐 **Dual Transport Architecture** | Native **Stdio** for desktop MCP hosts, and streamable **HTTP** (SSE) with constant-time SHA-256 Bearer Token auth and folder scoping. |
| 📊 **Embedded Web Console** | Single-port FastAPI + Tailwind SPA on port `8765` featuring system diagnostics, an interactive Tool Explorer with raw JSON-RPC inspection, audit logs, and instant backup rollback. |
| 🩺 **Self-Healing Diagnostics** | `vaultmcp doctor` CLI validates vault paths, SQLite schema integrity, FTS5 index sync, and JSON-RPC stdout purity in seconds. |

---

## 🏛️ Architecture

```
                  ┌────────────────────────────────────────────────────────┐
                  │                 MCP Host Applications                  │
                  │   Claude Desktop  •  Cursor  •  Antigravity  •  Zed    │
                  └───────────────────────────┬────────────────────────────┘
                                              │
                      ┌───────────────────────┴───────────────────────┐
                      │                                               │
               Stdio Transport                                  HTTP Transport
          (Pure JSON-RPC on stdout)                     (SSE + SHA-256 Bearer Token)
                      │                                               │
                      └───────────────────────┬───────────────────────┘
                                              ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │                                   VaultMCP Core Engine                                  │
 │                                                                                         │
 │   ┌──────────────────────┐   ┌───────────────────────┐   ┌──────────────────────────┐   │
 │   │   Path Confinement   │   │     Token Auth &      │   │     Logging Setup        │   │
 │   │  Canonical realpath  │   │     Scope Checker     │   │   stderr only (pure RPC) │   │
 │   └──────────┬───────────┘   └───────────┬───────────┘   └────────────┬─────────────┘   │
 │              │                           │                            │                 │
 │   ┌──────────▼───────────────────────────▼────────────────────────────▼─────────────┐   │
 │   │                                Tools & Resources                                │   │
 │   │  list_notes • search_notes • read_note • list_tags • get_backlinks • create/append │   │
 │   │  note://{path} resources • summarize_note / find_related prompts                │   │
 │   └──────────┬───────────────────────────┬────────────────────────────┬─────────────┘   │
 │              │                           │                            │                 │
 │   ┌──────────▼───────────┐   ┌───────────▼───────────┐   ┌────────────▼─────────────┐   │
 │   │ Markdown/Frontmatter │   │ SQLite FTS5 Indexer   │   │  Pre-Write Backup Engine │   │
 │   │  Parser & Link Graph │   │ BM25 & Heading Boosts │   │  Diff Tracking & Restore │   │
 │   └──────────┬───────────┘   └───────────┬───────────┘   └────────────┬─────────────┘   │
 └──────────────┼───────────────────────────┼────────────────────────────┼─────────────────┘
                │                           │                            │
                ▼                           ▼                            ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │                                    Local Note Vault                                     │
 │   📁 notes/                      📁 .vaultmcp/                                          │
 │   ├── inbox/                     ├── index.db (SQLite FTS5 + Schema Migrations)         │
 │   ├── projects/                  ├── config.json                                        │
 │   └── welcome.md                 └── backups/ (Timestamped pre-write snapshots)        │
 └─────────────────────────────────────────────────────────────────────────────────────────┘
                                            ▲
                                            │ HTTP / JSON API
 ┌──────────────────────────────────────────┴──────────────────────────────────────────────┐
 │                     Embedded Web Console (http://127.0.0.1:8765)                        │
 │        Dashboard  •  Interactive Tool Runner  •  Audit Logs  •  Config Generator        │
 └─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quickstart

### Prerequisites

- Python 3.11 or higher
- Git

### 1. Installation

Clone and install dependencies in editable mode:

```bash
git clone https://github.com/amano2/vaultmcp.git
cd vaultmcp
pip install -e .
```

### 2. Initialize Your Vault

Create `.vaultmcp/index.db` and index all Markdown notes:

```bash
python -m server.vaultmcp.main init --vault /path/to/my/notes
```

### 3. Verify Health with Doctor

Run comprehensive pre-flight verification:

```bash
python -m server.vaultmcp.main doctor --vault /path/to/my/notes
```

Output:
```text
[ok] Vault directory exists and is accessible (/path/to/my/notes)
[ok] Internal directory exists (.vaultmcp)
[ok] Configuration file is valid
[ok] SQLite index exists and passes schema integrity checks
[ok] Path confinement test passed (traversal blocked)
[ok] Stdout purity confirmed (zero bytes leaked to stdout during init)
All diagnostics passed! VaultMCP is ready.
```

### 4. Launch the Web Console

Start the embedded FastAPI + Tailwind web dashboard:

```bash
python -m server.vaultmcp.main console --vault /path/to/my/notes --port 8765
```

Navigate to **`http://127.0.0.1:8765`** to inspect index stats, test tools interactively, view live audit logs, and generate host configuration files.

---

## 🔮 Live Obsidian Integration

VaultMCP is designed to run directly underneath **[Obsidian](https://obsidian.md)** or any Markdown-based note-taking environment:

1. **Open Vault in Obsidian:** In Obsidian, select *"Open folder as vault"* and select your notes directory (e.g., `fixtures/test_vault`).
2. **Visual Knowledge Graph:** Press `Ctrl + G` in Obsidian to view the full interactive wikilink graph (`[[note]]` connections) mapped by VaultMCP's link index.
3. **Real-Time Assistant Updates:** When an AI assistant calls `append_to_note` or `create_note`, Obsidian detects the file system mutation and live-types the update directly onto your screen without an app restart.
4. **Bidirectional Watching:** When you edit notes in Obsidian, VaultMCP's debounced background watcher (`watcher.py`) automatically updates the SQLite FTS5 index in under 2 seconds.

---

## 💎 Interactive Landing Page & Workbench

VaultMCP includes a rich, reactive browser-based Landing Page & Tool Workbench ([index.html](index.html)) with zero external dependencies:
- **Interactive Terminal Simulator:** Simulates real-time JSON-RPC initialize handshakes, BM25 searches, and hostile path traversal interceptions.
- **Live Tool Workbench:** Execute calls against a simulated or live VaultMCP server with side-by-side JSON-RPC request and response inspection.
- **Client Configuration Generator:** 1-click copy-paste JSON snippets for Claude Desktop, Cursor IDE, and Antigravity.

To launch the landing page:
```bash
# Double-click index.html or serve locally:
python -m http.server 8080
```
Then navigate to **`http://localhost:8080/index.html`**.

---

## 💻 MCP Host Configuration

### Claude Desktop

Add VaultMCP to your Claude Desktop configuration (`claude_desktop_config.json`):

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "vaultmcp": {
      "command": "python",
      "args": [
        "-m",
        "server.vaultmcp.main",
        "--vault",
        "/absolute/path/to/your/notes",
        "--stdio"
      ]
    }
  }
}
```

### Cursor

In Cursor settings under **Features > MCP Servers > Add New MCP Server**:

- **Name**: `vaultmcp`
- **Type**: `command`
- **Command**: `python -m server.vaultmcp.main --vault /absolute/path/to/your/notes --stdio`

### Google Antigravity / Gemini CLI

In your MCP configuration file:

```json
{
  "mcpServers": {
    "vaultmcp": {
      "command": "python",
      "args": ["-m", "server.vaultmcp.main", "--vault", "/absolute/path/to/your/notes", "--stdio"]
    }
  }
}
```

Or generate auto-formatted config blocks using the built-in CLI:

```bash
python -m server.vaultmcp.main config --host claude-desktop --vault /path/to/my/notes
python -m server.vaultmcp.main config --host cursor --vault /path/to/my/notes
```

---

## 🛠️ Tool Reference

VaultMCP exposes a fine-grained tool surface designed for model reliability and safety:

| Tool | Parameters | Description | Risk Level |
|---|---|---|:---:|
| `list_notes` | `folder: str | None`<br>`limit: int = 50` | List note relative paths, titles, and modification timestamps with optional folder scoping. | `read` |
| `search_notes` | `query: str`<br>`folder: str | None`<br>`tag: str | None`<br>`top_k: int = 5` | Full-text search across section passages using SQLite FTS5 BM25 ranking with heading boosts. | `read` |
| `read_note` | `path: str`<br>`section: str | None` | Read note contents, front matter, and metadata. Optionally fetches an exact heading section. | `read` |
| `list_tags` | `prefix: str | None` | Discover all front matter and inline tags with occurrence counts and note associations. | `read` |
| `get_backlinks` | `path: str` | Find all incoming references (`[[wikilink]]` and markdown links) to a note. | `read` |
| `create_note` | `path: str`<br>`content: str` | Create a new markdown note in an authorized write folder. Refuses to overwrite existing files. | `write` |
| `append_to_note` | `path: str`<br>`content: str`<br>`heading: str | None` | Append content under a heading or at note end. Creates an automated backup snapshot first. | `write` |

### Resources & Prompts

- **Resource Scheme**: `note://{path}` allows MCP clients to read live markdown note content directly as structured resources.
- **Prompt Templates**:
  - `summarize_note`: Generates a structured synthesis of any vault note.
  - `find_related`: Explores cross-note connections via tag overlap, shared headings, and link graph backlinks.

---

## 🔒 Security & Safety Model

VaultMCP is built under the assumption that LLM outputs and notes may contain untrusted or adversarial content.

1. **Strict Path Confinement**:
   - Every path parameter is canonicalized via `os.path.realpath`.
   - Any path resolving outside the vault root raises an immediate `PermissionError`.
   - Rejects `..`, null bytes (`\0`), and absolute path escapes.
2. **Opt-In Scoped Writes**:
   - `writes_enabled` is `false` by default. Must be explicitly toggled in `.vaultmcp/config.json`.
   - Writes are constrained strictly to designated folders (`allowed_write_folders`, e.g., `["inbox"]`).
   - `create_note` will never overwrite an existing note.
   - **No file deletion tool exists** in the MCP interface.
3. **Automated Pre-Write Backups**:
   - Before modifying any file in `append_to_note`, a timestamped backup is saved to `.vaultmcp/backups/`.
   - The embedded web console provides visual unified diffs and one-click rollback.
4. **Token Verification**:
   - HTTP transport tokens use constant-time `hmac.compare_digest` to prevent timing attacks.
   - Separate token scopes for `read` vs `read_write`.
5. **Stdout Purity**:
   - Stdout is reserved exclusively for JSON-RPC framing.
   - All server logging, initialization messages, and diagnostics go to `stderr`.

---

## 🧪 Test & Evaluation Suite

VaultMCP includes a comprehensive suite of unit tests, security checks, and automated LLM tool-calling evaluations:

### 1. Pytest Unit Suite

```bash
pytest server/tests -v
```

```text
server/tests/test_console_api.py::test_console_health PASSED             [  7%]
server/tests/test_console_api.py::test_console_tools_list PASSED         [ 15%]
server/tests/test_indexer.py::test_incremental_indexing PASSED           [ 23%]
server/tests/test_indexer.py::test_fts5_bm25_search PASSED               [ 30%]
server/tests/test_mcp_client.py::test_mcp_protocol_handshake PASSED      [ 38%]
server/tests/test_migrations.py::test_database_migrations PASSED         [ 46%]
server/tests/test_paths.py::test_path_traversal_prevention PASSED        [ 53%]
server/tests/test_paths.py::test_symlink_confinement PASSED              [ 61%]
server/tests/test_stdout_purity.py::test_stdout_pure_jsonrpc PASSED      [ 69%]
server/tests/test_tools_read.py::test_read_tools PASSED                  [ 76%]
server/tests/test_tools_read.py::test_backlinks_and_tags PASSED          [ 84%]
server/tests/test_tools_write.py::test_write_safety_and_backups PASSED   [ 92%]
server/tests/test_tools_write.py::test_write_folder_confinement PASSED   [100%]

============================= 13 passed in 8.98s =============================
```

### 2. Conformance & Tool-Use Evaluation

VaultMCP includes a synthetic dataset of **70 challenging real-world queries** across 7 intent categories (broad search, targeted lookup, tag aggregation, link analysis, scoped creation, structured append, and negative non-matching queries).

```bash
# Run MCP Protocol Conformance
python eval/conformance_runner.py

# Run Tool Selection Benchmark
python eval/tool_use_eval.py
```

| Benchmark | Target | Result | Status |
|---|:---:|:---:|:---:|
| **MCP Protocol Conformance** | 100% | **100%** | ✅ PASS |
| **Tool Selection Accuracy** | > 95% | **100.0% (70/70)** | ✅ PASS |
| **Path Confinement Security** | 100% | **100%** | ✅ PASS |
| **Stdout Framing Purity** | 0 leaked bytes | **0 leaked bytes** | ✅ PASS |

---

## 📁 Repository Structure

```text
vaultmcp/
├── .github/workflows/ci.yml       # Automated GitHub Actions CI workflow
├── console/                       # Web Console static assets
├── docs/                          # Architecture & design specifications
│   ├── PRD.md                     # Product Requirements Document
│   ├── TRD.md                     # Technical Requirements Document
│   ├── UI-UX.md                   # Web Console UX specifications
│   └── BACKEND-SCHEMA.md          # SQLite FTS5 schema & migrations
├── eval/                          # Conformance & evaluation benchmark
│   ├── dataset/prompts.json       # 70-prompt tool-use evaluation dataset
│   ├── conformance_runner.py      # MCP schema & conformance checker
│   └── tool_use_eval.py           # Tool selection accuracy evaluation
├── fixtures/test_vault/           # Fixture test vault with tricky edge cases
├── server/
│   ├── console_api/app.py         # FastAPI Web Console backend
│   ├── vaultmcp/
│   │   ├── adapter.py             # Official MCP SDK server integration
│   │   ├── auth.py                # Constant-time SHA-256 token verification
│   │   ├── config.py              # Host configuration generator
│   │   ├── logging_setup.py       # Guaranteed stderr-only logging
│   │   ├── main.py                # Unified CLI (init, doctor, console, stdio, http)
│   │   ├── index/                 # SQLite connection, FTS5 BM25, schema migrations
│   │   ├── tools/                 # Tool definitions (read, search, tags, backlinks, write)
│   │   └── vault/                 # Path confinement, parser, scanner, watcher, backups
│   └── tests/                     # 13 comprehensive pytest test cases
├── Makefile                       # Developer shortcuts (test, lint, format)
├── pyproject.toml                 # Packaging & dependencies
└── README.md                      # Documentation
```

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.
