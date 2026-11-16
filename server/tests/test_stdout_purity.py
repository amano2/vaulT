"""Test stdout purity: spawns the stdio server and asserts zero non-protocol frames on stdout."""

import subprocess
import sys
import os
import json
from pathlib import Path


def test_stdout_purity():
    vault_path = str(Path("fixtures/test_vault").resolve())
    cmd = [
        sys.executable,
        "-u",
        "-m",
        "server.vaultmcp.main",
        "--stdio",
        "--vault",
        vault_path,
    ]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=0,
        env=env,
    )

    try:
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pytest-client", "version": "1.0"},
            },
        }

        # Send initialize request
        proc.stdin.write(json.dumps(init_req) + "\n")
        proc.stdin.flush()

        # Read line from stdout
        response_line = proc.stdout.readline()
        if not response_line:
            err_output = proc.stderr.read()
            assert False, f"Expected JSON-RPC response on stdout, got EOF. Stderr was:\n{err_output}"

        # Assert stdout line is strictly valid JSON
        parsed = json.loads(response_line)
        assert parsed.get("jsonrpc") == "2.0"
        assert parsed.get("id") == 1
        assert "result" in parsed
        assert "serverInfo" in parsed["result"]

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
