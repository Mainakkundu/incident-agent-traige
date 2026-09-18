"""Ask Groq for the first gld_001 investigation tool call."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from groq import Groq

from scripts.groq_phoenix_smoke import groq_sdk_base_url, require_groq_api_key
from src.config import Settings, load_settings
from src.gld_001 import gld001_prompt
from src.tracing import configure_tracing, get_tracer, set_span_attributes, shutdown_tracing


READ_TOOL_NAMES = (
    "get_ticket",
    "search_logs",
    "get_recent_deploys",
    "get_ci_dependencies",
    "get_similar_incidents",
    "search_runbooks",
)
TEMPERATURE = 0.0
MAX_COMPLETION_TOKENS = 300
TRACER_NAME = "incident-triage-agent.llm_smoke_test_01"
SPAN_NAME = "incident.llm_smoke_test_01.first_tool"


@dataclass(frozen=True, slots=True)
class FirstToolCall:
    """First tool call selected by the LLM."""

    name: str
    arguments: dict[str, Any]


def run_smoke(settings: Settings) -> FirstToolCall:
    """Return the first LLM-selected gld_001 tool call."""
    require_groq_api_key(settings)
    tracing_handle = configure_tracing(settings)
    try:
        return create_traced_first_tool_call(settings)
    finally:
        shutdown_tracing(tracing_handle)


def create_traced_first_tool_call(settings: Settings) -> FirstToolCall:
    """Ask Groq for the first tool call and trace the decision."""
    tracer = get_tracer(TRACER_NAME)
    with tracer.start_as_current_span(SPAN_NAME) as span:
        set_span_attributes(
            span,
            {
                "llm.system": "groq",
                "llm.model_name": settings.groq_model,
                "input.value": gld001_prompt(),
            },
        )
        completion = create_first_tool_completion(settings)
        tool_call = extract_first_tool_call(completion)
        require_read_tool(tool_call)
        set_span_attributes(span, first_tool_attributes(tool_call, completion))
        return tool_call


def create_first_tool_completion(settings: Settings) -> Any:
    """Create one Groq completion with tool choice enabled."""
    client = Groq(
        api_key=settings.groq_api_key,
        base_url=groq_sdk_base_url(settings.groq_base_url),
        timeout=settings.http_timeout_seconds,
    )
    return client.chat.completions.create(
        messages=message_payload(),
        model=settings.groq_model,
        tools=tool_schemas(),
        tool_choice="auto",
        temperature=TEMPERATURE,
        max_completion_tokens=MAX_COMPLETION_TOKENS,
    )


def message_payload() -> list[dict[str, str]]:
    """Return the gld_001 prompt as a chat payload."""
    return [{"role": "user", "content": gld001_prompt()}]


def tool_schemas() -> list[dict[str, Any]]:
    """Return tool schemas exposed to the LLM smoke."""
    return [
        function_tool(
            "get_ticket",
            "Return one incident ticket from ITSM.",
            {"ticket_id": {"type": "string"}},
            ["ticket_id"],
        ),
        function_tool(
            "search_logs",
            "Return exact, time-bounded logs for one service.",
            {
                "service": {"type": "string"},
                "window_start": {"type": "string"},
                "window_end": {"type": "string"},
                "level": {"type": "string", "enum": ["DEBUG", "INFO", "WARN", "ERROR"]},
                "keyword": {"type": "string"},
                "limit": {"type": "integer"},
            },
            ["service", "window_start", "window_end"],
        ),
        function_tool(
            "get_recent_deploys",
            "Return deploys for one service before a reference time.",
            {
                "service": {"type": "string"},
                "reference_time": {"type": "string"},
                "hours": {"type": "integer"},
            },
            ["service", "reference_time"],
        ),
        function_tool(
            "get_ci_dependencies",
            "Return direct dependency edges for one configuration item.",
            {"name_or_id": {"type": "string"}},
            ["name_or_id"],
        ),
        function_tool(
            "get_similar_incidents",
            "Return semantically similar past incidents.",
            {"signature": {"type": "string"}, "limit": {"type": "integer"}},
            ["signature"],
        ),
        function_tool(
            "search_runbooks",
            "Return semantically relevant runbooks.",
            {"query": {"type": "string"}, "limit": {"type": "integer"}},
            ["query"],
        ),
    ]


def function_tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    """Return one Groq/OpenAI-compatible function tool schema."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def extract_first_tool_call(completion: Any) -> FirstToolCall:
    """Return the first tool call from one Groq completion."""
    message = completion.choices[0].message
    tool_calls = getattr(message, "tool_calls", None) or []
    if not tool_calls:
        msg = f"LLM did not select a tool. Content: {message.content!r}"
        raise ValueError(msg)
    function = tool_calls[0].function
    return FirstToolCall(
        name=function.name,
        arguments=json.loads(function.arguments or "{}"),
    )


def first_tool_attributes(tool_call: FirstToolCall, completion: Any) -> dict[str, Any]:
    """Return trace attributes for the selected first tool."""
    usage = getattr(completion, "usage", None)
    return {
        "tool.name": tool_call.name,
        "tool.args": json.dumps(tool_call.arguments, sort_keys=True, default=str),
        "llm.token_count.prompt": get_optional_int(usage, "prompt_tokens"),
        "llm.token_count.completion": get_optional_int(usage, "completion_tokens"),
        "llm.token_count.total": get_optional_int(usage, "total_tokens"),
    }


def get_optional_int(value: Any, name: str) -> int | None:
    """Return one optional integer attribute."""
    raw = getattr(value, name, None)
    return None if raw is None else int(raw)


def require_read_tool(tool_call: FirstToolCall) -> None:
    """Require the first call to use a read tool."""
    if tool_call.name not in READ_TOOL_NAMES:
        msg = f"Expected read tool, got {tool_call.name}"
        raise AssertionError(msg)


def main() -> None:
    """Run the LLM first-tool smoke."""
    tool_call = run_smoke(load_settings())
    print(json.dumps(asdict(tool_call), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
