from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.seed_runbooks import load_runbook_documents, parse_runbook, runbook_rows


class SeedRunbooksTests(unittest.TestCase):
    def test_load_runbook_documents_loads_all_project_runbooks(self) -> None:
        documents = load_runbook_documents()

        self.assertEqual(len(documents), 12)
        self.assertEqual(len([doc for doc in documents if doc.runbook_id < "20"]), 7)
        self.assertEqual(len([doc for doc in documents if doc.runbook_id >= "20"]), 5)

    def test_parse_runbook_uses_filename_id_and_heading_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "RB-99-example.md"
            path.write_text("# RB-99 - Example\n\nBody", encoding="utf-8")

            document = parse_runbook(path)

        self.assertEqual(document.runbook_id, "99")
        self.assertEqual(document.title, "RB-99 - Example")
        self.assertEqual(document.body, "# RB-99 - Example\n\nBody")

    def test_runbook_rows_include_pgvector_literal(self) -> None:
        documents = load_runbook_documents()
        provider = StaticEmbeddingProvider()

        rows = runbook_rows(documents[:1], provider)

        self.assertEqual(rows[0][0], "01")
        self.assertTrue(rows[0][3].startswith("["))
        self.assertTrue(rows[0][3].endswith("]"))
        self.assertEqual(len(rows[0][3].strip("[]").split(",")), 3)


class StaticEmbeddingProvider:
    def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


if __name__ == "__main__":
    unittest.main()
