"""Ask Groq for one investigation tool call, then execute that tool."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.groq_phoenix_smoke import require_groq_api_key
from scripts.llm_smoke_test_01 import (
    FirstToolCall,
    create_first_tool_completion,
    extract_first_tool_call,
    first_tool_attributes,
    require_read_tool,
)
from src.config import Settings, load_settings
from src.gld_001 import (
    GLD001_WINDOW_END,
    GLD001_WINDOW_START,
    build_default_tool_providers,
    gld001_prompt,
    tool_result_count,
)
from src.mcp.itsm import ITSMTools
from src.mcp.observability import ObservabilityTools
from src.tracing import configure_tracing, get_tracer, set_span_attributes, shutdown_tracing


TRACER_NAME = "incident-triage-agent.llm_tool_execute_smoke_01"
RUN_SPAN_NAME = "incident.llm_tool_execute_smoke_01.run"
MAX_PREVIEW_CHARS = 1200


@dataclass(frozen=True, slots=True)
class LLMToolExecutionResult:
    """Result of one LLM-selected tool execution."""

    selected_tool: str
    selected_args: dict[str, Any]
    result_count: int
    result: dict[str, Any]


def run_smoke(settings: Settings) -> LLMToolExecutionResult:
    """Run the full LLM tool-selection and execution smoke."""
    require_groq_api_key(settings)
    observability_tools, itsm_tools = build_default_tool_providers(settings)
    tracing_handle = configure_tracing(settings)
    try:
        return create_traced_tool_execution(settings, observability_tools, itsm_tools)
    finally:
        shutdown_tracing(tracing_handle)


def create_traced_tool_execution(
    settings: Settings,
    observability_tools: ObservabilityTools,
    itsm_tools: ITSMTools,
) -> LLMToolExecutionResult:
    """Ask Groq for one read tool call, execute it, and trace both steps."""
    tracer = get_tracer(TRACER_NAME)
    with tracer.start_as_current_span(RUN_SPAN_NAME) as run_span:
        completion = create_first_tool_completion(settings, prompt=full_loop_prompt())
        tool_call = extract_first_tool_call(completion)
        require_read_tool(tool_call)
        set_span_attributes(run_span, first_tool_attributes(tool_call, completion))

        with tracer.start_as_current_span(f"tool.{tool_call.name}") as tool_span:
            set_span_attributes(tool_span, tool_call_attributes(tool_call))
            result = execute_tool_call(tool_call, observability_tools, itsm_tools)
            result_count = tool_result_count(result)
            set_span_attributes(tool_span, tool_result_attributes(result, result_count))

        set_span_attributes(
            run_span,
            {
                "tool.executed": True,
                "tool.result_count": result_count,
                "tool.result.preview": result_preview(result),
            },
        )
        return LLMToolExecutionResult(
            selected_tool=tool_call.name,
            selected_args=tool_call.arguments,
            result_count=result_count,
            result=result,
        )


def full_loop_prompt() -> str:
    """Return the gld_001 prompt with the incident time window included."""
    return "\n\n".join(
        (
            gld001_prompt(),
            "Incident time window:",
            f"Start: {GLD001_WINDOW_START}",
            f"End: {GLD001_WINDOW_END}",
            "For time-bounded tools, use this incident time window.",
        )
    )


def execute_tool_call(
    tool_call: FirstToolCall,
    observability_tools: ObservabilityTools,
    itsm_tools: ITSMTools,
) -> dict[str, Any]:
    """Execute one LLM-selected read tool call."""
    dispatch = tool_dispatch(observability_tools, itsm_tools)
    try:
        tool = dispatch[tool_call.name]
    except KeyError as exc:
        msg = f"No executable read tool named {tool_call.name}"
        raise AssertionError(msg) from exc
    return tool(**tool_call.arguments)


def tool_dispatch(
    observability_tools: ObservabilityTools,
    itsm_tools: ITSMTools,
) -> dict[str, Callable[..., dict[str, Any]]]:
    """Return executable read-tool dispatch table."""
    return {
        "get_ticket": itsm_tools.get_ticket,
        "search_logs": observability_tools.search_logs,
        "get_recent_deploys": observability_tools.get_recent_deploys,
        "get_ci_dependencies": itsm_tools.get_ci_dependencies,
        "get_similar_incidents": itsm_tools.get_similar_incidents,
        "search_runbooks": itsm_tools.search_runbooks,
    }


def tool_call_attributes(tool_call: FirstToolCall) -> dict[str, Any]:
    """Return trace attributes for the executable tool span."""
    return {
        "tool.name": tool_call.name,
        "tool.args": json.dumps(tool_call.arguments, sort_keys=True, default=str),
    }


def tool_result_attributes(result: dict[str, Any], result_count: int) -> dict[str, Any]:
    """Return trace attributes for the executed tool result."""
    return {
        "tool.result_count": result_count,
        "tool.result.preview": result_preview(result),
    }


def result_preview(result: dict[str, Any]) -> str:
    """Return a compact JSON preview of a tool result."""
    raw = json.dumps(result, sort_keys=True, default=str)
    if len(raw) <= MAX_PREVIEW_CHARS:
        return raw
    return raw[:MAX_PREVIEW_CHARS] + "...[truncated]"


def main() -> None:
    """Run the full-loop smoke test from the command line."""
    result = run_smoke(load_settings())
    print(json.dumps(asdict(result), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
