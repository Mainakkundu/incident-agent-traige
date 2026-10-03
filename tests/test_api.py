from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from src.api import create_audit_app
from src.audit import RunAudit


class ApiTests(unittest.TestCase):
    def test_get_run_returns_persisted_audit(self) -> None:
        reader = FakeRunAuditReader(sample_audit())
        client = TestClient(create_audit_app(reader))

        response = client.get("/runs/run-123")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["run_id"], "run-123")
        self.assertEqual(response.json()["status"], "completed")
        self.assertEqual(reader.requested_run_ids, ["run-123"])

    def test_get_run_returns_404_for_unknown_run(self) -> None:
        client = TestClient(create_audit_app(FakeRunAuditReader(None)))

        response = client.get("/runs/missing")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "run not found"})


class FakeRunAuditReader:
    def __init__(self, audit: RunAudit | None) -> None:
        self.audit = audit
        self.requested_run_ids: list[str] = []

    def get_run(self, run_id: str) -> RunAudit | None:
        self.requested_run_ids.append(run_id)
        return self.audit


def sample_audit() -> RunAudit:
    return RunAudit(
        run_id="run-123",
        trace_id="trace-123",
        incident_id="gld_001",
        ticket_id="INC-GLD-001",
        status="completed",
        started_at="2026-09-18T10:00:00Z",
        ended_at="2026-09-18T10:00:01Z",
        alerted_service="payment-api",
        services_investigated=("payment-api",),
        steps=(),
        diagnosis={"root_cause": "postgres-main"},
        confidence=0.87,
        gate_status="auto_write",
        approval_token_present=True,
    )


if __name__ == "__main__":
    unittest.main()
