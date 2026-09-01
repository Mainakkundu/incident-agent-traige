from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import Any

import httpx

from src.clients.glpi import GLPIAuth, GLPIClient, GLPIClientError
from src.clients.protocols import CMDBReader, TicketReader, TicketWriter


BASE_URL = "http://glpi.test/api.php/v1"


class GLPIMock:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        method = request.method

        if path == "/api.php/v1/initSession" and method == "GET":
            return json_response(request, {"session_token": "session-1"})
        if path == "/api.php/v1/Ticket/77" and method == "GET":
            return json_response(request, ticket_body())
        if path == "/api.php/v1/Computer" and method == "GET":
            return json_response(request, computers_body())
        if path == "/api.php/v1/Computer/3" and method == "GET":
            return json_response(request, computers_body()[2])
        if path == "/api.php/v1/Computer/7" and method == "GET":
            return json_response(request, computers_body()[3])
        if path == "/api.php/v1/ImpactRelation" and method == "GET":
            return json_response(request, impact_relations_body())
        if path == "/api.php/v1/TicketFollowup" and method == "POST":
            return json_response(request, {"id": 501})
        if path == "/api.php/v1/Ticket/77" and method == "PUT":
            return json_response(request, {"id": 77})

        return json_response(request, {"error": "not found"}, status_code=404)


class GLPIClientTests(unittest.TestCase):
    def test_client_satisfies_read_and_write_protocols(self) -> None:
        client = make_client()

        self.assertIsInstance(client, TicketReader)
        self.assertIsInstance(client, CMDBReader)
        self.assertIsInstance(client, TicketWriter)

    def test_get_ticket_maps_glpi_ticket_response(self) -> None:
        client = make_client()

        ticket = client.get_ticket("77")

        self.assertEqual(ticket.ticket_id, "77")
        self.assertEqual(ticket.title, "payment-api elevated errors")
        self.assertEqual(ticket.service, "payment-api")
        self.assertEqual(ticket.created_at, datetime(2026, 8, 31, 9, 30, tzinfo=UTC))

    def test_get_ci_by_name_lists_glpi_cmdb_items(self) -> None:
        client = make_client()

        ci = client.get_ci("payment-api")

        self.assertEqual(ci.ci_id, "3")
        self.assertEqual(ci.name, "payment-api")
        self.assertEqual(ci.item_type, "Computer")

    def test_get_ci_dependencies_reads_impact_relations_from_glpi(self) -> None:
        client = make_client()

        dependencies = client.get_ci_dependencies("payment-api")

        self.assertEqual([edge.target.name for edge in dependencies], ["auth-service"])
        self.assertEqual(dependencies[0].source.name, "payment-api")

    def test_update_ticket_rejects_missing_approval_token(self) -> None:
        client = make_client()

        with self.assertRaises(PermissionError):
            client.update_ticket("77", "postgres-main failed", (), 0.9, "")

    def test_update_ticket_writes_followup_with_approval_token(self) -> None:
        mock = GLPIMock()
        client = make_client(mock)

        result = client.update_ticket(
            "77",
            "postgres-main hit max_connections",
            ("payment-api timed out to auth-service",),
            0.87,
            "approved",
        )

        self.assertTrue(result.written)
        self.assertTrue(any(req.url.path.endswith("TicketFollowup") for req in mock.requests))

    def test_close_ticket_rejects_missing_approval_token(self) -> None:
        client = make_client()

        with self.assertRaises(PermissionError):
            client.close_ticket("77", "false alarm", "")

    def test_missing_ci_raises_client_error(self) -> None:
        client = make_client()

        with self.assertRaises(GLPIClientError):
            client.get_ci("missing-service")


def make_client(mock: GLPIMock | None = None) -> GLPIClient:
    glpi_mock = mock or GLPIMock()
    transport = httpx.MockTransport(glpi_mock.handle)
    http_client = httpx.Client(transport=transport)
    return GLPIClient(
        base_url=BASE_URL,
        auth=GLPIAuth(app_token="app-token", user_token="user-token"),
        timeout_seconds=30.0,
        list_page_size=1000,
        client=http_client,
    )


def json_response(
    request: httpx.Request,
    body: Any,
    status_code: int = 200,
) -> httpx.Response:
    return httpx.Response(status_code=status_code, json=body, request=request)


def ticket_body() -> dict[str, Any]:
    return {
        "id": 77,
        "name": "payment-api elevated errors",
        "content": "payment-api error rate is 12%",
        "service": "payment-api",
        "status": 1,
        "date_creation": "2026-08-31 09:30:00",
    }


def computers_body() -> list[dict[str, Any]]:
    return [
        {"id": 1, "name": "checkout-web", "comment": "Checkout UI"},
        {"id": 2, "name": "api-gateway", "comment": "Gateway"},
        {"id": 3, "name": "payment-api", "comment": "Payment service"},
        {"id": 7, "name": "auth-service", "comment": "Auth service"},
    ]


def impact_relations_body() -> list[dict[str, Any]]:
    return [
        {
            "itemtype_source": "Computer",
            "items_id_source": 7,
            "itemtype_impacted": "Computer",
            "items_id_impacted": 3,
        }
    ]


if __name__ == "__main__":
    unittest.main()
