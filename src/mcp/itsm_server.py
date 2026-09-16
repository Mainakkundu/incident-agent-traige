"""MCP server entrypoint for ITSM, CMDB, and semantic retrieval tools."""

from __future__ import annotations

from typing import Any

from src.clients.glpi import GLPIClient
from src.clients.logstore import LogStoreClient
from src.config import Settings, load_settings
from src.embeddings import HuggingFaceEmbeddingProvider
from src.mcp.itsm import ITSMTools
from src.mcp.server_common import (
    MCPServerLike,
    create_mcp_server,
    parse_server_args,
    print_tool_names,
    register_named_tools,
    run_server,
)


ITSM_MCP_NAME = "incident-itsm"
ITSM_TOOL_NAMES = (
    "get_ticket",
    "get_ci",
    "get_ci_dependencies",
    "get_similar_incidents",
    "search_runbooks",
    "update_ticket",
    "close_ticket",
)


def build_itsm_tools(settings: Settings) -> ITSMTools:
    """Return ITSM tools backed by GLPI and logstore retrieval."""
    glpi_client = GLPIClient.from_settings(settings)
    embedding_provider = HuggingFaceEmbeddingProvider(settings.embedding_model)
    logstore_client = LogStoreClient.from_settings(settings, embedding_provider)
    return ITSMTools(
        ticket_reader=glpi_client,
        ticket_writer=glpi_client,
        cmdb_reader=glpi_client,
        incident_searcher=logstore_client,
        runbook_searcher=logstore_client,
    )


def register_itsm_tools(server: MCPServerLike, tools: ITSMTools) -> MCPServerLike:
    """Register ITSM tools on one MCP server."""
    return register_named_tools(server, tools, ITSM_TOOL_NAMES)


def build_itsm_server(tools: ITSMTools) -> Any:
    """Return the ITSM MCP server."""
    server = create_mcp_server(ITSM_MCP_NAME)
    return register_itsm_tools(server, tools)


def build_default_itsm_server() -> Any:
    """Return an ITSM MCP server from local settings."""
    return build_itsm_server(build_itsm_tools(load_settings()))


def main() -> None:
    """Run the ITSM MCP server."""
    args = parse_server_args("Run the incident ITSM MCP server.")
    if args.list_tools:
        print_tool_names(ITSM_TOOL_NAMES)
        return
    server = build_default_itsm_server()
    run_server(server, args.transport, args.host, args.port)


if __name__ == "__main__":
    main()
