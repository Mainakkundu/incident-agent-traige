"""Read-only HTTP surface for incident run audits."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException

from src.audit import PhoenixRunAuditReader, RunAuditReader
from src.config import Settings, load_settings


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


def create_audit_app(reader: RunAuditReader) -> FastAPI:
    """Create the Phase 4 read-only run-audit application."""
    app = FastAPI(title="Incident Triage Agent")
    app.add_api_route(
        "/runs/{run_id}",
        GetRunEndpoint(reader),
        methods=["GET"],
        name="get_run",
    )
    return app


def create_default_audit_app(settings: Settings | None = None) -> FastAPI:
    """Create the run-audit application backed by Phoenix."""
    effective_settings = settings or load_settings()
    return create_audit_app(PhoenixRunAuditReader.from_settings(effective_settings))
