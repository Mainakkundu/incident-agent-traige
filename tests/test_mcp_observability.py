from __future__ import annotations

import unittest
from datetime import UTC, datetime

from src.clients.protocols import Deploy, ErrorRate, LogEntry, MetricPoint
from src.config import Settings
from src.mcp.observability import ObservabilityTools, parse_datetime


WINDOW_START = "2026-08-31T09:00:00+00:00"
WINDOW_END = "2026-08-31T09:15:00+00:00"
REFERENCE_TIME = "2026-08-31T12:00:00+00:00"


class ObservabilityToolsTests(unittest.TestCase):
    def test_search_logs_calls_log_reader_with_window_and_limit(self) -> None:
        client = FakeObservabilityClient()
        tools = ObservabilityTools(client, client, client, make_settings())

        result = tools.search_logs(
            service="payment-api",
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            level="ERROR",
            keyword="auth timeout",
        )

        self.assertEqual(result["retrieval_style"], "fulltext")
        self.assertEqual(result["logs"][0]["message"], "auth-service timeout")
        self.assertEqual(client.search_logs_call["service"], "payment-api")
        self.assertEqual(client.search_logs_call["limit"], 100)
        self.assertEqual(client.search_logs_call["keyword"], "auth timeout")

    def test_get_error_rate_serializes_counts_and_rate(self) -> None:
        client = FakeObservabilityClient()
        tools = ObservabilityTools(client, client, client, make_settings())

        result = tools.get_error_rate("payment-api", WINDOW_START, WINDOW_END)

        error_rate = result["error_rate"]
        self.assertEqual(result["retrieval_style"], "fulltext")
        self.assertEqual(error_rate["error_count"], 3)
        self.assertEqual(error_rate["total_count"], 30)
        self.assertEqual(error_rate["rate"], 0.1)

    def test_get_recent_deploys_uses_configured_window(self) -> None:
        client = FakeObservabilityClient()
        tools = ObservabilityTools(client, client, client, make_settings())

        result = tools.get_recent_deploys("payment-api", REFERENCE_TIME)

        self.assertEqual(result["deploys"][0]["version"], "v1.4.2")
        self.assertEqual(result["since"], "2026-08-28T12:00:00+00:00")
        self.assertEqual(client.get_recent_deploys_call["service"], "payment-api")

    def test_get_metric_serializes_metric_points(self) -> None:
        client = FakeObservabilityClient()
        tools = ObservabilityTools(client, client, client, make_settings())

        result = tools.get_metric("error_rate", WINDOW_START, WINDOW_END, "payment-api")

        self.assertEqual(result["points"][0]["value"], 0.1)
        self.assertEqual(result["points"][0]["unit"], "ratio")
        self.assertEqual(client.get_metric_call["name"], "error_rate")

    def test_parse_datetime_accepts_z_suffix(self) -> None:
        parsed = parse_datetime("2026-08-31T09:00:00Z")

        self.assertEqual(parsed, datetime(2026, 8, 31, 9, 0, tzinfo=UTC))


class FakeObservabilityClient:
    def __init__(self) -> None:
        self.search_logs_call: dict[str, object] = {}
        self.get_recent_deploys_call: dict[str, object] = {}
        self.get_metric_call: dict[str, object] = {}

    def search_logs(
        self,
        service: str,
        window_start: datetime,
        window_end: datetime,
        level: str | None = None,
        keyword: str | None = None,
        limit: int | None = None,
    ) -> tuple[LogEntry, ...]:
        self.search_logs_call = {
            "service": service,
            "window_start": window_start,
            "window_end": window_end,
            "level": level,
            "keyword": keyword,
            "limit": limit,
        }
        return (
            LogEntry(
                timestamp=window_start,
                service=service,
                level="ERROR",
                message="auth-service timeout",
            ),
        )

    def get_error_rate(
        self,
        service: str,
        window_start: datetime,
        window_end: datetime,
    ) -> ErrorRate:
        return ErrorRate(
            service=service,
            window_start=window_start,
            window_end=window_end,
            total_count=30,
            error_count=3,
            rate=0.1,
        )

    def get_recent_deploys(
        self,
        service: str,
        since: datetime,
    ) -> tuple[Deploy, ...]:
        self.get_recent_deploys_call = {"service": service, "since": since}
        return (
            Deploy(
                service=service,
                version="v1.4.2",
                deployed_at=since,
                actor="mainak",
                change_id=None,
            ),
        )

    def get_metric(
        self,
        name: str,
        window_start: datetime,
        window_end: datetime,
        service: str | None = None,
    ) -> tuple[MetricPoint, ...]:
        self.get_metric_call = {
            "name": name,
            "window_start": window_start,
            "window_end": window_end,
            "service": service,
        }
        return (
            MetricPoint(
                name=name,
                service=service,
                timestamp=window_end,
                value=0.1,
                unit="ratio",
            ),
        )


def make_settings() -> Settings:
    return Settings(
        environment="test",
        glpi_url="http://localhost:8080/api.php/v1",
        glpi_db_host="localhost",
        glpi_db_port=3306,
        glpi_db_name="glpi",
        glpi_db_user="glpi",
        glpi_db_password=None,
        glpi_app_token=None,
        glpi_user_token=None,
        glpi_list_page_size=1000,
        postgres_dsn="postgresql://test",
        phoenix_endpoint="http://localhost:6006",
        phoenix_project_name="incident-triage-agent-groq-smoke",
        otel_exporter_otlp_endpoint="http://localhost:4317",
        groq_api_key=None,
        groq_base_url="https://api.groq.com",
        groq_model="openai/gpt-oss-20b",
        http_timeout_seconds=30.0,
        log_search_limit=100,
        vector_search_limit=5,
        recent_deploys_hours=72,
        error_rate_window_minutes=15,
        metric_window_minutes=15,
        embedding_dimensions=768,
        embedding_model="sentence-transformers/all-mpnet-base-v2",
        agent_max_steps=15,
        auto_write_confidence=0.8,
        approval_token_ttl_seconds=900,
        webhook_response_timeout_ms=200,
        trace_sample_rate=1.0,
    )


if __name__ == "__main__":
    unittest.main()
