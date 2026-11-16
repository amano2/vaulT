"""Unit and integration tests for FastAPI Console API."""

from pathlib import Path
from starlette.testclient import TestClient
from server.console_api.app import create_console_app
from server.vaultmcp.index.db import open_db
from server.vaultmcp.index.migrations import run_migrations
from server.vaultmcp.vault.scanner import scan_and_index_vault


def test_console_api_endpoints(tmp_path: Path):
    fixture_vault = Path("fixtures/test_vault").resolve()
    db_path = tmp_path / "console_test.db"
    conn = open_db(db_path)
    run_migrations(conn)
    scan_and_index_vault(fixture_vault, conn, kind="full")
    conn.close()

    app = create_console_app(fixture_vault)
    client = TestClient(app)

    # 1. Status endpoint
    status_res = client.get("/api/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["notes"] >= 5
    assert "writes_enabled" in status_data

    # 2. Settings endpoint
    settings_res = client.get("/api/settings")
    assert settings_res.status_code == 200
    assert "ignore_folders" in settings_res.json()

    # Update settings
    put_res = client.put("/api/settings", json={"writes_enabled": True, "allowed_write_folders": ["inbox"]})
    assert put_res.status_code == 200
    assert put_res.json()["status"] == "ok"

    # Verify update persisted
    updated_settings = client.get("/api/settings").json()
    assert updated_settings["writes_enabled"] is True
    assert updated_settings["allowed_write_folders"] == ["inbox"]

    # 3. Tools listing
    tools_res = client.get("/api/tools")
    assert tools_res.status_code == 200
    tools_list = tools_res.json()
    assert len(tools_list) == 7
    tool_names = {t["name"] for t in tools_list}
    assert "search_notes" in tool_names
    assert "create_note" in tool_names

    # 4. Interactive tool call via console
    call_res = client.post("/api/tools/search_notes/call", json={"arguments": {"query": "retrieval evaluation"}})
    assert call_res.status_code == 200
    call_data = call_res.json()
    assert call_data["status"] == "ok"
    assert "projects/ai.md" in call_data["output"]
    assert "raw_request" in call_data
    assert "raw_response" in call_data

    # 5. Call Log Activity
    calls_res = client.get("/api/calls")
    assert calls_res.status_code == 200
    calls = calls_res.json()
    assert len(calls) > 0
    assert calls[0]["tool"] == "search_notes"

    # 6. Token generation and revocation
    tok_res = client.post("/api/tokens", json={"name": "test-remote-agent", "scope": "read"})
    assert tok_res.status_code == 200
    tok_data = tok_res.json()
    assert "raw_token" in tok_data
    token_id = tok_data["id"]

    tokens_list_res = client.get("/api/tokens")
    assert any(t["id"] == token_id for t in tokens_list_res.json())

    del_res = client.delete(f"/api/tokens/{token_id}")
    assert del_res.status_code == 200

    # 7. Config Snippet
    snippet_res = client.get("/api/config-snippet?host=claude-desktop")
    assert snippet_res.status_code == 200
    assert "mcpServers" in snippet_res.json()

    # 8. Web Console HTML
    html_res = client.get("/")
    assert html_res.status_code == 200
    assert "VaultMCP" in html_res.text
