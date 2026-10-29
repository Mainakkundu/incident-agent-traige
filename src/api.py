"""HTTP surface for incident ingestion, approval, and run audits."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping

from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel

from src.audit import PhoenixRunAuditReader, RunAuditReader
from src.config import Settings, load_settings
from src.ingestion import (
    IncidentDispatcher,
    RunRegistry,
    alert_from_alertmanager,
)


class ApprovalRequest(BaseModel):
    """Human approval submitted for a paused run."""

    approver: str


class HealthEndpoint:
    """Dependency-free liveness endpoint for deployment platforms."""

    def __call__(self) -> dict[str, str]:
        """Return process health without probing optional integrations."""
        return {"status": "ok"}


class GetRunEndpoint:
    """Serve one run-audit lookup without module-level mutable state."""

    def __init__(self, reader: RunAuditReader) -> None:
        self.reader = reader

    def __call__(self, run_id: str) -> dict[str, Any]:
        """Return one audit response or an HTTP 404."""
        audit = self.reader.get_run(run_id)
        if audit is None:
            raise HTTPException(status_code=404, detail="run not found")
        return asdict(audit)


class IngestIncidentEndpoint:
    """Accept Alertmanager retries without starting duplicate runs."""

    def __init__(self, registry: RunRegistry, dispatcher: IncidentDispatcher) -> None:
        self.registry = registry
        self.dispatcher = dispatcher

    def __call__(self, payload: Mapping[str, Any], response: Response) -> dict[str, Any]:
        """Reserve and enqueue one normalized incident."""
        try:
            alert = alert_from_alertmanager(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        reservation = self.registry.reserve(alert)
        if reservation.created:
            self.dispatcher.enqueue(reservation.run_id, alert)
        response.status_code = status.HTTP_202_ACCEPTED
        return {
            "run_id": reservation.run_id,
            "fingerprint": reservation.fingerprint,
            "duplicate": not reservation.created,
        }


class ApproveRunEndpoint:
    """Record explicit human approval for a paused investigation."""

    def __init__(self, registry: RunRegistry) -> None:
        self.registry = registry

    def __call__(
        self,
        run_id: str,
        approval: ApprovalRequest,
        response: Response,
    ) -> dict[str, str]:
        """Accept approval for one known run."""
        if not approval.approver.strip():
            raise HTTPException(status_code=422, detail="approver is required")
        if not self.registry.approve(run_id, approval.approver.strip()):
            raise HTTPException(status_code=404, detail="run not found")
        response.status_code = status.HTTP_202_ACCEPTED
        return {"run_id": run_id, "status": "approval_accepted"}


def create_audit_app(reader: RunAuditReader, lifespan: Any | None = None) -> FastAPI:
    """Create the Phase 4 read-only run-audit application."""
    app = FastAPI(title="Incident Triage Agent", lifespan=lifespan)
    app.add_api_route("/health", HealthEndpoint(), methods=["GET"], name="health")
    app.add_api_route(
        "/runs/{run_id}",
        GetRunEndpoint(reader),
        methods=["GET"],
        name="get_run",
    )
    return app


def create_incident_app(
    reader: RunAuditReader,
    registry: RunRegistry,
    dispatcher: IncidentDispatcher,
    lifespan: Any | None = None,
) -> FastAPI:
    """Create the complete three-endpoint incident API."""
    app = create_audit_app(reader, lifespan=lifespan)
    app.add_api_route(
        "/webhooks/incident",
        IngestIncidentEndpoint(registry, dispatcher),
        methods=["POST"],
        name="ingest_incident",
        status_code=status.HTTP_202_ACCEPTED,
    )
    app.add_api_route(
        "/runs/{run_id}/approve",
        ApproveRunEndpoint(registry),
        methods=["POST"],
        name="approve_run",
        status_code=status.HTTP_202_ACCEPTED,
    )
    return app


def create_default_audit_app(settings: Settings | None = None) -> FastAPI:
    """Create the run-audit application backed by Phoenix."""
    effective_settings = settings or load_settings()
    return create_audit_app(PhoenixRunAuditReader.from_settings(effective_settings))
