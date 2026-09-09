"""Supervisor prompts for incident triage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


SUPERVISOR_ROLE = (
    "You are the incident triage supervisor. Your job is to investigate the "
    "current alert, find the most likely root cause, cite evidence, and decide "
    "whether the ticket should be updated or escalated."
)
NO_ANSWER_HINTS = (
    "Do not assume a root cause from service names, prior examples, or common "
    "patterns. The correct answer must come from tool results gathered during "
    "this run."
)
INVESTIGATION_METHOD = (
    "Start from the alerted service. Read the ticket, inspect recent deploys, "
    "check time-bounded logs, and follow CMDB dependency edges only when the "
    "evidence gives a reason to inspect another service."
)
EVIDENCE_RULES = (
    "Keep a concise evidence chain. Prefer exact log lines, dependency edges, "
    "deploy records, metrics, similar incidents, and runbooks returned by tools. "
    "If evidence is missing or contradictory, say so."
)
GOVERNANCE_RULES = (
    "Read tools are allowed. Do not call write tools unless approval_token is "
    "present in state. If confidence is low, uncertain, or the step cap is hit, "
    "escalate instead of pretending certainty."
)
OUTPUT_RULES = (
    "Final answer must include root_cause, impacted_service, causal_chain, "
    "evidence, confidence, and next_action."
)
TOOL_SECTION_HEADER = "Available tools:"


@dataclass(frozen=True, slots=True)
class PromptContext:
    """Runtime context inserted into the supervisor prompt."""

    ticket_id: str
    alerted_service: str
    condition: str
    observed_value: str
    baseline_value: str | None = None


def build_supervisor_prompt(
    context: PromptContext,
    tool_names: Sequence[str],
) -> str:
    """Build the method-only supervisor prompt."""
    require_prompt_context(context)
    return "\n\n".join(
        (
            SUPERVISOR_ROLE,
            alert_section(context),
            tool_section(tool_names),
            INVESTIGATION_METHOD,
            EVIDENCE_RULES,
            GOVERNANCE_RULES,
            NO_ANSWER_HINTS,
            OUTPUT_RULES,
        )
    )


def require_prompt_context(context: PromptContext) -> None:
    """Require alert context fields."""
    required_values = (
        context.ticket_id,
        context.alerted_service,
        context.condition,
        context.observed_value,
    )
    if any(not value.strip() for value in required_values):
        msg = "ticket_id, alerted_service, condition, and observed_value are required"
        raise ValueError(msg)


def alert_section(context: PromptContext) -> str:
    """Return the runtime alert section."""
    fields = [
        f"Ticket ID: {context.ticket_id}",
        f"Alerted service: {context.alerted_service}",
        f"Condition: {context.condition}",
        f"Observed value: {context.observed_value}",
    ]
    if context.baseline_value:
        fields.append(f"Baseline value: {context.baseline_value}")
    return "Alert context:\n" + "\n".join(fields)


def tool_section(tool_names: Sequence[str]) -> str:
    """Return the available-tool section."""
    if not tool_names:
        msg = "at least one tool name is required"
        raise ValueError(msg)
    lines = [f"- {tool_name}" for tool_name in tool_names]
    return TOOL_SECTION_HEADER + "\n" + "\n".join(lines)
