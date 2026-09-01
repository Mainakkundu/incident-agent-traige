from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import Any, Sequence

from src.clients.logstore import LogStoreClient, LogStoreClientError
from src.clients.protocols import (
    DeployReader,
    EmbeddingProvider,
    IncidentSearcher,
    LogReader,
    MetricReader,
    RunbookSearcher,
)


WINDOW_START = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 8, 31, 9, 15, tzinfo=UTC)


class StaticEmbeddingProvider:
    def embed_query(self, text: str) -> Sequence[float]:
        return (0.1, 0.2, 0.3)


class FakeCursor:
    def __init__(self, rows: list[Any], one: Any | None = None) -> None:
        self.rows = rows
        self.one = one
        self.query = ""
        self.params: Sequence[Any] | None = None

    def execute(self, query: str, params: Sequence[Any] | None = None) -> None:
        self.query = query
        self.params = params

    def fetchall(self) -> list[Any]:
        return self.rows

    def fetchone(self) -> Any:
        return self.one

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        return None


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor_instance = cursor

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        return None


class FakeConnectionFactory:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor = cursor
        self.dsn: str | None = None

    def __call__(self, dsn: str) -> FakeConnection:
        self.dsn = dsn
        return FakeConnection(self.cursor)


class LogStoreClientTests(unittest.TestCase):
    def test_client_satisfies_observability_protocols(self) -> None:
        client = make_client(FakeCursor([]), StaticEmbeddingProvider())

        self.assertIsInstance(client, LogReader)
        self.assertIsInstance(client, DeployReader)
        self.assertIsInstance(client, MetricReader)
        self.assertIsInstance(client, IncidentSearcher)
        self.assertIsInstance(client, RunbookSearcher)

    def test_search_logs_uses_exact_service_window_and_fulltext_keyword(self) -> None:
        cursor = FakeCursor(
            [(WINDOW_START, "payment-api", "ERROR", "upstream auth-service timeout")],
        )
        factory = FakeConnectionFactory(cursor)
        client = make_client(cursor, connection_factory=factory)

        rows = client.search_logs(
            "payment-api",
            WINDOW_START,
            WINDOW_END,
            level="ERROR",
            keyword="auth timeout",
            limit=10,
        )

        self.assertEqual(factory.dsn, "postgresql://test")
        self.assertEqual(rows[0].message, "upstream auth-service timeout")
        self.assertIn("FROM logs", cursor.query)
        self.assertIn("service = %s", cursor.query)
        self.assertIn("ts >= %s", cursor.query)
        self.assertIn("to_tsvector", cursor.query)
        self.assertEqual(
            cursor.params,
            [
                "payment-api",
                WINDOW_START,
                WINDOW_END,
                "ERROR",
                "auth timeout",
                10,
            ],
        )

    def test_get_error_rate_computes_rate_from_counts(self) -> None:
        cursor = FakeCursor([], one=(20, 5))
        client = make_client(cursor)

        error_rate = client.get_error_rate("payment-api", WINDOW_START, WINDOW_END)

        self.assertEqual(error_rate.total_count, 20)
        self.assertEqual(error_rate.error_count, 5)
        self.assertEqual(error_rate.rate, 0.25)

    def test_get_recent_deploys_maps_deploy_rows(self) -> None:
        cursor = FakeCursor(
            [("payment-api", "v1.4.2", WINDOW_START, "mainak")],
        )
        client = make_client(cursor)

        deploys = client.get_recent_deploys("payment-api", WINDOW_START)

        self.assertEqual(deploys[0].version, "v1.4.2")
        self.assertEqual(deploys[0].actor, "mainak")
        self.assertIsNone(deploys[0].change_id)
        self.assertIn("FROM deploys", cursor.query)
        self.assertEqual(cursor.params, ("payment-api", WINDOW_START))

    def test_get_metric_derives_error_rate_from_logs(self) -> None:
        cursor = FakeCursor([], one=(20, 5))
        client = make_client(cursor)

        points = client.get_metric("error_rate", WINDOW_START, WINDOW_END, "payment-api")

        self.assertEqual(points[0].value, 0.25)
        self.assertEqual(points[0].unit, "ratio")
        self.assertIn("FROM logs", cursor.query)
        self.assertEqual(
            cursor.params,
            ("payment-api", WINDOW_START, WINDOW_END),
        )

    def test_get_metric_rejects_unknown_metric(self) -> None:
        client = make_client(FakeCursor([]))

        with self.assertRaises(LogStoreClientError):
            client.get_metric("cpu_usage", WINDOW_START, WINDOW_END, "payment-api")

    def test_get_similar_incidents_uses_pgvector_and_embedding_provider(self) -> None:
        cursor = FakeCursor(
            [
                (
                    "INC-3902",
                    "Database connection limit reached",
                    "postgres max connections",
                    "postgres-main hit max_connections",
                    "released idle connections",
                    "postgres-main",
                    WINDOW_START,
                    0.91,
                )
            ],
        )
        client = make_client(cursor, StaticEmbeddingProvider())

        incidents = client.get_similar_incidents("connection pool exhausted", limit=3)

        self.assertEqual(incidents[0].incident_id, "INC-3902")
        self.assertIn("FROM past_incidents", cursor.query)
        self.assertIn("embedding <=> %s::vector", cursor.query)
        self.assertEqual(cursor.params[1], "[0.1,0.2,0.3]")
        self.assertEqual(cursor.params[3], 3)

    def test_search_runbooks_uses_pgvector_and_embedding_provider(self) -> None:
        cursor = FakeCursor([("RB-07", "Postgres max connections", "Steps", 0.88)])
        client = make_client(cursor, StaticEmbeddingProvider())

        runbooks = client.search_runbooks("postgres max connections")

        self.assertEqual(runbooks[0].runbook_id, "RB-07")
        self.assertIn("FROM runbooks", cursor.query)
        self.assertEqual(cursor.params[1], "[0.1,0.2,0.3]")

    def test_semantic_search_requires_embedding_provider(self) -> None:
        client = make_client(FakeCursor([]))

        with self.assertRaises(LogStoreClientError):
            client.get_similar_incidents("connection pool exhausted")


def make_client(
    cursor: FakeCursor,
    embedding_provider: EmbeddingProvider | None = None,
    connection_factory: FakeConnectionFactory | None = None,
) -> LogStoreClient:
    factory = connection_factory or FakeConnectionFactory(cursor)
    return LogStoreClient(
        dsn="postgresql://test",
        log_search_limit=100,
        vector_search_limit=5,
        embedding_provider=embedding_provider,
        connection_factory=factory,
    )


if __name__ == "__main__":
    unittest.main()
