from __future__ import annotations

import unittest

from scripts.groq_phoenix_smoke import groq_sdk_base_url, require_groq_api_key
from tests.test_mcp_observability import make_settings


class GroqPhoenixSmokeTests(unittest.TestCase):
    def test_require_groq_api_key_rejects_missing_key(self) -> None:
        settings = make_settings()

        with self.assertRaises(ValueError):
            require_groq_api_key(settings)

    def test_require_groq_api_key_accepts_real_value_shape(self) -> None:
        settings = make_settings_with_key("test-key")

        require_groq_api_key(settings)

    def test_groq_sdk_base_url_removes_openai_compatible_path(self) -> None:
        base_url = groq_sdk_base_url("https://api.groq.com/openai/v1")

        self.assertEqual(base_url, "https://api.groq.com")


def make_settings_with_key(key: str):
    settings = make_settings()
    return type(settings)(
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
        groq_api_key=key,
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
        trace_sample_rate=settings.trace_sample_rate,
    )


if __name__ == "__main__":
    unittest.main()
