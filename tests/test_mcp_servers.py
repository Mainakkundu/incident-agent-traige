from __future__ import annotations

import unittest
from typing import Any, Callable

from src.mcp.itsm_server import ITSM_TOOL_NAMES, register_itsm_tools
from src.mcp.observability_server import (
    OBSERVABILITY_TOOL_NAMES,
    register_observability_tools,
)
from tests.test_mcp_itsm import FakeITSMClient
from tests.test_mcp_observability import FakeObservabilityClient, make_settings
from src.mcp.itsm import ITSMTools
from src.mcp.observability import ObservabilityTools


class MCPServerRegistrationTests(unittest.TestCase):
    def test_observability_server_registers_four_tools(self) -> None:
        client = FakeObservabilityClient()
        tools = ObservabilityTools(client, client, client, make_settings())
        server = FakeMCPServer()

        register_observability_tools(server, tools)

        self.assertEqual(server.tool_names(), OBSERVABILITY_TOOL_NAMES)

    def test_itsm_server_registers_seven_tools(self) -> None:
        client = FakeITSMClient()
        tools = ITSMTools(client, client, client, client, client)
        server = FakeMCPServer()

        register_itsm_tools(server, tools)

        self.assertEqual(server.tool_names(), ITSM_TOOL_NAMES)

    def test_registered_write_tool_still_requires_approval_token(self) -> None:
        client = FakeITSMClient()
        tools = ITSMTools(client, client, client, client, client)
        server = FakeMCPServer()
        register_itsm_tools(server, tools)

        with self.assertRaises(PermissionError):
            server.tools["update_ticket"](
                ticket_id="77",
                diagnosis="postgres-main max connections",
                evidence=("log line",),
                confidence=0.9,
                approval_token="",
            )


class FakeMCPServer:
    def __init__(self) -> None:
        self.tools: dict[str, Callable[..., Any]] = {}
        self.descriptions: dict[str, str | None] = {}

    def add_tool(
        self,
        fn: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        tool_name = name or fn.__name__
        self.tools[tool_name] = fn
        self.descriptions[tool_name] = description

    def tool_names(self) -> tuple[str, ...]:
        return tuple(self.tools)


if __name__ == "__main__":
    unittest.main()
