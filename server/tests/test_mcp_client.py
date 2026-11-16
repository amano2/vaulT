"""Contract test verifying MCP tools listing and invocation."""

import asyncio
from pathlib import Path
from server.vaultmcp.index.db import open_db
from server.vaultmcp.index.migrations import run_migrations
from server.vaultmcp.vault.scanner import scan_and_index_vault
from server.vaultmcp.adapter import create_mcp_server


def test_mcp_server_contract(tmp_path: Path):
    async def _run():
        fixture_vault = Path("fixtures/test_vault").resolve()
        db_path = tmp_path / "contract.db"
        conn = open_db(db_path)
        run_migrations(conn)
        scan_and_index_vault(fixture_vault, conn, kind="full")

        server = create_mcp_server(fixture_vault, conn, transport="test")

        # 1. Verify list_tools from tool manager
        tools = server._tool_manager.list_tools()
        tool_names = {t.name for t in tools}
        expected_tools = {
            "list_notes",
            "search_notes",
            "read_note",
            "list_tags",
            "get_backlinks",
            "create_note",
            "append_to_note",
        }
        assert expected_tools.issubset(tool_names)

        # 2. Verify tool schemas and docstrings are non-empty
        for tool in tools:
            assert tool.description and len(tool.description.strip()) > 10
            assert tool.parameters is not None

        # 3. Call search_notes tool handler
        search_tool = server._tool_manager.get_tool("search_notes")
        res = await search_tool.fn(query="retrieval evaluation")
        assert res is not None
        assert "projects/ai.md" in res

        # 4. Call list_tags tool handler
        tags_tool = server._tool_manager.get_tool("list_tags")
        tags_res = await tags_tool.fn()
        assert "#ml" in tags_res

        # 5. Call read_note tool handler
        read_tool = server._tool_manager.get_tool("read_note")
        read_res = await read_tool.fn(path="welcome.md")
        assert "Welcome to the Vault" in read_res

        conn.close()

    asyncio.run(_run())
