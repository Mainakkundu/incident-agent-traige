"""LangGraph supervisor graph for incident triage."""

from __future__ import annotations

from functools import partial
from typing import Any, Literal, Protocol, Sequence

from src.config import Settings
from src.gate import gate_state
from src.state import TriageState, TriageStateUpdate


SUPERVISOR_NODE = "supervisor"
TOOL_NODE = "tool_node"
GATE_NODE = "gate"
END_NODE = "__end__"

GraphRoute = Literal["tool_node", "gate"]


class ChatModel(Protocol):
    """Model interface required by the supervisor node."""

    def invoke(self, messages: Sequence[Any]) -> Any:
        """Return the next assistant message."""
        ...


def supervisor_node(state: TriageState, model: ChatModel) -> TriageStateUpdate:
    """Ask the model for the next step."""
    response = model.invoke(state["messages"])
    return {
        "messages": [response],
        "llm_calls": state["llm_calls"] + 1,
    }


def should_continue(state: TriageState, settings: Settings) -> GraphRoute:
    """Route to tools when requested, otherwise route to the gate."""
    if state["llm_calls"] >= settings.agent_max_steps:
        return GATE_NODE
    if not state["messages"]:
        return GATE_NODE
    return TOOL_NODE if message_has_tool_calls(state["messages"][-1]) else GATE_NODE


def message_has_tool_calls(message: Any) -> bool:
    """Return whether a message requested at least one tool call."""
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        return True
    if isinstance(message, dict):
        return bool(message.get("tool_calls"))
    return False


def gate_node(state: TriageState, settings: Settings) -> TriageStateUpdate:
    """Apply the confidence gate to the final diagnosis."""
    return gate_state(state, settings)


def build_triage_graph(
    model: ChatModel,
    tools: Sequence[Any],
    settings: Settings,
    checkpointer: Any,
) -> Any:
    """Compile the explicit supervisor graph."""
    require_graph_dependency()
    require_tools(tools)
    if checkpointer is None:
        msg = "checkpointer is required"
        raise ValueError(msg)

    from langgraph.graph import END, StateGraph
    from langgraph.prebuilt import ToolNode

    graph = StateGraph(TriageState)
    graph.add_node(SUPERVISOR_NODE, partial(supervisor_node, model=model))
    graph.add_node(TOOL_NODE, ToolNode(list(tools)))
    graph.add_node(GATE_NODE, partial(gate_node, settings=settings))
    graph.set_entry_point(SUPERVISOR_NODE)
    graph.add_conditional_edges(
        SUPERVISOR_NODE,
        partial(should_continue, settings=settings),
        {
            TOOL_NODE: TOOL_NODE,
            GATE_NODE: GATE_NODE,
        },
    )
    graph.add_edge(TOOL_NODE, SUPERVISOR_NODE)
    graph.add_edge(GATE_NODE, END)
    return graph.compile(checkpointer=checkpointer)


def require_graph_dependency() -> None:
    """Require LangGraph only when compiling the graph."""
    try:
        import langgraph.graph
        import langgraph.prebuilt
    except ImportError as exc:
        msg = "langgraph is required to compile the triage graph"
        raise ImportError(msg) from exc


def require_tools(tools: Sequence[Any]) -> None:
    """Require at least one tool for the ReAct loop."""
    if not tools:
        msg = "at least one tool is required"
        raise ValueError(msg)
