"""Typed LangGraph state for incident triage."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Sequence, TypedDict

try:
    from langchain_core.messages import AnyMessage
except ImportError:
    AnyMessage = Any


class TriageState(TypedDict):
    """Complete state carried through the supervisor graph."""

    messages: Annotated[list[AnyMessage], operator.add]
    llm_calls: int
    services_seen: Annotated[list[str], operator.add]
    approval_token: str | None
    gate_decision: dict[str, Any] | None


class TriageStateUpdate(TypedDict, total=False):
    """Partial state returned by graph nodes."""

    messages: list[AnyMessage]
    llm_calls: int
    services_seen: list[str]
    approval_token: str | None
    gate_decision: dict[str, Any] | None


def initial_triage_state(
    messages: Sequence[AnyMessage] = (),
    approval_token: str | None = None,
) -> TriageState:
    """Return initial triage graph state."""
    return {
        "messages": list(messages),
        "llm_calls": 0,
        "services_seen": [],
        "approval_token": approval_token,
        "gate_decision": None,
    }


def record_service_seen(service: str) -> TriageStateUpdate:
    """Return a state update for one observed service."""
    normalized = service.strip()
    if not normalized:
        msg = "service name is required"
        raise ValueError(msg)
    return {"services_seen": [normalized]}


def increment_llm_calls(state: TriageState) -> TriageStateUpdate:
    """Return a state update for one LLM call."""
    return {"llm_calls": state["llm_calls"] + 1}


def set_approval_token(approval_token: str | None) -> TriageStateUpdate:
    """Return a state update for approval token changes."""
    return {"approval_token": approval_token}
