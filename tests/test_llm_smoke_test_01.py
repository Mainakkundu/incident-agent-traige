from __future__ import annotations

import json
import unittest

from scripts.llm_smoke_test_01 import (
    FirstToolCall,
    extract_first_tool_call,
    first_tool_attributes,
    require_read_tool,
    tool_schemas,
)


class LLMSmokeTest01Tests(unittest.TestCase):
    def test_tool_schemas_expose_read_tools_only(self) -> None:
        names = [schema["function"]["name"] for schema in tool_schemas()]

        self.assertIn("search_logs", names)
        self.assertIn("get_ci_dependencies", names)
        self.assertNotIn("update_ticket", names)
        self.assertNotIn("close_ticket", names)

    def test_extract_first_tool_call_parses_groq_response_shape(self) -> None:
        completion = FakeCompletion("search_logs", {"service": "payment-api"})

        tool_call = extract_first_tool_call(completion)

        self.assertEqual(tool_call.name, "search_logs")
        self.assertEqual(tool_call.arguments, {"service": "payment-api"})

    def test_require_read_tool_rejects_write_tool(self) -> None:
        with self.assertRaises(AssertionError):
            require_read_tool(FirstToolCall("update_ticket", {}))

    def test_first_tool_attributes_include_selected_tool_and_usage(self) -> None:
        completion = FakeCompletion("search_logs", {"service": "payment-api"})
        completion.usage = FakeUsage()

        attrs = first_tool_attributes(
            FirstToolCall("search_logs", {"service": "payment-api"}),
            completion,
        )

        self.assertEqual(attrs["tool.name"], "search_logs")
        self.assertEqual(attrs["tool.args"], '{"service": "payment-api"}')
        self.assertEqual(attrs["llm.token_count.prompt"], 10)
        self.assertEqual(attrs["llm.token_count.completion"], 3)
        self.assertEqual(attrs["llm.token_count.total"], 13)


class FakeCompletion:
    def __init__(self, name: str, arguments: dict[str, object]) -> None:
        self.choices = [
            FakeChoice(
                FakeMessage(
                    [
                        FakeToolCall(
                            FakeFunction(
                                name,
                                json.dumps(arguments),
                            )
                        )
                    ]
                )
            )
        ]


class FakeChoice:
    def __init__(self, message: object) -> None:
        self.message = message


class FakeMessage:
    def __init__(self, tool_calls: list[object]) -> None:
        self.tool_calls = tool_calls
        self.content = None


class FakeToolCall:
    def __init__(self, function: object) -> None:
        self.function = function


class FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class FakeUsage:
    prompt_tokens = 10
    completion_tokens = 3
    total_tokens = 13


if __name__ == "__main__":
    unittest.main()
