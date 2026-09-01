from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import Sequence

from src.clients.protocols import (
    ConfigurationItem,
    Dependency,
    Runbook,
    SimilarIncident,
    Ticket,
    TicketWriteResult,
)
from src.mcp.itsm import ITSMTools


CREATED_AT = datetime(2026, 8, 31, 9, 30, tzinfo=UTC)


class ITSMToolsTests(unittest.TestCase):
    def test_get_ticket_serializes_ticket(self) -> None:
        client = FakeITSMClient()
        tools = ITSMTools(client, client, client, client, client)

        result = tools.get_ticket("77")

        self.assertEqual(result["ticket"]["ticket_id"], "77")
        self.assertEqual(result["ticket"]["service"], "payment-api")

    def test_get_ci_serializes_configuration_item(self) -> None:
        client = FakeITSMClient()
        tools = ITSMTools(client, client, client, client, client)

        result = tools.get_ci("payment-api")

        self.assertEqual(result["ci"]["name"], "payment-api")
        self.assertEqual(client.get_ci_call, "payment-api")

    def test_get_ci_dependencies_serializes_graph_edges(self) -> None:
        client = FakeITSMClient()
        tools = ITSMTools(client, client, client, client, client)

        result = tools.get_ci_dependencies("payment-api")

        dependencies = result["dependencies"]
        self.assertEqual(result["retrieval_style"], "graph")
        self.assertEqual(dependencies[0]["source"]["name"], "payment-api")
        self.assertEqual(dependencies[0]["target"]["name"], "auth-service")

    def test_get_similar_incidents_serializes_vector_results(self) -> None:
        client = FakeITSMClient()
        tools = ITSMTools(client, client, client, client, client)

        result = tools.get_similar_incidents("postgres max connections", limit=2)

        self.assertEqual(result["retrieval_style"], "vector")
        self.assertEqual(result["incidents"][0]["incident_id"], "INC-3902")
        self.assertEqual(client.get_similar_incidents_call["limit"], 2)

    def test_search_runbooks_serializes_vector_results(self) -> None:
        client = FakeITSMClient()
        tools = ITSMTools(client, client, client, client, client)

        result = tools.search_runbooks("connection pool exhausted", limit=3)

        self.assertEqual(result["retrieval_style"], "vector")
        self.assertEqual(result["runbooks"][0]["runbook_id"], "01")
        self.assertEqual(client.search_runbooks_call["limit"], 3)

    def test_update_ticket_rejects_missing_approval_token(self) -> None:
        client = FakeITSMClient()
        tools = ITSMTools(client, client, client, client, client)

        with self.assertRaises(PermissionError):
            tools.update_ticket("77", "postgres-main failed", (), 0.9, "")

        self.assertFalse(client.update_ticket_called)

    def test_update_ticket_writes_with_approval_token(self) -> None:
        client = FakeITSMClient()
        tools = ITSMTools(client, client, client, client, client)

        result = tools.update_ticket(
            ticket_id="77",
            diagnosis="postgres-main hit max_connections",
            evidence=("payment-api timed out to auth-service",),
            confidence=0.87,
            approval_token="approved",
        )

        self.assertTrue(result["result"]["written"])
        self.assertTrue(client.update_ticket_called)

    def test_close_ticket_rejects_missing_approval_token(self) -> None:
        client = FakeITSMClient()
        tools = ITSMTools(client, client, client, client, client)

        with self.assertRaises(PermissionError):
            tools.close_ticket("77", "resolved", "")

        self.assertFalse(client.close_ticket_called)

    def test_close_ticket_writes_with_approval_token(self) -> None:
        client = FakeITSMClient()
        tools = ITSMTools(client, client, client, client, client)

        result = tools.close_ticket("77", "resolved", "approved")

        self.assertEqual(result["result"]["status"], "closed")
        self.assertTrue(client.close_ticket_called)


class FakeITSMClient:
    def __init__(self) -> None:
        self.get_ci_call = ""
        self.get_similar_incidents_call: dict[str, object] = {}
        self.search_runbooks_call: dict[str, object] = {}
        self.update_ticket_called = False
        self.close_ticket_called = False

    def get_ticket(self, ticket_id: str) -> Ticket:
        return Ticket(
            ticket_id=ticket_id,
            title="payment-api elevated errors",
            description="payment-api error rate is 12%",
            service="payment-api",
            status="open",
            created_at=CREATED_AT,
        )

    def get_ci(self, name_or_id: str) -> ConfigurationItem:
        self.get_ci_call = name_or_id
        return configuration_item("3", "payment-api")

    def get_ci_dependencies(self, name_or_id: str) -> tuple[Dependency, ...]:
        return (
            Dependency(
                source=configuration_item("3", "payment-api"),
                target=configuration_item("7", "auth-service"),
                relation_type="depends_on",
            ),
        )

    def get_similar_incidents(
        self,
        signature: str,
        limit: int | None = None,
    ) -> tuple[SimilarIncident, ...]:
        self.get_similar_incidents_call = {"signature": signature, "limit": limit}
        return (
            SimilarIncident(
                incident_id="INC-3902",
                title="Postgres connection limit reached",
                signature=signature,
                root_cause="postgres-main hit max_connections",
                resolution="released idle connections",
                service="postgres-main",
                occurred_at=CREATED_AT,
                score=0.91,
            ),
        )

    def search_runbooks(
        self,
        query: str,
        limit: int | None = None,
    ) -> tuple[Runbook, ...]:
        self.search_runbooks_call = {"query": query, "limit": limit}
        return (
            Runbook(
                runbook_id="01",
                title="RB-01 - Postgres Connection Pressure During Checkout",
                body="Check connection pressure before raising max_connections.",
                score=0.88,
            ),
        )

    def update_ticket(
        self,
        ticket_id: str,
        diagnosis: str,
        evidence: Sequence[str],
        confidence: float,
        approval_token: str,
    ) -> TicketWriteResult:
        self.update_ticket_called = True
        return TicketWriteResult(
            ticket_id=ticket_id,
            status="updated",
            written=True,
            message="ticket followup created",
        )

    def close_ticket(
        self,
        ticket_id: str,
        reason: str,
        approval_token: str,
    ) -> TicketWriteResult:
        self.close_ticket_called = True
        return TicketWriteResult(
            ticket_id=ticket_id,
            status="closed",
            written=True,
            message="ticket marked solved",
        )


def configuration_item(ci_id: str, name: str) -> ConfigurationItem:
    return ConfigurationItem(
        ci_id=ci_id,
        name=name,
        item_type="Computer",
        description=None,
    )


if __name__ == "__main__":
    unittest.main()
