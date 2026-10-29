"""LangGraph supervisor graph for incident triage."""

from __future__ import annotations

from functools import partial
from importlib.util import find_spec
from typing import Any, Literal, Protocol, Sequence

from src.config import Settings
from src.gate import gate_state
from src.state import TriageState, TriageStateUpdate


SUPERVISOR_NODE = "supervisor"
TOOL_NODE = "tool_node"
GATE_NODE = "gate"
WRITE_NODE = "write"
END_NODE = "__end__"
INTERRUPT_BEFORE_NODES = (WRITE_NODE,)

GraphRoute = Literal["tool_node", "gate"]
GateRoute = Literal["write", "__end__"]


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
        return "gate"
    if not state["messages"]:
        return "gate"
    return "tool_node" if message_has_tool_calls(state["messages"][-1]) else "gate"


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


def should_write(state: TriageState) -> GateRoute:
    """Route approved diagnoses to the write interruption node."""
    decision = state.get("gate_decision")
    if not isinstance(decision, dict):
        return "__end__"
    return "write" if decision.get("status") == "auto_write" else "__end__"


def write_node(state: TriageState) -> TriageStateUpdate:
    """Return no changes after human approval resumes the write path."""
    return {}


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
    graph.add_node(WRITE_NODE, write_node)
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
    graph.add_conditional_edges(
        GATE_NODE,
        should_write,
        {
            WRITE_NODE: WRITE_NODE,
            END_NODE: END,
        },
    )
    graph.add_edge(WRITE_NODE, END)
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=list(INTERRUPT_BEFORE_NODES),
    )


def require_graph_dependency() -> None:
    """Require LangGraph only when compiling the graph."""
    if find_spec("langgraph.graph") is None or find_spec("langgraph.prebuilt") is None:
        msg = "langgraph is required to compile the triage graph"
        raise ImportError(msg)


def require_tools(tools: Sequence[Any]) -> None:
    """Require at least one tool for the ReAct loop."""
    if not tools:
        msg = "at least one tool is required"
        raise ValueError(msg)
