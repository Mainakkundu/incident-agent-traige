from __future__ import annotations

import operator
import unittest
from typing import get_args, get_origin, get_type_hints

from src.state import (
    TriageState,
    increment_llm_calls,
    initial_triage_state,
    record_service_seen,
    set_approval_token,
)


class TriageStateTests(unittest.TestCase):
    def test_initial_triage_state_sets_required_fields(self) -> None:
        message = object()

        state = initial_triage_state(messages=(message,), approval_token="token-1")

        self.assertEqual(state["messages"], [message])
        self.assertEqual(state["llm_calls"], 0)
        self.assertEqual(state["services_seen"], [])
        self.assertEqual(state["approval_token"], "token-1")
        self.assertIsNone(state["gate_decision"])

    def test_services_seen_has_add_reducer_for_e3(self) -> None:
        hints = get_type_hints(TriageState, include_extras=True)
        services_seen = hints["services_seen"]

        self.assertIs(get_origin(services_seen), get_origin(hints["messages"]))
        self.assertIs(get_args(services_seen)[1], operator.add)

    def test_record_service_seen_returns_append_update(self) -> None:
        update = record_service_seen(" payment-api ")

        self.assertEqual(update, {"services_seen": ["payment-api"]})

    def test_record_service_seen_rejects_empty_service(self) -> None:
        with self.assertRaises(ValueError):
            record_service_seen(" ")

    def test_increment_llm_calls_replaces_count_with_next_value(self) -> None:
        state = initial_triage_state()
        state["llm_calls"] = 4

        update = increment_llm_calls(state)

        self.assertEqual(update, {"llm_calls": 5})

    def test_set_approval_token_can_set_and_clear_token(self) -> None:
        self.assertEqual(set_approval_token("approved"), {"approval_token": "approved"})
        self.assertEqual(set_approval_token(None), {"approval_token": None})


if __name__ == "__main__":
    unittest.main()
