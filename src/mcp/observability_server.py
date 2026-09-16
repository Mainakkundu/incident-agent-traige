"""MCP server entrypoint for log, metric, and deploy tools."""

from __future__ import annotations

from typing import Any

from src.clients.logstore import LogStoreClient
from src.config import Settings, load_settings
from src.mcp.observability import ObservabilityTools
from src.mcp.server_common import (
    MCPServerLike,
    create_mcp_server,
    parse_server_args,
    print_tool_names,
    register_named_tools,
    run_server,
)


OBSERVABILITY_MCP_NAME = "incident-observability"
OBSERVABILITY_TOOL_NAMES = (
    "search_logs",
    "get_error_rate",
    "get_recent_deploys",
    "get_metric",
)


def build_observability_tools(settings: Settings) -> ObservabilityTools:
    """Return observability tools backed by the logstore."""
    client = LogStoreClient.from_settings(settings)
    return ObservabilityTools(client, client, client, settings)


def register_observability_tools(
    server: MCPServerLike,
    tools: ObservabilityTools,
) -> MCPServerLike:
    """Register observability tools on one MCP server."""
    return register_named_tools(server, tools, OBSERVABILITY_TOOL_NAMES)


def build_observability_server(tools: ObservabilityTools) -> Any:
    """Return the observability MCP server."""
    server = create_mcp_server(OBSERVABILITY_MCP_NAME)
    return register_observability_tools(server, tools)


def build_default_observability_server() -> Any:
    """Return an observability MCP server from local settings."""
    return build_observability_server(build_observability_tools(load_settings()))


def main() -> None:
    """Run the observability MCP server."""
    args = parse_server_args("Run the incident observability MCP server.")
    if args.list_tools:
        print_tool_names(OBSERVABILITY_TOOL_NAMES)
        return
    server = build_default_observability_server()
    run_server(server, args.transport, args.host, args.port)


if __name__ == "__main__":
    main()
