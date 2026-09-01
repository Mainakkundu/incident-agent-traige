"""Typed client protocols for external systems."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Sequence, runtime_checkable

from src.config import LogLevel


@dataclass(frozen=True, slots=True)
class Ticket:
    """Incident ticket read from ITSM."""

    ticket_id: str
    title: str
    description: str
    service: str
    status: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ConfigurationItem:
    """Configuration item read from a CMDB."""

    ci_id: str
    name: str
    item_type: str
    description: str | None


@dataclass(frozen=True, slots=True)
class Dependency:
    """One dependency relation from a CMDB graph."""

    source: ConfigurationItem
    target: ConfigurationItem
    relation_type: str


@dataclass(frozen=True, slots=True)
class LogEntry:
    """One structured log row."""

    timestamp: datetime
    service: str
    level: LogLevel
    message: str


@dataclass(frozen=True, slots=True)
class ErrorRate:
    """Error-rate result for one service and window."""

    service: str
    window_start: datetime
    window_end: datetime
    total_count: int
    error_count: int
    rate: float


@dataclass(frozen=True, slots=True)
class Deploy:
    """One deploy event."""

    service: str
    version: str
    deployed_at: datetime
    actor: str | None
    change_id: str | None


@dataclass(frozen=True, slots=True)
class MetricPoint:
    """One metric sample."""

    name: str
    service: str | None
    timestamp: datetime
    value: float
    unit: str | None


@dataclass(frozen=True, slots=True)
class SimilarIncident:
    """Past incident returned by semantic search."""

    incident_id: str
    title: str
    signature: str
    root_cause: str
    resolution: str
    service: str
    occurred_at: datetime
    score: float


@dataclass(frozen=True, slots=True)
class Runbook:
    """Runbook returned by semantic search."""

    runbook_id: str
    title: str
    body: str
    score: float


@dataclass(frozen=True, slots=True)
class TicketWriteResult:
    """Result of an ITSM write."""

    ticket_id: str
    status: str
    written: bool
    message: str


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Create embeddings for semantic search queries."""

    def embed_query(self, text: str) -> Sequence[float]:
        """Return one embedding vector for query text."""
        ...


@runtime_checkable
class TicketReader(Protocol):
    """Read incident tickets from ITSM."""

    def get_ticket(self, ticket_id: str) -> Ticket:
        """Return one incident ticket."""
        ...


@runtime_checkable
class TicketWriter(Protocol):
    """Write incident diagnoses to ITSM."""

    def update_ticket(
        self,
        ticket_id: str,
        diagnosis: str,
        evidence: Sequence[str],
        confidence: float,
        approval_token: str,
    ) -> TicketWriteResult:
        """Write a diagnosis to one ticket."""
        ...

    def close_ticket(
        self,
        ticket_id: str,
        reason: str,
        approval_token: str,
    ) -> TicketWriteResult:
        """Close one ticket."""
        ...


@runtime_checkable
class CMDBReader(Protocol):
    """Read configuration items and dependency graph data."""

    def get_ci(self, name_or_id: str) -> ConfigurationItem:
        """Return one configuration item."""
        ...

    def get_ci_dependencies(self, name_or_id: str) -> Sequence[Dependency]:
        """Return direct dependencies for one configuration item."""
        ...


@runtime_checkable
class LogReader(Protocol):
    """Read structured logs."""

    def search_logs(
        self,
        service: str,
        window_start: datetime,
        window_end: datetime,
        level: LogLevel | None = None,
        keyword: str | None = None,
        limit: int | None = None,
    ) -> Sequence[LogEntry]:
        """Return logs matching the requested service and window."""
        ...

    def get_error_rate(
        self,
        service: str,
        window_start: datetime,
        window_end: datetime,
    ) -> ErrorRate:
        """Return an error rate for one service and window."""
        ...


@runtime_checkable
class DeployReader(Protocol):
    """Read deploy history."""

    def get_recent_deploys(
        self,
        service: str,
        since: datetime,
    ) -> Sequence[Deploy]:
        """Return deploys for one service since a timestamp."""
        ...


@runtime_checkable
class MetricReader(Protocol):
    """Read service metrics."""

    def get_metric(
        self,
        name: str,
        window_start: datetime,
        window_end: datetime,
        service: str | None = None,
    ) -> Sequence[MetricPoint]:
        """Return samples for one metric and window."""
        ...


@runtime_checkable
class IncidentSearcher(Protocol):
    """Search historical incidents semantically."""

    def get_similar_incidents(
        self,
        signature: str,
        limit: int | None = None,
    ) -> Sequence[SimilarIncident]:
        """Return incidents similar to a failure signature."""
        ...


@runtime_checkable
class RunbookSearcher(Protocol):
    """Search runbooks semantically."""

    def search_runbooks(
        self,
        query: str,
        limit: int | None = None,
    ) -> Sequence[Runbook]:
        """Return runbooks relevant to a query."""
        ...
