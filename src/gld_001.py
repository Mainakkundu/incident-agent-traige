"""End-to-end runner for the first golden incident."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver

from src.clients.glpi import GLPIClient
from src.clients.logstore import LogStoreClient
from src.config import Settings, load_settings
from src.graph import build_triage_graph
from src.mcp.itsm import ITSMTools
from src.mcp.observability import ObservabilityTools
from src.prompts import PromptContext, build_supervisor_prompt
from src.state import TriageState, initial_triage_state
from src.tracing import configure_tracing, get_tracer, set_span_attributes, shutdown_tracing


GLD001_ID = "gld_001"
GLD001_TICKET_ID = "INC-GLD-001"
GLD001_SERVICE = "payment-api"
GLD001_CONDITION = "error_rate"
GLD001_VALUE = "12%"
GLD001_BASELINE = "0.3%"
GLD001_WINDOW_START = "2026-07-31T20:20:00+00:00"
GLD001_WINDOW_END = "2026-07-31T20:26:00+00:00"
GLD001_EXPECTED_ROOT = "postgres-main"
GLD001_EXPECTED_CHAIN = ("postgres-main", "auth-service", "payment-api")
GLD001_THREAD_ID = "gld-001"
TRACER_NAME = "incident-triage-agent.gld_001"
RUN_SPAN_NAME = "incident.gld_001.run"
UNKNOWN_RETRIEVAL_STYLE = "unknown"


@dataclass(frozen=True, slots=True)
class Gld001Result:
    """Result of running gld_001 through the graph."""

    root_cause: str
    causal_chain: tuple[str, ...]
    evidence: tuple[str, ...]
    confidence: float
    gate_status: str
    approval_token_present: bool


class Gld001SupervisorModel:
    """Deterministic supervisor for the gld_001 end-to-end check."""

    def __init__(self) -> None:
        self.step = 0

    def invoke(self, messages: Sequence[Any]) -> AIMessage:
        """Return the next planned supervisor message."""
        message = planned_message(self.step)
        self.step += 1
        return message


def run_gld001(settings: Settings | None = None) -> Gld001Result:
    """Run gld_001 with local tool clients."""
    effective_settings = settings or load_settings()
    observability_tools, itsm_tools = build_default_tool_providers(effective_settings)
    state = run_gld001_with_tools(effective_settings, observability_tools, itsm_tools)
    result = result_from_state(state)
    assert_gld001_result(result)
    return result


def run_traced_gld001(settings: Settings | None = None) -> Gld001Result:
    """Run gld_001 with Phoenix tracing enabled."""
    effective_settings = settings or load_settings()
    tracing_handle = configure_tracing(effective_settings)
    tracer = get_tracer(TRACER_NAME)
    try:
        with tracer.start_as_current_span(RUN_SPAN_NAME) as span:
            set_span_attributes(span, gld001_run_attributes())
            result = run_gld001(effective_settings)
            set_span_attributes(span, gld001_result_attributes(result))
            return result
    finally:
        shutdown_tracing(tracing_handle)


def build_default_tool_providers(
    settings: Settings,
) -> tuple[ObservabilityTools, ITSMTools]:
    """Return local tool providers for gld_001."""
    logstore_client = LogStoreClient.from_settings(settings)
    glpi_client = GLPIClient.from_settings(settings)
    observability_tools = ObservabilityTools(
        log_reader=logstore_client,
        deploy_reader=logstore_client,
        metric_reader=logstore_client,
        settings=settings,
    )
    itsm_tools = ITSMTools(
        ticket_reader=glpi_client,
        ticket_writer=glpi_client,
        cmdb_reader=glpi_client,
        incident_searcher=logstore_client,
        runbook_searcher=logstore_client,
    )
    return observability_tools, itsm_tools


def run_gld001_with_tools(
    settings: Settings,
    observability_tools: ObservabilityTools,
    itsm_tools: ITSMTools,
) -> TriageState:
    """Run gld_001 with supplied tool providers."""
    graph = build_triage_graph(
        model=Gld001SupervisorModel(),
        tools=gld001_langchain_tools(observability_tools, itsm_tools),
        settings=settings,
        checkpointer=InMemorySaver(),
    )
    state = initial_triage_state(messages=(HumanMessage(content=gld001_prompt()),))
    return graph.invoke(state, config={"configurable": {"thread_id": GLD001_THREAD_ID}})


def gld001_prompt() -> str:
    """Return the gld_001 supervisor prompt."""
    context = PromptContext(
        ticket_id=GLD001_TICKET_ID,
        alerted_service=GLD001_SERVICE,
        condition=GLD001_CONDITION,
        observed_value=GLD001_VALUE,
        baseline_value=GLD001_BASELINE,
    )
    return build_supervisor_prompt(context, gld001_tool_names())


def gld001_langchain_tools(
    observability_tools: ObservabilityTools,
    itsm_tools: ITSMTools,
) -> tuple[StructuredTool, ...]:
    """Return LangChain tools needed for gld_001."""
    traced_tools = Gld001TracedTools(observability_tools, itsm_tools)
    return (
        StructuredTool.from_function(
            func=traced_tools.search_logs,
            name="search_logs",
            description=observability_tools.search_logs.__doc__ or "",
        ),
        StructuredTool.from_function(
            func=traced_tools.get_ci_dependencies,
            name="get_ci_dependencies",
            description=itsm_tools.get_ci_dependencies.__doc__ or "",
        ),
    )


class Gld001TracedTools:
    """Traced wrappers around gld_001 tools."""

    def __init__(
        self,
        observability_tools: ObservabilityTools,
        itsm_tools: ITSMTools,
    ) -> None:
        self.observability_tools = observability_tools
        self.itsm_tools = itsm_tools
        self.tracer = get_tracer(TRACER_NAME)

    def search_logs(
        self,
        service: str,
        window_start: str,
        window_end: str,
        level: str | None = None,
        keyword: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Return exact, time-bounded logs for one service."""
        attributes = tool_span_attributes(
            tool_name="search_logs",
            args={
                "service": service,
                "window_start": window_start,
                "window_end": window_end,
                "level": level,
                "keyword": keyword,
                "limit": limit,
            },
        )
        with self.tracer.start_as_current_span("tool.search_logs") as span:
            set_span_attributes(span, attributes)
            result = self.observability_tools.search_logs(
                service=service,
                window_start=window_start,
                window_end=window_end,
                level=level,
                keyword=keyword,
                limit=limit,
            )
            set_span_attributes(span, tool_result_attributes(result))
            return result

    def get_ci_dependencies(self, name_or_id: str) -> dict[str, Any]:
        """Return direct dependency edges for one configuration item."""
        attributes = tool_span_attributes(
            tool_name="get_ci_dependencies",
            args={"name_or_id": name_or_id},
        )
        with self.tracer.start_as_current_span("tool.get_ci_dependencies") as span:
            set_span_attributes(span, attributes)
            result = self.itsm_tools.get_ci_dependencies(name_or_id)
            set_span_attributes(span, tool_result_attributes(result))
            return result


def gld001_tool_names() -> tuple[str, ...]:
    """Return tool names available to the gld_001 supervisor."""
    return ("search_logs", "get_ci_dependencies")


def planned_message(step: int) -> AIMessage:
    """Return one planned supervisor message."""
    if step == 0:
        return tool_call_message(
            "call_payment_logs",
            "search_logs",
            {
                "service": "payment-api",
                "window_start": GLD001_WINDOW_START,
                "window_end": GLD001_WINDOW_END,
                "level": "ERROR",
                "keyword": "auth-service",
                "limit": 20,
            },
        )
    if step == 1:
        return tool_call_message(
            "call_payment_deps",
            "get_ci_dependencies",
            {"name_or_id": "payment-api"},
        )
    if step == 2:
        return tool_call_message(
            "call_auth_logs",
            "search_logs",
            {
                "service": "auth-service",
                "window_start": GLD001_WINDOW_START,
                "window_end": GLD001_WINDOW_END,
                "level": "ERROR",
                "keyword": "connection pool exhausted",
                "limit": 20,
            },
        )
    if step == 3:
        return tool_call_message(
            "call_auth_deps",
            "get_ci_dependencies",
            {"name_or_id": "auth-service"},
        )
    if step == 4:
        return tool_call_message(
            "call_postgres_logs",
            "search_logs",
            {
                "service": "postgres-main",
                "window_start": GLD001_WINDOW_START,
                "window_end": GLD001_WINDOW_END,
                "level": "ERROR",
                "keyword": "too many clients",
                "limit": 20,
            },
        )
    return AIMessage(content=json.dumps(gld001_diagnosis_payload()))


def tool_call_message(call_id: str, name: str, args: dict[str, Any]) -> AIMessage:
    """Return an assistant tool-call message."""
    return AIMessage(
        content="",
        tool_calls=[
            {
                "id": call_id,
                "name": name,
                "args": args,
            }
        ],
    )


def gld001_diagnosis_payload() -> dict[str, Any]:
    """Return the expected gld_001 diagnosis payload."""
    return {
        "root_cause": GLD001_EXPECTED_ROOT,
        "impacted_service": GLD001_SERVICE,
        "causal_chain": list(GLD001_EXPECTED_CHAIN),
        "evidence": [
            "postgres-main: FATAL: sorry, too many clients already",
            "auth-service: connection pool exhausted, no available connections after 5000ms",
            "payment-api: upstream auth-service timeout after 3000ms",
        ],
        "confidence": 0.87,
        "next_action": "update_ticket",
    }


def gld001_run_attributes() -> dict[str, Any]:
    """Return trace attributes for the gld_001 run."""
    return {
        "incident.golden_id": GLD001_ID,
        "incident.ticket_id": GLD001_TICKET_ID,
        "incident.alerted_service": GLD001_SERVICE,
        "incident.condition": GLD001_CONDITION,
        "incident.observed_value": GLD001_VALUE,
        "incident.baseline_value": GLD001_BASELINE,
    }


def gld001_result_attributes(result: Gld001Result) -> dict[str, Any]:
    """Return trace attributes for the gld_001 result."""
    return {
        "incident.root_cause": result.root_cause,
        "incident.causal_chain": " -> ".join(result.causal_chain),
        "incident.confidence": result.confidence,
        "gate.status": result.gate_status,
        "gate.approval_token_present": result.approval_token_present,
    }


def tool_span_attributes(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Return trace attributes for one tool call."""
    return {
        "tool.name": tool_name,
        "retrieval_style": expected_retrieval_style(tool_name),
        "hypothesis_at_this_step": hypothesis_at_this_step(tool_name, args),
        "tool.args": json.dumps(args, sort_keys=True, default=str),
    }


def tool_result_attributes(result: dict[str, Any]) -> dict[str, Any]:
    """Return trace attributes from one tool result."""
    return {
        "retrieval_style": result.get("retrieval_style", UNKNOWN_RETRIEVAL_STYLE),
        "tool.result_count": tool_result_count(result),
    }


def expected_retrieval_style(tool_name: str) -> str:
    """Return the retrieval style expected for one tool."""
    if tool_name == "search_logs":
        return "fulltext"
    if tool_name == "get_ci_dependencies":
        return "graph"
    return UNKNOWN_RETRIEVAL_STYLE


def hypothesis_at_this_step(tool_name: str, args: dict[str, Any]) -> str:
    """Return the investigation hypothesis for one gld_001 tool call."""
    service = str(args.get("service") or args.get("name_or_id") or "")
    if tool_name == "search_logs" and service == "payment-api":
        return "payment-api may be a victim of auth-service upstream timeouts"
    if tool_name == "get_ci_dependencies" and service == "payment-api":
        return "payment-api depends on auth-service, so inspect auth-service next"
    if tool_name == "search_logs" and service == "auth-service":
        return "auth-service may be failing because its database pool is exhausted"
    if tool_name == "get_ci_dependencies" and service == "auth-service":
        return "auth-service depends on postgres-main, so inspect postgres-main next"
    if tool_name == "search_logs" and service == "postgres-main":
        return "postgres-main connection pressure is the likely root cause"
    return "continue evidence gathering for gld_001"


def tool_result_count(result: dict[str, Any]) -> int:
    """Return a count for common tool result collections."""
    for key in ("logs", "dependencies", "incidents", "runbooks", "deploys", "points"):
        value = result.get(key)
        if isinstance(value, list):
            return len(value)
    return 0


def result_from_state(state: TriageState) -> Gld001Result:
    """Return a typed gld_001 result from graph state."""
    diagnosis = json.loads(last_ai_message(state["messages"]).content)
    gate_decision = state["gate_decision"] or {}
    return Gld001Result(
        root_cause=str(diagnosis["root_cause"]),
        causal_chain=tuple(str(item) for item in diagnosis["causal_chain"]),
        evidence=tuple(str(item) for item in diagnosis["evidence"]),
        confidence=float(diagnosis["confidence"]),
        gate_status=str(gate_decision.get("status")),
        approval_token_present=bool(state["approval_token"]),
    )


def last_ai_message(messages: Sequence[BaseMessage]) -> AIMessage:
    """Return the last assistant message from graph messages."""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            return message
    msg = "gld_001 run did not produce a final diagnosis"
    raise ValueError(msg)


def assert_gld001_result(result: Gld001Result) -> None:
    """Require the gld_001 result to match the golden case."""
    if result.root_cause != GLD001_EXPECTED_ROOT:
        msg = f"expected root {GLD001_EXPECTED_ROOT}, got {result.root_cause}"
        raise AssertionError(msg)
    if result.causal_chain != GLD001_EXPECTED_CHAIN:
        msg = f"expected chain {GLD001_EXPECTED_CHAIN}, got {result.causal_chain}"
        raise AssertionError(msg)
    if result.gate_status != "auto_write":
        msg = f"expected auto_write gate, got {result.gate_status}"
        raise AssertionError(msg)
    if not result.approval_token_present:
        msg = "expected approval token from gate"
        raise AssertionError(msg)


def main() -> None:
    """Run gld_001 from the command line."""
    result = run_traced_gld001()
    print(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":
    main()
