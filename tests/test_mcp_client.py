"""Tests for tools/mcp_client.py."""

import pytest

from tools.mcp_client import MCPClient, MCPError, MCPServerConfig


@pytest.fixture
def sample_config():
    return {
        "mcp_servers": {
            "tradingview": {
                "transport": "stdio",
                "command": "tradingview-mcp-server",
                "args": ["--stdio"],
                "env": {"TRADINGVIEW_TIMEOUT": "30"},
                "timeout_seconds": 45,
                "enabled": True,
            },
            "unusual_whales": {
                "transport": "sse",
                "url": "https://api.example.com/mcp/sse",
                "headers": {"Authorization": "Bearer test"},
                "enabled": False,
            },
        }
    }


def test_config_parsing(sample_config):
    client = MCPClient(sample_config)

    tv = client._servers["tradingview"]
    assert tv.transport == "stdio"
    assert tv.command == "tradingview-mcp-server"
    assert tv.args == ["--stdio"]
    assert tv.env["TRADINGVIEW_TIMEOUT"] == "30"
    assert tv.timeout_seconds == 45.0
    assert tv.enabled is True

    uw = client._servers["unusual_whales"]
    assert uw.transport == "sse"
    assert uw.url == "https://api.example.com/mcp/sse"
    assert uw.headers["Authorization"] == "Bearer test"
    assert uw.enabled is False


def test_server_names(sample_config):
    client = MCPClient(sample_config)
    # Only enabled servers are returned
    assert client.server_names == ["tradingview"]


@pytest.mark.asyncio
async def test_call_tool_unconfigured_server():
    client = MCPClient({})
    with pytest.raises(MCPError, match="not configured"):
        await client.call_tool("missing", "some_tool")


@pytest.mark.asyncio
async def test_call_tool_disabled_server(sample_config):
    client = MCPClient(sample_config)
    with pytest.raises(MCPError, match="disabled"):
        await client.call_tool("unusual_whales", "some_tool")


def test_mcp_server_config_defaults():
    cfg = MCPServerConfig.from_dict("test", {})
    assert cfg.transport == "stdio"
    assert cfg.command is None
    assert cfg.args == []
    assert cfg.env == {}
    assert cfg.timeout_seconds == 60.0
    assert cfg.enabled is True
