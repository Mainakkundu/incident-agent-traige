from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import (
    DEFAULT_CONFIG_FILE,
    LOG_LEVELS,
    RETRIEVAL_STYLES,
    load_settings,
)


class SettingsTests(unittest.TestCase):
    def test_load_settings_uses_project_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_env = Path(tmpdir) / ".env"
            settings = load_settings(missing_env)

        self.assertEqual(settings.glpi_url, "http://localhost:8080/api.php/v1")
        self.assertEqual(
            settings.postgres_dsn,
            "postgresql://agent:agent@localhost:5432/incidents",
        )
        self.assertEqual(settings.agent_max_steps, 15)
        self.assertEqual(settings.auto_write_confidence, 0.8)
        self.assertEqual(settings.groq_model, "openai/gpt-oss-20b")
        self.assertEqual(settings.groq_base_url, "https://api.groq.com")
        self.assertIsNone(settings.groq_api_key)

    def test_load_settings_reads_env_file_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "\n".join(
                    (
                        "APP_ENV=test",
                        "GLPI_DB_PORT=3307",
                        "HTTP_TIMEOUT_SECONDS=12.5",
                        "AUTO_WRITE_CONFIDENCE=0.91",
                        "GROQ_API_KEY=test-secret",
                    )
                ),
                encoding="utf-8",
            )
            settings = load_settings(env_file)

        self.assertEqual(settings.environment, "test")
        self.assertEqual(settings.glpi_db_port, 3307)
        self.assertEqual(settings.http_timeout_seconds, 12.5)
        self.assertEqual(settings.auto_write_confidence, 0.91)
        self.assertEqual(settings.groq_api_key, "test-secret")

    def test_load_settings_reads_alternate_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            config_file = Path(tmpdir) / "defaults.toml"
            config_file.write_text(DEFAULT_CONFIG_FILE.read_text(encoding="utf-8"))
            config_text = config_file.read_text(encoding="utf-8").replace(
                "max_steps = 15",
                "max_steps = 9",
            )
            config_file.write_text(config_text, encoding="utf-8")

            settings = load_settings(env_file, config_file)

        self.assertEqual(settings.agent_max_steps, 9)
        self.assertEqual(
            settings.embedding_model,
            "sentence-transformers/all-mpnet-base-v2",
        )

    def test_process_environment_overrides_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text("GLPI_URL=http://from-file/api.php/v1", encoding="utf-8")

            with patch.dict(os.environ, {"GLPI_URL": "http://from-process/api.php/v1"}):
                settings = load_settings(env_file)

        self.assertEqual(settings.glpi_url, "http://from-process/api.php/v1")

    def test_invalid_environment_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text("APP_ENV=staging", encoding="utf-8")

            with self.assertRaises(ValueError):
                load_settings(env_file)

    def test_static_labels_cover_tool_retrieval_modes(self) -> None:
        self.assertEqual(LOG_LEVELS, ("DEBUG", "INFO", "WARN", "ERROR"))
        self.assertEqual(RETRIEVAL_STYLES, ("fulltext", "vector", "graph"))


if __name__ == "__main__":
    unittest.main()
