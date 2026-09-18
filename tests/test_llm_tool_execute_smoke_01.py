from __future__ import annotations

import json
import unittest

from scripts.llm_smoke_test_01 import FirstToolCall
from scripts.llm_tool_execute_smoke_01 import (
    dependency_target_names,
    execute_tool_call,
    full_loop_prompt,
    result_preview,
    tool_result_attributes,
    update_investigation_state,
)


class LLMToolExecuteSmoke01Tests(unittest.TestCase):
    def test_full_loop_prompt_includes_incident_window_context(self) -> None:
        prompt = full_loop_prompt()

        self.assertIn("Incident time window:", prompt)
        self.assertIn("2026-07-31T20:20:00+00:00", prompt)
        self.assertIn("2026-07-31T20:26:00+00:00", prompt)

    def test_execute_tool_call_dispatches_llm_selected_search_logs_args(self) -> None:
        observability = FakeObservabilityTools()
        itsm = FakeITSMTools()
        tool_call = FirstToolCall(
            "search_logs",
            {
                "service": "payment-api",
                "window_start": "2026-07-31T20:20:00+00:00",
                "window_end": "2026-07-31T20:26:00+00:00",
                "level": "ERROR",
                "limit": 10,
            },
        )

        result = execute_tool_call(tool_call, observability, itsm)

        self.assertEqual(observability.search_logs_call, tool_call.arguments)
        self.assertEqual(result["logs"][0]["message"], "auth-service timeout")

    def test_execute_tool_call_dispatches_llm_selected_dependency_args(self) -> None:
        observability = FakeObservabilityTools()
        itsm = FakeITSMTools()

        result = execute_tool_call(
            FirstToolCall("get_ci_dependencies", {"name_or_id": "payment-api"}),
            observability,
            itsm,
        )

        self.assertEqual(itsm.get_ci_dependencies_call, {"name_or_id": "payment-api"})
        self.assertEqual(result["dependencies"][0]["target"], "auth-service")

    def test_tool_result_attributes_include_count_and_preview(self) -> None:
        result = {"logs": [{"message": "auth-service timeout"}]}

        attrs = tool_result_attributes(result, result_count=1)

        self.assertEqual(attrs["tool.result_count"], 1)
        self.assertEqual(json.loads(attrs["tool.result.preview"]), result)

    def test_result_preview_truncates_large_payloads(self) -> None:
        preview = result_preview({"logs": [{"message": "x" * 2000}]})

        self.assertLess(len(preview), 1300)
        self.assertTrue(preview.endswith("...[truncated]"))

    def test_dependency_targets_are_tracked_until_log_inspection(self) -> None:
        dependency_targets: set[str] = set()
        inspected_log_services: set[str] = set()
        dependency_result = {
            "dependencies": [
                {"target": {"name": "auth-service"}},
                {"target": {"name": "postgres-main"}},
            ]
        }

        update_investigation_state(
            FirstToolCall("get_ci_dependencies", {"name_or_id": "payment-api"}),
            dependency_result,
            dependency_targets,
            inspected_log_services,
        )
        update_investigation_state(
            FirstToolCall("search_logs", {"service": "auth-service"}),
            {"logs": []},
            dependency_targets,
            inspected_log_services,
        )

        self.assertEqual(dependency_target_names(dependency_result), {"auth-service", "postgres-main"})
        self.assertEqual(dependency_targets - inspected_log_services, {"postgres-main"})


class FakeObservabilityTools:
    def __init__(self) -> None:
        self.search_logs_call: dict[str, object] = {}

    def search_logs(self, **kwargs: object) -> dict[str, object]:
        self.search_logs_call = kwargs
        return {"logs": [{"message": "auth-service timeout"}]}

    def get_recent_deploys(self, **kwargs: object) -> dict[str, object]:
        return {"deploys": []}


class FakeITSMTools:
    def __init__(self) -> None:
        self.get_ci_dependencies_call: dict[str, object] = {}

    def get_ticket(self, **kwargs: object) -> dict[str, object]:
        return {"ticket": {"ticket_id": kwargs["ticket_id"]}}

    def get_ci_dependencies(self, **kwargs: object) -> dict[str, object]:
        self.get_ci_dependencies_call = kwargs
        return {"dependencies": [{"source": "payment-api", "target": "auth-service"}]}

    def get_similar_incidents(self, **kwargs: object) -> dict[str, object]:
        return {"incidents": []}

    def search_runbooks(self, **kwargs: object) -> dict[str, object]:
        return {"runbooks": []}


if __name__ == "__main__":
    unittest.main()
