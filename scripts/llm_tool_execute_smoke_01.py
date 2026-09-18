"""Run gld_001 as a real LLM tool loop."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from groq import Groq

from scripts.groq_phoenix_smoke import groq_sdk_base_url, require_groq_api_key
from scripts.llm_smoke_test_01 import (
    FirstToolCall,
    extract_first_tool_call,
    first_tool_attributes,
    require_read_tool,
    tool_schemas,
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
MAX_TOOL_STEPS = 8
TEMPERATURE = 0.0
MAX_COMPLETION_TOKENS = 600


@dataclass(frozen=True, slots=True)
class ToolExecution:
    """One executed LLM-selected tool call."""

    step: int
    tool: str
    args: dict[str, Any]
    result_count: int


@dataclass(frozen=True, slots=True)
class LLMToolExecutionResult:
    """Result of the full LLM investigation loop."""

    final_answer: dict[str, Any]
    tool_executions: tuple[ToolExecution, ...]


def run_smoke(settings: Settings) -> LLMToolExecutionResult:
    """Run the full LLM tool-selection, execution, and final-answer loop."""
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
    """Let Groq repeatedly choose read tools, execute them, then return a diagnosis."""
    tracer = get_tracer(TRACER_NAME)
    client = Groq(
        api_key=settings.groq_api_key,
        base_url=groq_sdk_base_url(settings.groq_base_url),
        timeout=settings.http_timeout_seconds,
    )
    messages = initial_messages()
    executions: list[ToolExecution] = []
    dependency_targets: set[str] = set()
    inspected_log_services: set[str] = set()

    with tracer.start_as_current_span(RUN_SPAN_NAME) as run_span:
        set_span_attributes(run_span, {"input.value": messages[0]["content"]})
        for step in range(1, MAX_TOOL_STEPS + 1):
            completion = create_tool_loop_completion(client, settings, messages)
            message = completion.choices[0].message
            tool_calls = getattr(message, "tool_calls", None) or []
            if not tool_calls:
                uninspected_targets = dependency_targets - inspected_log_services
                if uninspected_targets and step < MAX_TOOL_STEPS:
                    append_uninspected_targets_message(messages, uninspected_targets)
                    continue
                final_answer = parse_final_answer(message.content or "{}")
                set_final_attributes(run_span, final_answer, executions)
                return LLMToolExecutionResult(final_answer, tuple(executions))

            append_assistant_tool_message(messages, message)
            for raw_tool_call in tool_calls:
                tool_call = first_tool_call_from_raw(raw_tool_call)
                require_read_tool(tool_call)
                set_span_attributes(run_span, first_tool_attributes(tool_call, completion))
                result = execute_traced_tool_call(
                    tracer,
                    step,
                    tool_call,
                    observability_tools,
                    itsm_tools,
                )
                result_count = tool_result_count(result)
                update_investigation_state(
                    tool_call,
                    result,
                    dependency_targets,
                    inspected_log_services,
                )
                executions.append(
                    ToolExecution(
                        step=step,
                        tool=tool_call.name,
                        args=tool_call.arguments,
                        result_count=result_count,
                    )
                )
                append_tool_result_message(messages, raw_tool_call.id, tool_call.name, result)

        final_answer = force_final_answer(client, settings, messages)
        set_final_attributes(run_span, final_answer, executions)
        return LLMToolExecutionResult(final_answer, tuple(executions))


def initial_messages() -> list[dict[str, Any]]:
    """Return the initial chat payload for the investigation."""
    return [{"role": "user", "content": full_loop_prompt()}]


def create_tool_loop_completion(
    client: Groq,
    settings: Settings,
    messages: list[dict[str, Any]],
) -> Any:
    """Create one loop completion where Groq can either call tools or answer."""
    return client.chat.completions.create(
        messages=messages,
        model=settings.groq_model,
        tools=tool_schemas(),
        tool_choice="auto",
        temperature=TEMPERATURE,
        max_completion_tokens=MAX_COMPLETION_TOKENS,
    )


def force_final_answer(
    client: Groq,
    settings: Settings,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Ask Groq for a final diagnosis after the tool-step budget is exhausted."""
    final_messages = messages + [
        {
            "role": "user",
            "content": (
                "Stop calling tools. Return only final JSON with keys root_cause, "
                "impacted_service, causal_chain, evidence, confidence, and next_action."
            ),
        }
    ]
    completion = client.chat.completions.create(
        messages=final_messages,
        model=settings.groq_model,
        temperature=TEMPERATURE,
        max_completion_tokens=MAX_COMPLETION_TOKENS,
    )
    return parse_final_answer(completion.choices[0].message.content or "{}")


def full_loop_prompt() -> str:
    """Return the gld_001 prompt with enough runtime context for real tools."""
    return "\n\n".join(
        (
            gld001_prompt(),
            "Incident time window:",
            f"Start: {GLD001_WINDOW_START}",
            f"End: {GLD001_WINDOW_END}",
            "For time-bounded tools, use this incident time window.",
            "Run the investigation end to end. Call read tools until you have enough evidence.",
            (
                "If logs show upstream timeouts or pool/database pressure, inspect that service's "
                "CMDB dependencies and then inspect the upstream dependency logs before finalizing."
            ),
            (
                "In dependency results, relation_type=depends_on means source depends on target. "
                "After get_ci_dependencies returns targets, inspect target service logs before final JSON."
            ),
            (
                "Do not name a service as root cause while it still has an uninspected upstream "
                "dependency that could explain its failure."
            ),
            (
                "When done, return only JSON with keys root_cause, impacted_service, "
                "causal_chain, evidence, confidence, and next_action. Confidence must be a number "
                "from 0.0 to 1.0. next_action must be update_ticket or escalate."
            ),
        )
    )


def first_tool_call_from_raw(raw_tool_call: Any) -> FirstToolCall:
    """Return a typed tool call from one SDK tool-call object."""
    completion = FakeSingleToolCompletion(raw_tool_call)
    return extract_first_tool_call(completion)


class FakeSingleToolCompletion:
    """Small adapter so one raw SDK tool call can reuse the existing parser."""

    def __init__(self, raw_tool_call: Any) -> None:
        self.choices = [FakeChoice(FakeMessage([raw_tool_call]))]


class FakeChoice:
    def __init__(self, message: object) -> None:
        self.message = message


class FakeMessage:
    def __init__(self, tool_calls: list[object]) -> None:
        self.tool_calls = tool_calls
        self.content = None


def append_assistant_tool_message(messages: list[dict[str, Any]], message: Any) -> None:
    """Append the assistant tool-call message in chat-completions format."""
    messages.append(
        {
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    },
                }
                for tool_call in message.tool_calls
            ],
        }
    )


def append_tool_result_message(
    messages: list[dict[str, Any]],
    tool_call_id: str,
    tool_name: str,
    result: dict[str, Any],
) -> None:
    """Append one executed tool result back to the LLM conversation."""
    messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result_preview(result),
        }
    )


def append_uninspected_targets_message(
    messages: list[dict[str, Any]],
    targets: set[str],
) -> None:
    """Tell the LLM to inspect dependency targets before finalizing."""
    target_list = ", ".join(sorted(targets))
    messages.append(
        {
            "role": "user",
            "content": (
                "You tried to finalize before inspecting dependency target logs. "
                f"Inspect these target services with search_logs first: {target_list}."
            ),
        }
    )


def update_investigation_state(
    tool_call: FirstToolCall,
    result: dict[str, Any],
    dependency_targets: set[str],
    inspected_log_services: set[str],
) -> None:
    """Track which dependency targets still need log inspection."""
    if tool_call.name == "search_logs":
        service = tool_call.arguments.get("service")
        if isinstance(service, str):
            inspected_log_services.add(service)
    if tool_call.name == "get_ci_dependencies":
        dependency_targets.update(dependency_target_names(result))


def dependency_target_names(result: dict[str, Any]) -> set[str]:
    """Return dependency target names from one dependency tool result."""
    names: set[str] = set()
    for dependency in result.get("dependencies", []):
        if not isinstance(dependency, dict):
            continue
        target = dependency.get("target")
        if isinstance(target, dict) and isinstance(target.get("name"), str):
            names.add(target["name"])
    return names


def execute_traced_tool_call(
    tracer: Any,
    step: int,
    tool_call: FirstToolCall,
    observability_tools: ObservabilityTools,
    itsm_tools: ITSMTools,
) -> dict[str, Any]:
    """Execute one selected read tool and trace its real output."""
    with tracer.start_as_current_span(f"tool.{step}.{tool_call.name}") as tool_span:
        set_span_attributes(tool_span, tool_call_attributes(tool_call, step))
        result = execute_tool_call(tool_call, observability_tools, itsm_tools)
        result_count = tool_result_count(result)
        set_span_attributes(tool_span, tool_result_attributes(result, result_count))
        return result


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


def tool_call_attributes(tool_call: FirstToolCall, step: int) -> dict[str, Any]:
    """Return trace attributes for one executable tool span."""
    return {
        "tool.step": step,
        "tool.name": tool_call.name,
        "tool.args": json.dumps(tool_call.arguments, sort_keys=True, default=str),
    }


def tool_result_attributes(result: dict[str, Any], result_count: int) -> dict[str, Any]:
    """Return trace attributes for one executed tool result."""
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


def parse_final_answer(content: str) -> dict[str, Any]:
    """Parse the final JSON answer from model content."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(content[start : end + 1])


def set_final_attributes(
    span: Any,
    final_answer: dict[str, Any],
    executions: list[ToolExecution],
) -> None:
    """Set final answer attributes on the run span."""
    set_span_attributes(
        span,
        {
            "tool.execution_count": len(executions),
            "output.value": json.dumps(final_answer, sort_keys=True, default=str),
            "incident.root_cause": final_answer.get("root_cause"),
            "incident.causal_chain": json.dumps(final_answer.get("causal_chain")),
            "incident.confidence": final_answer.get("confidence"),
            "incident.next_action": final_answer.get("next_action"),
        },
    )


def main() -> None:
    """Run the full-loop smoke test from the command line."""
    result = run_smoke(load_settings())
    print(json.dumps(asdict(result), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
