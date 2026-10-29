from __future__ import annotations

import unittest
from time import perf_counter

from fastapi.testclient import TestClient

from src.api import create_audit_app, create_incident_app
from src.audit import RunAudit
from src.ingestion import IncidentAlert, InMemoryRunRegistry


class ApiTests(unittest.TestCase):
    def test_health_is_dependency_free(self) -> None:
        client = TestClient(create_audit_app(FakeRunAuditReader(None)))

        response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

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

    def test_webhook_returns_202_and_deduplicates_retries(self) -> None:
        registry = InMemoryRunRegistry()
        dispatcher = RecordingDispatcher()
        client = TestClient(
            create_incident_app(FakeRunAuditReader(None), registry, dispatcher)
        )
        payload = sample_alertmanager_payload()

        first = client.post("/webhooks/incident", json=payload)
        retry = client.post("/webhooks/incident", json=payload)

        self.assertEqual(first.status_code, 202)
        self.assertEqual(retry.status_code, 202)
        self.assertEqual(first.json()["run_id"], retry.json()["run_id"])
        self.assertFalse(first.json()["duplicate"])
        self.assertTrue(retry.json()["duplicate"])
        self.assertEqual(len(dispatcher.enqueued), 1)

    def test_webhook_returns_within_200_milliseconds(self) -> None:
        client = TestClient(
            create_incident_app(
                FakeRunAuditReader(None),
                InMemoryRunRegistry(),
                RecordingDispatcher(),
            )
        )

        started = perf_counter()
        response = client.post("/webhooks/incident", json=sample_alertmanager_payload())
        elapsed_ms = (perf_counter() - started) * 1000

        self.assertEqual(response.status_code, 202)
        self.assertLess(elapsed_ms, 200)

    def test_webhook_rejects_malformed_alert(self) -> None:
        client = TestClient(
            create_incident_app(
                FakeRunAuditReader(None),
                InMemoryRunRegistry(),
                RecordingDispatcher(),
            )
        )

        response = client.post("/webhooks/incident", json={"alerts": []})

        self.assertEqual(response.status_code, 422)

    def test_approval_accepts_known_run_and_rejects_unknown_run(self) -> None:
        registry = InMemoryRunRegistry()
        reservation = registry.reserve(sample_incident_alert())
        client = TestClient(
            create_incident_app(
                FakeRunAuditReader(None),
                registry,
                RecordingDispatcher(),
            )
        )

        accepted = client.post(
            f"/runs/{reservation.run_id}/approve",
            json={"approver": "on-call@example.com"},
        )
        missing = client.post(
            "/runs/missing/approve",
            json={"approver": "on-call@example.com"},
        )

        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(
            registry.approver_for(reservation.run_id),
            "on-call@example.com",
        )


class FakeRunAuditReader:
    def __init__(self, audit: RunAudit | None) -> None:
        self.audit = audit
        self.requested_run_ids: list[str] = []

    def get_run(self, run_id: str) -> RunAudit | None:
        self.requested_run_ids.append(run_id)
        return self.audit


class RecordingDispatcher:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, IncidentAlert]] = []

    def enqueue(self, run_id: str, alert: IncidentAlert) -> None:
        self.enqueued.append((run_id, alert))


def sample_alertmanager_payload() -> dict[str, object]:
    return {
        "alerts": [
            {
                "labels": {
                    "service": "payment-api",
                    "alertname": "HighErrorRate",
                },
                "annotations": {"value": "12%", "baseline": "0.3%"},
                "startsAt": "2026-10-28T01:00:00Z",
            }
        ]
    }


def sample_incident_alert() -> IncidentAlert:
    return IncidentAlert(
        service="payment-api",
        condition="HighErrorRate",
        value="12%",
        baseline="0.3%",
        starts_at="2026-10-28T01:00:00Z",
    )


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
