from __future__ import annotations

import unittest

from src.gld_001 import (
    expected_retrieval_style,
    gld001_result_attributes,
    gld001_run_attributes,
    hypothesis_at_this_step,
    tool_result_attributes,
    tool_span_attributes,
)
from src.gld_001 import Gld001Result
from src.tracing import set_span_attributes


class TraceAttributeTests(unittest.TestCase):
    def test_tool_span_attributes_include_required_investigation_context(self) -> None:
        attrs = tool_span_attributes(
            "search_logs",
            {
                "service": "postgres-main",
                "window_start": "2026-07-31T20:20:00+00:00",
                "window_end": "2026-07-31T20:26:00+00:00",
            },
        )

        self.assertEqual(attrs["tool.name"], "search_logs")
        self.assertEqual(attrs["retrieval_style"], "fulltext")
        self.assertIn("postgres-main", attrs["hypothesis_at_this_step"])

    def test_retrieval_style_maps_known_tools(self) -> None:
        self.assertEqual(expected_retrieval_style("search_logs"), "fulltext")
        self.assertEqual(expected_retrieval_style("get_ci_dependencies"), "graph")
        self.assertEqual(expected_retrieval_style("missing"), "unknown")

    def test_hypothesis_describes_current_step(self) -> None:
        hypothesis = hypothesis_at_this_step(
            "get_ci_dependencies",
            {"name_or_id": "auth-service"},
        )

        self.assertIn("postgres-main", hypothesis)

    def test_tool_result_attributes_count_result_rows(self) -> None:
        attrs = tool_result_attributes(
            {
                "retrieval_style": "graph",
                "dependencies": [{"target": {"name": "auth-service"}}],
            }
        )

        self.assertEqual(attrs["retrieval_style"], "graph")
        self.assertEqual(attrs["tool.result_count"], 1)

    def test_run_and_result_attributes_name_the_incident(self) -> None:
        run_attrs = gld001_run_attributes()
        result_attrs = gld001_result_attributes(
            Gld001Result(
                root_cause="postgres-main",
                causal_chain=("postgres-main", "auth-service", "payment-api"),
                evidence=("too many clients",),
                confidence=0.87,
                gate_status="auto_write",
                approval_token_present=True,
            )
        )

        self.assertEqual(run_attrs["incident.golden_id"], "gld_001")
        self.assertEqual(result_attrs["incident.root_cause"], "postgres-main")
        self.assertEqual(
            result_attrs["incident.causal_chain"],
            "postgres-main -> auth-service -> payment-api",
        )

    def test_set_span_attributes_skips_none_values(self) -> None:
        span = FakeSpan()

        set_span_attributes(span, {"a": "x", "b": None})

        self.assertEqual(span.attributes, {"a": "x"})


class FakeSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}

    def set_attribute(self, name: str, value: object) -> None:
        self.attributes[name] = value


if __name__ == "__main__":
    unittest.main()
