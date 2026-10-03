"""Reconstruct incident audit trails from persisted Phoenix spans."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from src.config import Settings


RUN_ID_ATTRIBUTE = "incident.run_id"
DEFAULT_SPAN_LIMIT = 1000


class SpanSource(Protocol):
    """Read persisted trace spans for one Phoenix project."""

    def get_run_spans(
        self,
        project_name: str,
        run_id: str,
        limit: int,
    ) -> Sequence[Mapping[str, Any]]:
        """Return all persisted spans for one incident run."""
        ...


class RunAuditReader(Protocol):
    """Read one reconstructed incident run."""

    def get_run(self, run_id: str) -> RunAudit | None:
        """Return an audit trail, or None when the run does not exist."""
        ...


@dataclass(frozen=True, slots=True)
class AuditStep:
    """One tool decision and its recorded outcome."""

    step: int
    span_id: str | None
    tool_name: str
    arguments: dict[str, Any]
    result: Any
    result_count: int | None
    retrieval_style: str | None
    hypothesis: str | None
    started_at: str | None
    ended_at: str | None
    status: str | None


@dataclass(frozen=True, slots=True)
class RunAudit:
    """Complete reconstructable audit view for an incident run."""

    run_id: str
    trace_id: str | None
    incident_id: str | None
    ticket_id: str | None
    status: str
    started_at: str | None
    ended_at: str | None
    alerted_service: str | None
    services_investigated: tuple[str, ...]
    steps: tuple[AuditStep, ...]
    diagnosis: dict[str, Any] | None
    confidence: float | None
    gate_status: str | None
    approval_token_present: bool


class PhoenixClientSpanSource:
    """Read spans through the official Phoenix query client."""

    def __init__(self, base_url: str) -> None:
        from phoenix.client import Client

        self.client = Client(base_url=base_url)

    def get_run_spans(
        self,
        project_name: str,
        run_id: str,
        limit: int,
    ) -> Sequence[Mapping[str, Any]]:
        """Find the run span by attribute, then retrieve its complete trace."""
        run_spans = self.client.spans.get_spans(
            project_identifier=project_name,
            attributes={RUN_ID_ATTRIBUTE: run_id},
            limit=limit,
        )
        if not run_spans:
            return []
        latest_run_span = max(run_spans, key=span_start_sort_key)
        trace_id = span_trace_id(latest_run_span)
        if trace_id is None:
            return []
        return self.client.spans.get_spans(
            project_identifier=project_name,
            trace_ids=[trace_id],
            limit=limit,
        )


class PhoenixRunAuditReader:
    """Reconstruct run audits from Phoenix span attributes."""

    def __init__(
        self,
        span_source: SpanSource,
        project_name: str,
        span_limit: int = DEFAULT_SPAN_LIMIT,
    ) -> None:
        if not project_name.strip():
            msg = "Phoenix project name is required"
            raise ValueError(msg)
        if span_limit < 1:
            msg = "span limit must be positive"
            raise ValueError(msg)
        self.span_source = span_source
        self.project_name = project_name
        self.span_limit = span_limit

    @classmethod
    def from_settings(cls, settings: Settings) -> PhoenixRunAuditReader:
        """Build a Phoenix-backed reader from application settings."""
        return cls(
            span_source=PhoenixClientSpanSource(settings.phoenix_endpoint),
            project_name=settings.phoenix_project_name,
        )

    def get_run(self, run_id: str) -> RunAudit | None:
        """Return an audit reconstructed from all matching persisted spans."""
        normalized_run_id = run_id.strip()
        if not normalized_run_id:
            return None
        spans = self.span_source.get_run_spans(
            self.project_name,
            normalized_run_id,
            self.span_limit,
        )
        if not spans:
            return None
        return reconstruct_run_audit(normalized_run_id, spans)


def reconstruct_run_audit(run_id: str, spans: Sequence[Mapping[str, Any]]) -> RunAudit:
    """Return one audit view reconstructed from persisted spans."""
    if not spans:
        msg = "at least one span is required"
        raise ValueError(msg)
    ordered = sorted(spans, key=span_start_sort_key)
    root = find_root_span(ordered)
    root_attributes = span_attributes(root)
    steps = tuple(audit_steps(ordered))
    diagnosis = diagnosis_from_attributes(root_attributes)
    gate_status = optional_text(root_attributes.get("gate.status"))
    return RunAudit(
        run_id=run_id,
        trace_id=span_trace_id(root),
        incident_id=optional_text(root_attributes.get("incident.golden_id")),
        ticket_id=optional_text(root_attributes.get("incident.ticket_id")),
        status=run_status(root, diagnosis, gate_status),
        started_at=optional_text(root.get("start_time")),
        ended_at=optional_text(root.get("end_time")),
        alerted_service=optional_text(root_attributes.get("incident.alerted_service")),
        services_investigated=services_from_steps(steps),
        steps=steps,
        diagnosis=diagnosis,
        confidence=optional_float(root_attributes.get("incident.confidence")),
        gate_status=gate_status,
        approval_token_present=bool(root_attributes.get("gate.approval_token_present", False)),
    )


def audit_steps(spans: Sequence[Mapping[str, Any]]) -> list[AuditStep]:
    """Return chronologically ordered tool audit steps."""
    tool_spans = [span for span in spans if span_attributes(span).get("tool.name")]
    steps: list[AuditStep] = []
    for position, span in enumerate(tool_spans, start=1):
        attributes = span_attributes(span)
        steps.append(
            AuditStep(
                step=optional_int(attributes.get("tool.step")) or position,
                span_id=span_id(span),
                tool_name=str(attributes["tool.name"]),
                arguments=json_object(attributes.get("tool.args")),
                result=json_value(attributes.get("tool.result.preview")),
                result_count=optional_int(attributes.get("tool.result_count")),
                retrieval_style=optional_text(attributes.get("retrieval_style")),
                hypothesis=optional_text(attributes.get("hypothesis_at_this_step")),
                started_at=optional_text(span.get("start_time")),
                ended_at=optional_text(span.get("end_time")),
                status=span_status(span),
            )
        )
    return sorted(steps, key=lambda step: step.step)


def find_root_span(spans: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """Return the root span, preferring a span without a parent."""
    for span in spans:
        if not span.get("parent_id"):
            return span
    return spans[0]


def span_attributes(span: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return normalized span attributes."""
    attributes = span.get("attributes", {})
    return attributes if isinstance(attributes, Mapping) else {}


def span_run_id(span: Mapping[str, Any]) -> str | None:
    """Return the incident run identifier stored on a span."""
    return optional_text(span_attributes(span).get(RUN_ID_ATTRIBUTE))


def span_trace_id(span: Mapping[str, Any]) -> str | None:
    """Return a trace identifier from supported Phoenix span shapes."""
    context = span.get("context")
    if isinstance(context, Mapping):
        return optional_text(context.get("trace_id"))
    return optional_text(span.get("trace_id"))


def span_id(span: Mapping[str, Any]) -> str | None:
    """Return a span identifier from supported Phoenix span shapes."""
    context = span.get("context")
    if isinstance(context, Mapping):
        return optional_text(context.get("span_id"))
    return optional_text(span.get("span_id") or span.get("id"))


def span_status(span: Mapping[str, Any]) -> str | None:
    """Return a normalized span status."""
    status = span.get("status")
    if isinstance(status, Mapping):
        return optional_text(status.get("status_code"))
    return optional_text(span.get("status_code") or status)


def diagnosis_from_attributes(attributes: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the final diagnosis recorded on a root span."""
    output = json_value(attributes.get("output.value"))
    if isinstance(output, dict):
        return output
    root_cause = optional_text(attributes.get("incident.root_cause"))
    if root_cause is None:
        return None
    diagnosis: dict[str, Any] = {"root_cause": root_cause}
    causal_chain = json_value(attributes.get("incident.causal_chain"))
    if isinstance(causal_chain, list):
        diagnosis["causal_chain"] = causal_chain
    elif isinstance(causal_chain, str):
        diagnosis["causal_chain"] = [item.strip() for item in causal_chain.split("->")]
    return diagnosis


def run_status(
    root: Mapping[str, Any],
    diagnosis: dict[str, Any] | None,
    gate_status: str | None,
) -> str:
    """Return the externally visible run status."""
    if gate_status == "auto_write":
        return "awaiting_approval"
    if gate_status == "escalate":
        return "escalated"
    if diagnosis is not None and root.get("end_time"):
        return "completed"
    return "running"


def services_from_steps(steps: Sequence[AuditStep]) -> tuple[str, ...]:
    """Return unique services in first-seen order."""
    services: list[str] = []
    for step in steps:
        service = step.arguments.get("service") or step.arguments.get("name_or_id")
        if isinstance(service, str) and service not in services:
            services.append(service)
    return tuple(services)


def json_object(value: Any) -> dict[str, Any]:
    """Return a decoded JSON object or an empty object."""
    decoded = json_value(value)
    return decoded if isinstance(decoded, dict) else {}


def json_value(value: Any) -> Any:
    """Decode JSON strings while preserving non-JSON values."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def optional_text(value: Any) -> str | None:
    """Return non-empty text when available."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def optional_int(value: Any) -> int | None:
    """Return an integer when coercion succeeds."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def optional_float(value: Any) -> float | None:
    """Return a float when coercion succeeds."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def span_start_sort_key(span: Mapping[str, Any]) -> str:
    """Return a stable chronological sort key."""
    return optional_text(span.get("start_time")) or ""
