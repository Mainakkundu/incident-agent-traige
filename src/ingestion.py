"""Incident ingestion, idempotency, and background-dispatch contracts."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol


RunHandler = Callable[[str, "IncidentAlert"], None]


@dataclass(frozen=True, slots=True)
class IncidentAlert:
    """Normalized alert accepted from Alertmanager."""

    service: str
    condition: str
    value: str
    baseline: str
    starts_at: str | None = None
    ticket_id: str | None = None


@dataclass(frozen=True, slots=True)
class RunReservation:
    """Stable run identity for an alert fingerprint."""

    run_id: str
    fingerprint: str
    created: bool


class IncidentDispatcher(Protocol):
    """Queue boundary used by HTTP ingestion."""

    def enqueue(self, run_id: str, alert: IncidentAlert) -> None:
        """Schedule one incident investigation."""
        ...


class RunRegistry(Protocol):
    """Idempotency and approval state required by the API."""

    def reserve(self, alert: IncidentAlert) -> RunReservation:
        """Return the existing or newly allocated run for an alert."""
        ...

    def approve(self, run_id: str, approver: str) -> bool:
        """Record approval for a known run."""
        ...


class InMemoryRunRegistry:
    """Thread-safe local registry used by the runnable demo and tests."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._run_ids_by_fingerprint: dict[str, str] = {}
        self._known_run_ids: set[str] = set()
        self._approvers_by_run_id: dict[str, str] = {}

    def reserve(self, alert: IncidentAlert) -> RunReservation:
        """Return one stable run ID per normalized alert fingerprint."""
        fingerprint = alert_fingerprint(alert)
        with self._lock:
            existing = self._run_ids_by_fingerprint.get(fingerprint)
            if existing is not None:
                return RunReservation(existing, fingerprint, False)
            run_id = str(uuid.uuid4())
            self._run_ids_by_fingerprint[fingerprint] = run_id
            self._known_run_ids.add(run_id)
            return RunReservation(run_id, fingerprint, True)

    def approve(self, run_id: str, approver: str) -> bool:
        """Record an approver for a known run."""
        with self._lock:
            if run_id not in self._known_run_ids:
                return False
            self._approvers_by_run_id[run_id] = approver
            return True

    def approver_for(self, run_id: str) -> str | None:
        """Return the recorded approver for test and audit inspection."""
        with self._lock:
            return self._approvers_by_run_id.get(run_id)


class ThreadPoolIncidentDispatcher:
    """Bounded background dispatcher for the local single-process demo."""

    def __init__(self, handler: RunHandler, max_workers: int = 1) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self._handler = handler
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="incident-triage",
        )

    def enqueue(self, run_id: str, alert: IncidentAlert) -> None:
        """Submit work without blocking the webhook response."""
        self._executor.submit(self._handler, run_id, alert)

    def shutdown(self, wait: bool = True) -> None:
        """Release worker threads during application shutdown."""
        self._executor.shutdown(wait=wait)


def alert_fingerprint(alert: IncidentAlert) -> str:
    """Return a deterministic fingerprint for retry deduplication."""
    canonical = json.dumps(
        {
            "baseline": alert.baseline,
            "condition": alert.condition,
            "service": alert.service,
            "starts_at": alert.starts_at,
            "ticket_id": alert.ticket_id,
            "value": alert.value,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def alert_from_alertmanager(payload: Mapping[str, Any]) -> IncidentAlert:
    """Normalize one Alertmanager webhook payload."""
    alerts = payload.get("alerts")
    if not isinstance(alerts, list) or not alerts:
        raise ValueError("payload must contain at least one alert")
    first = alerts[0]
    if not isinstance(first, Mapping):
        raise ValueError("alert must be an object")
    labels = first.get("labels", {})
    annotations = first.get("annotations", {})
    if not isinstance(labels, Mapping) or not isinstance(annotations, Mapping):
        raise ValueError("alert labels and annotations must be objects")
    return IncidentAlert(
        service=require_alert_text(labels, "service"),
        condition=require_alert_text(labels, "alertname"),
        value=str(annotations.get("value", "unknown")),
        baseline=str(annotations.get("baseline", "unknown")),
        starts_at=optional_text(first.get("startsAt")),
        ticket_id=optional_text(annotations.get("ticket_id")),
    )


def require_alert_text(values: Mapping[str, Any], key: str) -> str:
    """Return one required alert field."""
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"alert {key} is required")
    return value.strip()


def optional_text(value: Any) -> str | None:
    """Normalize an optional webhook text field."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None
