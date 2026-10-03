from __future__ import annotations

import unittest
from typing import Any, Mapping, Sequence

from src.audit import PhoenixRunAuditReader, reconstruct_run_audit


RUN_ID = "run-123"


class AuditTests(unittest.TestCase):
    def test_reconstruct_run_audit_returns_full_decision_trail(self) -> None:
        audit = reconstruct_run_audit(RUN_ID, persisted_spans())

        self.assertEqual(audit.run_id, RUN_ID)
        self.assertEqual(audit.trace_id, "trace-1")
        self.assertEqual(audit.ticket_id, "INC-GLD-001")
        self.assertEqual(audit.status, "awaiting_approval")
        self.assertEqual(audit.services_investigated, ("payment-api", "auth-service"))
        self.assertEqual(audit.steps[0].tool_name, "search_logs")
        self.assertEqual(audit.steps[0].arguments["service"], "payment-api")
        self.assertEqual(audit.steps[0].result_count, 2)
        self.assertEqual(audit.steps[1].hypothesis, "inspect auth-service")
        self.assertEqual(audit.diagnosis["root_cause"], "postgres-main")
        self.assertEqual(audit.confidence, 0.87)
        self.assertEqual(audit.gate_status, "auto_write")
        self.assertTrue(audit.approval_token_present)

    def test_reader_filters_persisted_spans_by_run_id(self) -> None:
        source = FakeSpanSource(
            persisted_spans()
            + [
                {
                    "name": "other",
                    "attributes": {"incident.run_id": "other-run"},
                    "start_time": "2026-09-18T10:00:03Z",
                }
            ]
        )
        reader = PhoenixRunAuditReader(source, "test-project")

        audit = reader.get_run(RUN_ID)

        self.assertIsNotNone(audit)
        self.assertEqual(source.calls, [("test-project", RUN_ID, 1000)])
        self.assertEqual(len(audit.steps), 2)

    def test_reader_returns_none_for_unknown_run(self) -> None:
        reader = PhoenixRunAuditReader(FakeSpanSource(persisted_spans()), "test-project")

        self.assertIsNone(reader.get_run("missing"))

    def test_reconstruction_requires_at_least_one_span(self) -> None:
        with self.assertRaises(ValueError):
            reconstruct_run_audit(RUN_ID, [])


class FakeSpanSource:
    def __init__(self, spans: Sequence[Mapping[str, Any]]) -> None:
        self.spans = spans
        self.calls: list[tuple[str, str, int]] = []

    def get_run_spans(
        self,
        project_name: str,
        run_id: str,
        limit: int,
    ) -> Sequence[Mapping[str, Any]]:
        self.calls.append((project_name, run_id, limit))
        matching_trace_ids = {
            span["context"]["trace_id"]
            for span in self.spans
            if span.get("attributes", {}).get("incident.run_id") == run_id
        }
        return [
            span
            for span in self.spans
            if span.get("context", {}).get("trace_id") in matching_trace_ids
        ]


def persisted_spans() -> list[dict[str, Any]]:
    return [
        {
            "name": "incident.gld_001.run",
            "context": {"trace_id": "trace-1", "span_id": "span-root"},
            "parent_id": None,
            "start_time": "2026-09-18T10:00:00Z",
            "end_time": "2026-09-18T10:00:03Z",
            "status": {"status_code": "OK"},
            "attributes": {
                "incident.run_id": RUN_ID,
                "incident.golden_id": "gld_001",
                "incident.ticket_id": "INC-GLD-001",
                "incident.alerted_service": "payment-api",
                "incident.root_cause": "postgres-main",
                "incident.causal_chain": "postgres-main -> auth-service -> payment-api",
                "incident.confidence": 0.87,
                "gate.status": "auto_write",
                "gate.approval_token_present": True,
            },
        },
        {
            "name": "tool.search_logs",
            "context": {"trace_id": "trace-1", "span_id": "span-1"},
            "parent_id": "span-root",
            "start_time": "2026-09-18T10:00:01Z",
            "end_time": "2026-09-18T10:00:01.5Z",
            "status_code": "OK",
            "attributes": {
                "tool.step": 1,
                "tool.name": "search_logs",
                "tool.args": '{"service": "payment-api"}',
                "tool.result.preview": '{"logs": ["a", "b"]}',
                "tool.result_count": 2,
                "retrieval_style": "fulltext",
                "hypothesis_at_this_step": "inspect payment-api",
            },
        },
        {
            "name": "tool.get_ci_dependencies",
            "context": {"trace_id": "trace-1", "span_id": "span-2"},
            "parent_id": "span-root",
            "start_time": "2026-09-18T10:00:02Z",
            "end_time": "2026-09-18T10:00:02.5Z",
            "status_code": "OK",
            "attributes": {
                "tool.step": 2,
                "tool.name": "get_ci_dependencies",
                "tool.args": '{"name_or_id": "auth-service"}',
                "tool.result.preview": '{"dependencies": []}',
                "tool.result_count": 0,
                "retrieval_style": "graph",
                "hypothesis_at_this_step": "inspect auth-service",
            },
        },
    ]


if __name__ == "__main__":
    unittest.main()
