from __future__ import annotations

import unittest

from src.graph import (
    END_NODE,
    GATE_NODE,
    TOOL_NODE,
    WRITE_NODE,
    should_continue,
    should_write,
    supervisor_node,
    write_node,
)
from src.state import initial_triage_state
from tests.test_mcp_observability import make_settings


class GraphTests(unittest.TestCase):
    def test_should_continue_routes_to_tools_when_last_message_has_tool_calls(self) -> None:
        state = initial_triage_state(messages=(FakeMessage(tool_calls=[{"name": "search_logs"}]),))

        route = should_continue(state, make_settings())

        self.assertEqual(route, TOOL_NODE)

    def test_should_continue_routes_to_gate_when_last_message_has_no_tool_calls(self) -> None:
        state = initial_triage_state(messages=(FakeMessage(),))

        route = should_continue(state, make_settings())

        self.assertEqual(route, GATE_NODE)

    def test_should_continue_routes_to_gate_when_step_cap_is_hit(self) -> None:
        state = initial_triage_state(messages=(FakeMessage(tool_calls=[{"name": "search_logs"}]),))
        state["llm_calls"] = make_settings().agent_max_steps

        route = should_continue(state, make_settings())

        self.assertEqual(route, GATE_NODE)

    def test_supervisor_node_appends_model_message_and_increments_call_count(self) -> None:
        model = FakeModel(FakeMessage(content="next"))
        state = initial_triage_state(messages=(FakeMessage(content="start"),))
        state["llm_calls"] = 2

        update = supervisor_node(state, model)

        self.assertEqual(update["messages"], [FakeMessage(content="next")])
        self.assertEqual(update["llm_calls"], 3)
        self.assertEqual(model.messages, state["messages"])

    def test_should_write_routes_auto_write_decision_to_write_node(self) -> None:
        state = initial_triage_state()
        state["gate_decision"] = {"status": "auto_write"}

        self.assertEqual(should_write(state), WRITE_NODE)

    def test_should_write_routes_escalation_to_end(self) -> None:
        state = initial_triage_state()
        state["gate_decision"] = {"status": "escalate"}

        self.assertEqual(should_write(state), END_NODE)

    def test_write_node_waits_for_human_approval_without_state_changes(self) -> None:
        self.assertEqual(write_node(initial_triage_state()), {})

class FakeMessage:
    def __init__(
        self,
        content: str = "",
        tool_calls: list[dict[str, str]] | None = None,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls or []

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FakeMessage):
            return False
        return self.content == other.content and self.tool_calls == other.tool_calls


class FakeModel:
    def __init__(self, response: FakeMessage) -> None:
        self.response = response
        self.messages: object | None = None

    def invoke(self, messages: object) -> FakeMessage:
        self.messages = messages
        return self.response


if __name__ == "__main__":
    unittest.main()
