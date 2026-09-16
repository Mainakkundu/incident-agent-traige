"""Shared MCP server registration helpers."""

from __future__ import annotations

import argparse
from typing import Any, Callable, Protocol, Sequence


MCP_TRANSPORTS = ("stdio", "sse", "streamable-http")


class MCPServerLike(Protocol):
    """Minimal MCP server interface used by registration tests."""

    def add_tool(
        self,
        fn: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
    ) -> Any:
        """Register one callable tool."""
        ...


def create_mcp_server(name: str) -> Any:
    """Return a new MCP server."""
    try:
        from mcp.server import MCPServer
    except ImportError as exc:
        msg = "Install the MCP SDK with: pip install 'mcp[cli]'"
        raise RuntimeError(msg) from exc
    return MCPServer(name)


def register_named_tools(
    server: MCPServerLike,
    provider: object,
    tool_names: Sequence[str],
) -> MCPServerLike:
    """Register provider methods on one MCP server."""
    for tool_name in tool_names:
        method = getattr(provider, tool_name)
        description = getattr(method, "__doc__", None)
        server.add_tool(method, name=tool_name, description=description)
    return server


def parse_server_args(description: str) -> argparse.Namespace:
    """Parse common MCP server CLI arguments."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--transport",
        choices=MCP_TRANSPORTS,
        default="stdio",
        help="MCP transport to serve.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for HTTP transports.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP transports.",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="Print registered tool names and exit.",
    )
    return parser.parse_args()


def print_tool_names(tool_names: Sequence[str]) -> None:
    """Print registered tool names for manual checks."""
    for tool_name in tool_names:
        print(tool_name)


def run_server(server: Any, transport: str, host: str, port: int) -> None:
    """Run one MCP server until stopped."""
    try:
        if transport == "stdio":
            server.run(transport=transport)
            return
        server.run(transport=transport, host=host, port=port)
    except KeyboardInterrupt:
        return
