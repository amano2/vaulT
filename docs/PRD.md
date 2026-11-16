# VaultMCP — Product Requirements Document (PRD)

**Standalone project 4 of 5** · Version 0.1 · 14 Nov 2026

> **Inspired by:** Model Context Protocol docs, *Build an MCP server*. Ideas used: servers expose **tools** (functions a model can call, with user approval), **resources** (file-like data), and **prompts** (templates); an MCP host connects clients to servers; **stdio** servers must never write to stdout (log to stderr) while HTTP servers may; tool definitions come from type hints and docstrings; test a server from a host before relying on it. The docs target a recent protocol revision and a 2.x Python SDK; verify versions when implementing.

---

## 1. Summary
VaultMCP is an **MCP server for a folder of Markdown notes** (an Obsidian-style vault). Any MCP-capable assistant can search, read, and, with permission, create or append to notes. It ships with a small **web console** to configure the vault, manage access tokens, try the tools, and review a log of every call.

## 2. Problem
People keep knowledge in plain Markdown notes, but assistants cannot reach them safely. Ad-hoc scripts expose too much (whole disk, write access) and give no visibility into what an assistant did with your notes.

## 3. Goals and non-goals
**Goals**
- G1. A correct, well-documented MCP server that works with at least two independent MCP hosts.
- G2. Read access that is fast and precise (full-text search, tags, links) and write access that is opt-in, scoped, and auditable.
- G3. A console to configure, test, and monitor the server without editing files by hand.
- G4. Tool descriptions good enough that models choose and call tools correctly (measured).
- G5. Safe by default: vault-confined, read-only unless enabled, tokens for remote access.

**Non-goals (v1):** syncing notes across devices; editing non-Markdown files; building an MCP client or host; hosting as a public cloud service; encrypting the vault.

## 4. Personas
| Persona | Need |
|---|---|
| Note-taker | Ask an assistant about my notes without uploading them anywhere |
| Developer | Learn MCP by studying a clean, tested server |
| Cautious user | See and limit exactly what the assistant can read or change |

## 5. User stories
- Point VaultMCP at my vault folder and see how many notes were indexed.
- Connect a desktop assistant over stdio with a copy-paste config snippet.
- Ask the assistant to find notes about a topic and get passages with file names.
- Turn on write tools for one folder only; every write is logged and reversible.
- Open the console, call a tool by hand, and see the exact request and response.
- Create an access token for a remote HTTP client and revoke it later.
- See which tools were called, when, by which client, and whether they succeeded.

## 6. Features
| ID | Feature | Priority |
|---|---|---|
| V1 | Vault indexer: scan, parse front matter, tags, links, headings; full-text index; file watching | P0 |
| V2 | MCP tools: `list_notes`, `search_notes`, `read_note`, `list_tags`, `get_backlinks` (read) | P0 |
| V3 | Write tools: `create_note`, `append_to_note` (opt-in, folder-scoped) with automatic backups | P0 |
| V4 | stdio transport | P0 |
| V5 | Streamable HTTP transport with bearer tokens | P1 |
| V6 | Console: setup wizard, vault status, settings | P0 |
| V7 | Console: tool explorer (call tools, see raw requests and responses) | P1 |
| V8 | Call log with filters and export | P1 |
| V9 | Token management (create, scope, revoke) | P1 |
| V10 | Resources: notes exposed as `note://` resources | P1 |
| V11 | Prompts: reusable templates (for example, "summarise this note", "weekly review") | P2 |
| V12 | Tool-use evaluation set and conformance tests | P0 |

## 7. Functional requirements
- FR-1. The vault path is configured once; all file access is confined to it (no traversal, no symlink escape).
- FR-2. Tools are generated with precise types and docstrings; schemas are validated on every call.
- FR-3. Write tools are disabled by default. When enabled they require an allowed folder list, create a backup before changing a file, and never delete files.
- FR-4. stdio mode never writes to stdout except protocol messages; logs go to stderr.
- FR-5. HTTP mode requires a bearer token; tokens are stored hashed, can be scoped (read-only or read-write, folder prefix), and revoked.
- FR-6. Search returns passages with note path, heading, line range, and a score; results are size-capped.
- FR-7. Every call is logged (tool, argument summary, status, duration, client name) without storing note contents.
- FR-8. Changes made to files outside the server (editing in another app) are picked up by the watcher within a few seconds.
- FR-9. The console works offline on localhost and binds to `127.0.0.1` by default.

## 8. Non-functional requirements
| Area | Requirement |
|---|---|
| Speed | Index 10,000 notes in under 60 s; `search_notes` p95 under 200 ms; startup under 3 s with an existing index |
| Reliability | A malformed note never crashes the server; indexing errors are reported per file |
| Security | Vault confinement; read-only default; token auth for HTTP; secrets never logged |
| Compatibility | Works with two or more MCP hosts; protocol version recorded per connection |
| Accessibility | Console meets WCAG 2.2 AA |

## 9. Success metrics
| Metric | Target |
|---|---|
| Time from install to first successful tool call | Under 5 minutes |
| Tool-call success rate on the conformance suite | 100% |
| Correct tool selection with valid arguments on the tool-use set | 90% or higher |
| stdout pollution incidents | 0 |
| Path-escape attempts that succeed | 0 |

## 10. Release plan
| Phase | Scope |
|---|---|
| MVP | V1, V2, V4, V6, V12 |
| v1.1 | V3, V7, V8 |
| v1.2 | V5, V9 |
| v1.3 | V10, V11 |

## 11. Risks
| Risk | Mitigation |
|---|---|
| Assistant overwrites or corrupts notes | Write tools off by default, folder scope, no delete, backup before every write, undo from console |
| Prompt injection inside notes ("ignore previous instructions") | Return note text as data with clear delimiters; tool descriptions warn that content is untrusted; no tool executes commands |
| Path traversal | Resolve and verify every path against the vault root; test with hostile paths |
| SDK or protocol drift | Pin versions; one adapter module; conformance tests; canary job on latest |
| Poor tool descriptions cause wrong calls | Description checklist; tool-use evaluation; iterate on failures |

## 12. Acceptance criteria
The server indexes a sample vault; the tools work from two MCP hosts over stdio and from HTTP with a token; write tools respect folder scope and create backups; the stdout test passes; the console shows the call log; the tool-use and conformance suites pass.

## 13. Open questions
Which hosts to certify at launch? Support for wiki-style links and attachments? Optional semantic (embedding) search later?
