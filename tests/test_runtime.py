from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.config import load_settings
from src.runtime import create_app


class RuntimeTests(unittest.TestCase):
    def test_runtime_uses_non_blocking_trace_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = load_settings(Path(tmpdir) / ".env")

        with (
            patch("src.runtime.configure_tracing") as configure_tracing,
            patch("src.runtime.get_tracer", return_value=MagicMock()),
            patch("src.runtime.PhoenixRunAuditReader.from_settings"),
        ):
            app = create_app(settings)

        configure_tracing.assert_called_once_with(settings, batch=True)
        app.state.incident_dispatcher.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
