"""Settings and default configuration helpers for VaultMCP."""

import os
from pathlib import Path


def get_default_vault_path() -> Path:
    """Returns the vault path from VAULT_PATH environment variable or current directory."""
    env_path = os.getenv("VAULT_PATH")
    if env_path:
        return Path(env_path).resolve()
    return Path.cwd().resolve()


def get_host_config_snippet(host: str, vault_path: Path, executable: str = "vaultmcp") -> dict:
    """Generates copy-paste MCP client configurations for standard hosts."""
    clean_host = host.lower().replace("_", "-")
    path_str = str(vault_path.resolve())

    if clean_host in ("claude-desktop", "claude"):
        return {
            "mcpServers": {
                "vaultmcp": {
                    "command": executable,
                    "args": ["--vault", path_str, "--stdio"],
                }
            }
        }
    elif clean_host in ("cursor", "cursor-ide"):
        return {
            "name": "vaultmcp",
            "type": "command",
            "command": f"{executable} --vault \"{path_str}\" --stdio",
        }
    elif clean_host in ("antigravity", "gemini"):
        return {
            "mcpServers": {
                "vaultmcp": {
                    "command": executable,
                    "args": ["--vault", path_str, "--stdio"],
                    "disabled": False,
                    "autoApprove": ["list_notes", "search_notes", "read_note", "list_tags", "get_backlinks"],
                }
            }
        }
    elif clean_host in ("zed", "zed-editor"):
        return {
            "context_servers": {
                "vaultmcp": {
                    "command": executable,
                    "args": ["--vault", path_str, "--stdio"],
                }
            }
        }
    else:
        return {
            "mcpServers": {
                "vaultmcp": {
                    "command": executable,
                    "args": ["--vault", path_str, "--stdio"],
                }
            }
        }
