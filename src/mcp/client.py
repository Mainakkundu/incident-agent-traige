"""MCP client helpers for hosted incident tools."""

from __future__ import annotations

from typing import Any, Mapping


def create_mcp_client(target: Any) -> Any:
    """Return an MCP client for a server object or URL."""
    try:
        from mcp import Client
    except ImportError as exc:
        msg = "Install the MCP SDK with: pip install 'mcp[cli]'"
        raise RuntimeError(msg) from exc
    return Client(target)


async def list_mcp_tool_names(target: Any) -> tuple[str, ...]:
    """Return tool names exposed by one MCP target."""
    async with create_mcp_client(target) as client:
        result = await client.list_tools()
        return tuple(tool.name for tool in result.tools)


async def call_mcp_tool(
    target: Any,
    name: str,
    arguments: Mapping[str, Any],
) -> Any:
    """Call one MCP tool."""
    async with create_mcp_client(target) as client:
        return await client.call_tool(name, dict(arguments))
