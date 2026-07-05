from __future__ import annotations

import json

from fagun import install


def test_json_writer_adds_fagun_and_chrome_devtools(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"keep": {"command": "old"}}}))

    install._write_json_server(path, "mcpServers")

    data = json.loads(path.read_text())
    assert data["mcpServers"]["keep"]["command"] == "old"
    assert data["mcpServers"]["fagun"] == {"command": "uvx", "args": ["fagun"]}
    assert data["mcpServers"]["chrome-devtools"] == {
        "command": "npx",
        "args": ["-y", "chrome-devtools-mcp@latest", "--no-usage-statistics"],
        "env": {
            "CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS": "1",
            "CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS": "1",
        },
    }


def test_vscode_json_writer_adds_stdio_type(tmp_path):
    path = tmp_path / "mcp.json"

    install._write_json_server(path, "servers")

    data = json.loads(path.read_text())
    assert data["servers"]["fagun"]["type"] == "stdio"
    assert data["servers"]["chrome-devtools"] == {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "chrome-devtools-mcp@latest", "--no-usage-statistics"],
        "env": {
            "CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS": "1",
            "CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS": "1",
        },
    }


def test_codex_writer_adds_both_servers_and_is_idempotent(tmp_path):
    path = tmp_path / "config.toml"

    install._write_codex(path)
    install._write_codex(path)

    text = path.read_text()
    assert text.count("[mcp_servers.fagun]") == 1
    assert text.count("[mcp_servers.chrome-devtools]") == 1
    assert 'command = "uvx"' in text
    assert 'args = ["-y", "chrome-devtools-mcp@latest", "--no-usage-statistics"]' in text
    assert 'CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS = "1"' in text
    assert "startup_timeout_ms = 20_000" in text


def test_codex_writer_uses_windows_cmd_shape(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    monkeypatch.setattr(install.sys, "platform", "win32")

    install._write_codex(path)

    text = path.read_text()
    assert 'command = "cmd"' in text
    assert 'args = ["/c", "npx", "-y", "chrome-devtools-mcp@latest", "--no-usage-statistics"]' in text
    assert 'SystemRoot = "C:\\\\Windows"' in text
