from __future__ import annotations

import unittest

from src.prompts import PromptContext, build_supervisor_prompt


TOOL_NAMES = (
    "get_ticket",
    "search_logs",
    "get_recent_deploys",
    "get_ci_dependencies",
    "get_similar_incidents",
    "search_runbooks",
    "update_ticket",
)
FORBIDDEN_ROOT_HINTS = (
    "postgres-main",
    "auth-service",
    "redis-cache",
    "kafka-broker",
    "s3-receipts",
    "max_connections",
    "OutOfMemoryError",
)


class SupervisorPromptTests(unittest.TestCase):
    def test_supervisor_prompt_includes_runtime_alert_context(self) -> None:
        context = PromptContext(
            ticket_id="INC-4471",
            alerted_service="payment-api",
            condition="error_rate",
            observed_value="12%",
            baseline_value="0.3%",
        )

        prompt = build_supervisor_prompt(context, TOOL_NAMES)

        self.assertIn("Ticket ID: INC-4471", prompt)
        self.assertIn("Alerted service: payment-api", prompt)
        self.assertIn("Condition: error_rate", prompt)
        self.assertIn("Observed value: 12%", prompt)
        self.assertIn("Baseline value: 0.3%", prompt)

    def test_supervisor_prompt_names_method_not_answers(self) -> None:
        context = PromptContext(
            ticket_id="INC-1000",
            alerted_service="checkout-web",
            condition="latency",
            observed_value="p95 3s",
        )

        prompt = build_supervisor_prompt(context, TOOL_NAMES)

        self.assertIn("Start from the alerted service", prompt)
        self.assertIn("follow CMDB dependency edges only when", prompt)
        self.assertIn("Do not assume a root cause", prompt)
        self.assertNotIn("Baseline value:", prompt)
        for forbidden in FORBIDDEN_ROOT_HINTS:
            self.assertNotIn(forbidden, prompt)

    def test_supervisor_prompt_lists_tools_without_describing_impl_clients(self) -> None:
        context = PromptContext(
            ticket_id="INC-1001",
            alerted_service="payment-api",
            condition="error_rate",
            observed_value="12%",
        )

        prompt = build_supervisor_prompt(context, TOOL_NAMES)

        self.assertIn("- search_logs", prompt)
        self.assertIn("- update_ticket", prompt)
        self.assertNotIn("GLPIClient", prompt)
        self.assertNotIn("LogStoreClient", prompt)

    def test_supervisor_prompt_requires_context_fields(self) -> None:
        context = PromptContext(
            ticket_id="",
            alerted_service="payment-api",
            condition="error_rate",
            observed_value="12%",
        )

        with self.assertRaises(ValueError):
            build_supervisor_prompt(context, TOOL_NAMES)

    def test_supervisor_prompt_requires_tools(self) -> None:
        context = PromptContext(
            ticket_id="INC-1002",
            alerted_service="payment-api",
            condition="error_rate",
            observed_value="12%",
        )

        with self.assertRaises(ValueError):
            build_supervisor_prompt(context, ())


if __name__ == "__main__":
    unittest.main()
