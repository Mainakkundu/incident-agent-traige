"""Shared state and Prometheus rendering for the toy services."""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RequestCounts:
    """Snapshot of service request outcomes."""

    ok: int
    failed: int


class ServiceRuntime:
    """Thread-safe fault switch and request counters."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fault_enabled = False
        self._ok = 0
        self._failed = 0

    def set_fault(self, enabled: bool) -> None:
        """Enable or clear the service fault."""
        with self._lock:
            self._fault_enabled = enabled

    def fault_enabled(self) -> bool:
        """Return the current fault state."""
        with self._lock:
            return self._fault_enabled

    def record(self, successful: bool) -> None:
        """Record one request result."""
        with self._lock:
            if successful:
                self._ok += 1
            else:
                self._failed += 1

    def counts(self) -> RequestCounts:
        """Return an immutable counter snapshot."""
        with self._lock:
            return RequestCounts(ok=self._ok, failed=self._failed)


def render_metrics(service: str, counts: RequestCounts) -> str:
    """Render the minimal Prometheus exposition used by alert rules."""
    metric = "toy_http_requests_total"
    return "\n".join(
        (
            "# HELP toy_http_requests_total Requests handled by a toy service.",
            "# TYPE toy_http_requests_total counter",
            f'{metric}{{service="{service}",status="ok"}} {counts.ok}',
            f'{metric}{{service="{service}",status="error"}} {counts.failed}',
            "",
        )
    )
