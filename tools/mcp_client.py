"""
MCP Client for Alpha Trader

Connects to Model Context Protocol (MCP) servers and exposes their tools
to the Alpha Trader research and execution pipeline.

Supports:
- stdio servers (local subprocesses, e.g. tradingview-mcp-server)
- SSE servers (remote HTTP endpoints)
- Connection pooling and lazy reconnection
- Structured error envelopes compatible with tools/tradingview_mcp.py

Usage:
    from tools.mcp_client import MCPClient

    client = MCPClient(config)
    result = await client.call_tool(
        server="tradingview",
        tool="coin_analysis",
        arguments={"symbol": "AAPL", "timeframe": "1d"}
    )
"""

import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger


try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.sse import sse_client
    _MCP_AVAILABLE = True
except ImportError as _mcp_import_err:  # pragma: no cover
    ClientSession = None  # type: ignore
    StdioServerParameters = None  # type: ignore
    stdio_client = None  # type: ignore
    sse_client = None  # type: ignore
    _MCP_AVAILABLE = False
    logger.warning(f"MCP SDK not installed: {_mcp_import_err}")


class MCPError(Exception):
    """Raised when an MCP operation fails."""

    def __init__(
        self,
        message: str,
        server: Optional[str] = None,
        tool: Optional[str] = None,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.server = server
        self.tool = tool
        self.retryable = retryable


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""

    name: str
    transport: str  # "stdio" or "sse"
    # stdio fields
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None
    # sse fields
    url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    # common
    timeout_seconds: float = 60.0
    enabled: bool = True

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "MCPServerConfig":
        """Build config from a YAML/config dict."""
        return cls(
            name=name,
            transport=data.get("transport", "stdio"),
            command=data.get("command"),
            args=data.get("args", []),
            env=data.get("env", {}),
            cwd=data.get("cwd"),
            url=data.get("url"),
            headers=data.get("headers", {}),
            timeout_seconds=float(data.get("timeout_seconds", 60.0)),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass
class MCPCallResult:
    """Normalized result of an MCP tool call."""

    content: List[Any] = field(default_factory=list)
    is_error: bool = False
    text: Optional[str] = None
    data: Optional[Any] = None

    def __post_init__(self):
        if self.text is None and self.content:
            # Extract text from standard MCP TextContent items
            texts = []
            for item in self.content:
                if isinstance(item, dict) and item.get("type") == "text":
                    texts.append(item.get("text", ""))
                elif hasattr(item, "text"):
                    texts.append(str(item.text))
            self.text = "\n".join(texts) if texts else None

        if self.data is None and self.text:
            try:
                self.data = json.loads(self.text)
            except json.JSONDecodeError:
                self.data = None


class MCPClient:
    """
    Multi-server MCP client with connection caching.

    Connections are established lazily on first tool call and cached for reuse.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._servers: Dict[str, MCPServerConfig] = {}
        self._sessions: Dict[str, ClientSession] = {}
        self._session_locks: Dict[str, asyncio.Lock] = {}
        # Async context managers that must be exited on disconnect.
        # Each entry is a list ordered outer -> inner (stdio/sse cm, session cm).
        self._context_managers: Dict[str, List[Any]] = {}
        self._parse_config()

    def _parse_config(self):
        """Load server definitions from config['mcp_servers']."""
        mcp_config = self.config.get("mcp_servers", {})
        for name, data in mcp_config.items():
            if not isinstance(data, dict):
                logger.warning(f"Ignoring invalid MCP server config for {name}")
                continue
            self._servers[name] = MCPServerConfig.from_dict(name, data)
            self._session_locks[name] = asyncio.Lock()

    @property
    def server_names(self) -> List[str]:
        """List configured server names."""
        return [name for name, cfg in self._servers.items() if cfg.enabled]

    async def list_tools(self, server_name: str) -> List[Dict[str, Any]]:
        """List available tools on a server."""
        await self._ensure_session(server_name)
        session = self._sessions[server_name]
        try:
            result = await session.list_tools()
            return [
                {
                    "name": tool.name,
                    "description": getattr(tool, "description", ""),
                    "input_schema": getattr(tool, "inputSchema", {}),
                }
                for tool in result.tools
            ]
        except Exception as e:
            logger.error(f"Failed to list tools on {server_name}: {e}")
            raise MCPError(
                f"list_tools failed: {e}",
                server=server_name,
                retryable=True,
            )

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> MCPCallResult:
        """
        Call a tool on an MCP server.

        Args:
            server_name: Configured MCP server name.
            tool_name: Name of the tool to invoke.
            arguments: Tool arguments dict.
            timeout_seconds: Optional override for server timeout.

        Returns:
            MCPCallResult with content, text, and parsed data.
        """
        arguments = arguments or {}
        cfg = self._servers.get(server_name)
        if not cfg:
            raise MCPError(
                f"MCP server '{server_name}' not configured",
                server=server_name,
                tool=tool_name,
            )
        if not cfg.enabled:
            raise MCPError(
                f"MCP server '{server_name}' is disabled",
                server=server_name,
                tool=tool_name,
            )

        await self._ensure_session(server_name)
        session = self._sessions[server_name]
        timeout = timeout_seconds or cfg.timeout_seconds

        try:
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments),
                timeout=timeout,
            )
            call_result = MCPCallResult(
                content=[c.model_dump() if hasattr(c, "model_dump") else c for c in result.content],
                is_error=bool(getattr(result, "isError", False)),
            )
            if call_result.is_error:
                logger.warning(
                    f"MCP tool {server_name}/{tool_name} returned error: {call_result.text}"
                )
            else:
                logger.info(f"MCP tool {server_name}/{tool_name} succeeded")
            return call_result
        except asyncio.TimeoutError:
            logger.error(f"MCP tool {server_name}/{tool_name} timed out after {timeout}s")
            # Force reconnect on next call
            await self._disconnect_server(server_name)
            raise MCPError(
                f"Tool call timed out after {timeout}s",
                server=server_name,
                tool=tool_name,
                retryable=True,
            )
        except Exception as e:
            logger.error(f"MCP tool {server_name}/{tool_name} failed: {e}")
            await self._disconnect_server(server_name)
            raise MCPError(
                f"Tool call failed: {e}",
                server=server_name,
                tool=tool_name,
                retryable=True,
            )

    async def _ensure_session(self, server_name: str):
        """Establish a cached session for a server if not already connected."""
        if server_name in self._sessions and self._sessions[server_name] is not None:
            return

        lock = self._session_locks.setdefault(server_name, asyncio.Lock())
        async with lock:
            # Double-check after acquiring lock
            if server_name in self._sessions and self._sessions[server_name] is not None:
                return

            cfg = self._servers.get(server_name)
            if not cfg:
                raise MCPError(f"MCP server '{server_name}' not configured", server=server_name)

            logger.info(f"Connecting to MCP server '{server_name}' via {cfg.transport}")

            if cfg.transport == "stdio":
                await self._connect_stdio(server_name, cfg)
            elif cfg.transport == "sse":
                await self._connect_sse(server_name, cfg)
            else:
                raise MCPError(
                    f"Unsupported MCP transport: {cfg.transport}",
                    server=server_name,
                )

    async def _connect_stdio(self, server_name: str, cfg: MCPServerConfig):
        """Connect to a local stdio MCP server."""
        if not _MCP_AVAILABLE:
            raise MCPError(
                "MCP SDK not installed; cannot connect to stdio server",
                server=server_name,
            )

        command = cfg.command
        if not command:
            raise MCPError("stdio server requires 'command'", server=server_name)

        # If command is not an absolute path, resolve via PATH
        resolved_command = shutil.which(command) or command
        args = cfg.args or []

        # Merge configured env with current process env so PATH and credentials
        # are inherited unless explicitly overridden.
        env = {**os.environ, **cfg.env}

        params = StdioServerParameters(
            command=resolved_command,
            args=args,
            env=env,
        )

        transport_cm = stdio_client(params)
        read_stream, write_stream = await transport_cm.__aenter__()
        try:
            session_cm = ClientSession(read_stream, write_stream)
            session = await session_cm.__aenter__()
            await session.initialize()
            self._sessions[server_name] = session
            self._context_managers[server_name] = [transport_cm, session_cm]
            logger.info(f"MCP stdio server '{server_name}' connected")
        except Exception:
            await session_cm.__aexit__(*self._exc_info())
            await transport_cm.__aexit__(*self._exc_info())
            raise

    async def _connect_sse(self, server_name: str, cfg: MCPServerConfig):
        """Connect to a remote SSE MCP server."""
        if not _MCP_AVAILABLE:
            raise MCPError(
                "MCP SDK not installed; cannot connect to SSE server",
                server=server_name,
            )

        if not cfg.url:
            raise MCPError("SSE server requires 'url'", server=server_name)

        transport_cm = sse_client(cfg.url, headers=cfg.headers)
        read_stream, write_stream = await transport_cm.__aenter__()
        try:
            session_cm = ClientSession(read_stream, write_stream)
            session = await session_cm.__aenter__()
            await session.initialize()
            self._sessions[server_name] = session
            self._context_managers[server_name] = [transport_cm, session_cm]
            logger.info(f"MCP SSE server '{server_name}' connected")
        except Exception:
            await session_cm.__aexit__(*self._exc_info())
            await transport_cm.__aexit__(*self._exc_info())
            raise

    @staticmethod
    def _exc_info():
        """Return exception info for __aexit__ when no exception is active."""
        import sys

        return (None, None, None)

    async def _disconnect_server(self, server_name: str):
        """Close a cached session and its transport."""
        self._sessions.pop(server_name, None)
        managers = self._context_managers.pop(server_name, [])
        # Exit in reverse order (inner session first, then transport).
        for cm in reversed(managers):
            try:
                await cm.__aexit__(None, None, None)
            except Exception as e:
                logger.debug(f"Error exiting MCP context for {server_name}: {e}")

    async def close(self):
        """Close all MCP connections."""
        # Disconnect sequentially; context managers may be task-sensitive (anyio
        # cancel scopes must be exited in the same task that entered them).
        for name in list(self._sessions.keys()):
            try:
                await self._disconnect_server(name)
            except Exception as e:
                logger.debug(f"Error closing MCP connection '{name}': {e}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()


def load_mcp_client_from_config(config_path: Optional[str] = None) -> MCPClient:
    """Convenience factory that loads config from Alpha Trader's config.yaml."""
    import yaml

    if config_path is None:
        config_path = "config/config.yaml"

    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning(f"Config file not found: {config_path}; using empty MCP config")
        config = {}

    return MCPClient(config)
