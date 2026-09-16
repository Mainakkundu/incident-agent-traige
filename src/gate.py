"""Confidence gate for incident diagnosis write-back."""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Literal, Mapping, Sequence

from src.config import Settings
from src.state import TriageState, TriageStateUpdate


GateStatus = Literal["auto_write", "escalate"]
TokenFactory = Callable[[], str]


@dataclass(frozen=True, slots=True)
class Diagnosis:
    """Structured final diagnosis from the supervisor."""

    root_cause: str
    impacted_service: str
    causal_chain: tuple[str, ...]
    evidence: tuple[str, ...]
    confidence: float
    next_action: str


@dataclass(frozen=True, slots=True)
class GateDecision:
    """Result of applying write-back governance."""

    status: GateStatus
    confidence: float
    approval_token: str | None
    token_expires_at: str | None
    reason: str
    next_action: str


def gate_state(
    state: TriageState,
    settings: Settings,
    token_factory: TokenFactory | None = None,
    now: datetime | None = None,
) -> TriageStateUpdate:
    """Return gate updates for the current graph state."""
    diagnosis = diagnosis_from_state(state)
    decision = gate_diagnosis(
        diagnosis=diagnosis,
        settings=settings,
        cap_hit=state["llm_calls"] >= settings.agent_max_steps,
        token_factory=token_factory or default_approval_token,
        now=now,
    )
    return gate_update(decision)


def gate_diagnosis(
    diagnosis: Diagnosis,
    settings: Settings,
    cap_hit: bool = False,
    token_factory: TokenFactory | None = None,
    now: datetime | None = None,
) -> GateDecision:
    """Return the approval or escalation decision."""
    require_confidence(diagnosis.confidence)
    if cap_hit:
        return escalation_decision(diagnosis.confidence, "step cap hit")
    if diagnosis_is_uncertain(diagnosis):
        return escalation_decision(diagnosis.confidence, "diagnosis is uncertain")
    if diagnosis.confidence < settings.auto_write_confidence:
        return escalation_decision(diagnosis.confidence, "confidence below threshold")
    token = (token_factory or default_approval_token)()
    require_token(token)
    expires_at = token_expiry(now or datetime.now(UTC), settings)
    return GateDecision(
        status="auto_write",
        confidence=diagnosis.confidence,
        approval_token=token,
        token_expires_at=expires_at.isoformat(),
        reason="confidence meets threshold",
        next_action="update_ticket",
    )


def diagnosis_from_state(state: TriageState) -> Diagnosis:
    """Return a diagnosis parsed from the latest graph message."""
    if not state["messages"]:
        msg = "gate requires at least one message"
        raise ValueError(msg)
    return diagnosis_from_message(state["messages"][-1])


def diagnosis_from_message(message: Any) -> Diagnosis:
    """Return a diagnosis parsed from one message."""
    if isinstance(message, Mapping):
        content = message.get("content", message)
    else:
        content = getattr(message, "content", message)
    if isinstance(content, Mapping):
        return diagnosis_from_mapping(content)
    if isinstance(content, str):
        return diagnosis_from_mapping(json.loads(content))
    msg = "diagnosis message must contain a JSON object"
    raise ValueError(msg)


def diagnosis_from_mapping(data: Mapping[str, Any]) -> Diagnosis:
    """Return a diagnosis from mapped fields."""
    return Diagnosis(
        root_cause=require_text(data, "root_cause"),
        impacted_service=require_text(data, "impacted_service"),
        causal_chain=tuple_from_sequence(data, "causal_chain"),
        evidence=tuple_from_sequence(data, "evidence"),
        confidence=float(data["confidence"]),
        next_action=require_text(data, "next_action"),
    )


def diagnosis_is_uncertain(diagnosis: Diagnosis) -> bool:
    """Return whether the diagnosis should require human review."""
    action = diagnosis.next_action.lower()
    return (
        not diagnosis.root_cause.strip()
        or not diagnosis.evidence
        or "escalat" in action
        or "human" in action
        or "manual" in action
    )


def escalation_decision(confidence: float, reason: str) -> GateDecision:
    """Return an escalation gate decision."""
    return GateDecision(
        status="escalate",
        confidence=confidence,
        approval_token=None,
        token_expires_at=None,
        reason=reason,
        next_action="escalate",
    )


def gate_update(decision: GateDecision) -> TriageStateUpdate:
    """Return state changes for one gate decision."""
    return {
        "approval_token": decision.approval_token,
        "gate_decision": asdict(decision),
    }


def token_expiry(now: datetime, settings: Settings) -> datetime:
    """Return approval token expiry time."""
    return now + timedelta(seconds=settings.approval_token_ttl_seconds)


def default_approval_token() -> str:
    """Return a new approval token."""
    return secrets.token_urlsafe(32)


def require_confidence(confidence: float) -> None:
    """Require confidence to be in the expected range."""
    if confidence < 0.0 or confidence > 1.0:
        msg = "confidence must be between 0.0 and 1.0"
        raise ValueError(msg)


def require_token(token: str) -> None:
    """Require an issued token."""
    if not token:
        msg = "approval token factory returned an empty token"
        raise ValueError(msg)


def require_text(data: Mapping[str, Any], key: str) -> str:
    """Return one required text field."""
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"{key} is required"
        raise ValueError(msg)
    return value


def tuple_from_sequence(data: Mapping[str, Any], key: str) -> tuple[str, ...]:
    """Return one required string sequence field."""
    value = data.get(key)
    if not isinstance(value, Sequence) or isinstance(value, str):
        msg = f"{key} must be a sequence"
        raise ValueError(msg)
    values = tuple(str(item) for item in value if str(item).strip())
    if not values:
        msg = f"{key} must not be empty"
        raise ValueError(msg)
    return values
