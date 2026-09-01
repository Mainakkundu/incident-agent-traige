from __future__ import annotations

import unittest

from src.mcp.itsm import ITSMTools
from src.mcp.observability import ObservabilityTools


OBSERVABILITY_TOOLS = (
    "search_logs",
    "get_error_rate",
    "get_recent_deploys",
    "get_metric",
)

ITSM_TOOLS = (
    "get_ticket",
    "get_ci",
    "get_ci_dependencies",
    "get_similar_incidents",
    "search_runbooks",
    "update_ticket",
    "close_ticket",
)


class Phase2ToolContractTests(unittest.TestCase):
    def test_observability_exposes_four_standalone_tools(self) -> None:
        tools = public_tool_names(ObservabilityTools)

        self.assertEqual(tools, OBSERVABILITY_TOOLS)

    def test_itsm_exposes_seven_standalone_tools(self) -> None:
        tools = public_tool_names(ITSMTools)

        self.assertEqual(tools, ITSM_TOOLS)

    def test_phase2_exposes_eleven_total_tools(self) -> None:
        tool_count = len(OBSERVABILITY_TOOLS) + len(ITSM_TOOLS)

        self.assertEqual(tool_count, 11)


def public_tool_names(tool_class: type[object]) -> tuple[str, ...]:
    """Return public callable names in declaration order."""
    return tuple(
        name
        for name, value in tool_class.__dict__.items()
        if not name.startswith("_") and callable(value)
    )


if __name__ == "__main__":
    unittest.main()
