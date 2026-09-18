from __future__ import annotations

import unittest

from src.tracing import configure_tracing, shutdown_tracing
from tests.test_mcp_observability import make_settings


class TracingTests(unittest.TestCase):
    def test_configure_tracing_registers_phoenix_openinference_provider(self) -> None:
        recorder = RegisterRecorder()

        handle = configure_tracing(make_settings(), register_tracing=recorder)

        self.assertEqual(handle.project_name, "incident-triage-agent-groq-smoke")
        self.assertEqual(handle.endpoint, "http://localhost:4317")
        self.assertEqual(recorder.kwargs["project_name"], handle.project_name)
        self.assertEqual(recorder.kwargs["endpoint"], handle.endpoint)
        self.assertEqual(recorder.kwargs["protocol"], "http/protobuf")
        self.assertFalse(recorder.kwargs["batch"])
        self.assertFalse(recorder.kwargs["auto_instrument"])
        self.assertFalse(recorder.kwargs["verbose"])
        self.assertIn("sampler", recorder.kwargs)

    def test_shutdown_tracing_shutdowns_provider(self) -> None:
        recorder = RegisterRecorder()
        handle = configure_tracing(make_settings(), register_tracing=recorder)

        shutdown_tracing(handle)

        self.assertTrue(recorder.provider.shutdown_called)

    def test_configure_tracing_rejects_invalid_sample_rate(self) -> None:
        settings = make_settings()
        bad_settings = type(settings)(
            environment=settings.environment,
            glpi_url=settings.glpi_url,
            glpi_db_host=settings.glpi_db_host,
            glpi_db_port=settings.glpi_db_port,
            glpi_db_name=settings.glpi_db_name,
            glpi_db_user=settings.glpi_db_user,
            glpi_db_password=settings.glpi_db_password,
            glpi_app_token=settings.glpi_app_token,
            glpi_user_token=settings.glpi_user_token,
            glpi_list_page_size=settings.glpi_list_page_size,
            postgres_dsn=settings.postgres_dsn,
            phoenix_endpoint=settings.phoenix_endpoint,
            phoenix_project_name=settings.phoenix_project_name,
            otel_exporter_otlp_endpoint=settings.otel_exporter_otlp_endpoint,
            groq_api_key=settings.groq_api_key,
            groq_base_url=settings.groq_base_url,
            groq_model=settings.groq_model,
            http_timeout_seconds=settings.http_timeout_seconds,
            log_search_limit=settings.log_search_limit,
            vector_search_limit=settings.vector_search_limit,
            recent_deploys_hours=settings.recent_deploys_hours,
            error_rate_window_minutes=settings.error_rate_window_minutes,
            metric_window_minutes=settings.metric_window_minutes,
            embedding_dimensions=settings.embedding_dimensions,
            embedding_model=settings.embedding_model,
            agent_max_steps=settings.agent_max_steps,
            auto_write_confidence=settings.auto_write_confidence,
            approval_token_ttl_seconds=settings.approval_token_ttl_seconds,
            webhook_response_timeout_ms=settings.webhook_response_timeout_ms,
            trace_sample_rate=1.1,
        )

        with self.assertRaises(ValueError):
            configure_tracing(bad_settings, register_tracing=RegisterRecorder())


class RegisterRecorder:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] = {}
        self.provider = FakeTracerProvider()

    def __call__(self, **kwargs: object) -> FakeTracerProvider:
        self.kwargs = kwargs
        return self.provider


class FakeTracerProvider:
    def __init__(self) -> None:
        self.shutdown_called = False

    def shutdown(self) -> None:
        self.shutdown_called = True


if __name__ == "__main__":
    unittest.main()
