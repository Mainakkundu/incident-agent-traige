"""Load runbooks and embeddings into Postgres/pgvector.

Run: python -m scripts.seed_runbooks
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import psycopg

from src.config import PROJECT_ROOT, load_settings
from src.clients.protocols import EmbeddingProvider
from src.embeddings import HuggingFaceEmbeddingProvider


RUNBOOK_DIR = PROJECT_ROOT / "runbooks"


@dataclass(frozen=True, slots=True)
class RunbookDocument:
    """Runbook parsed from a Markdown file."""

    runbook_id: str
    title: str
    body: str


def load_runbook_documents(directory: Path = RUNBOOK_DIR) -> tuple[RunbookDocument, ...]:
    """Return runbook documents from Markdown files."""
    documents: list[RunbookDocument] = []
    for path in sorted(directory.glob("RB-*.md")):
        documents.append(parse_runbook(path))
    return tuple(documents)


def parse_runbook(path: Path) -> RunbookDocument:
    """Parse one Markdown runbook."""
    body = path.read_text(encoding="utf-8").strip()
    title = parse_title(body, path)
    return RunbookDocument(
        runbook_id=path.name.split("-", 2)[1],
        title=title,
        body=body,
    )


def parse_title(body: str, path: Path) -> str:
    """Return the first Markdown heading from a runbook."""
    for line in body.splitlines():
        if line.startswith("# "):
            return line.removeprefix("# ").strip()
    msg = f"Runbook has no H1 title: {path}"
    raise ValueError(msg)


def seed_runbooks() -> None:
    """Write runbooks and embeddings to Postgres."""
    settings = load_settings()
    embedding_provider = HuggingFaceEmbeddingProvider(settings.embedding_model)
    documents = load_runbook_documents()

    with psycopg.connect(settings.postgres_dsn) as connection:
        with connection.cursor() as cursor:
            reset_embedding_columns(cursor, settings.embedding_dimensions)
            cursor.execute("TRUNCATE runbooks")
            cursor.executemany(
                """INSERT INTO runbooks (id, title, body, embedding)
                   VALUES (%s, %s, %s, %s::vector)""",
                runbook_rows(documents, embedding_provider),
            )
            cursor.execute(
                """UPDATE past_incidents
                   SET embedding = %s::vector
                   WHERE embedding IS NULL""",
                (zero_vector(settings.embedding_dimensions),),
            )
            cursor.execute(
                """SELECT id, signature, root_cause, resolution
                   FROM past_incidents
                   ORDER BY id""",
            )
            past_incident_rows = cursor.fetchall()
            cursor.executemany(
                "UPDATE past_incidents SET embedding = %s::vector WHERE id = %s",
                past_incident_embedding_rows(past_incident_rows, embedding_provider),
            )
        connection.commit()

    print(f"loaded {len(documents)} runbooks")
    print(f"embedded {len(documents)} runbooks")
    print(f"embedded {len(past_incident_rows)} past incidents")


def runbook_rows(
    documents: Sequence[RunbookDocument],
    embedding_provider: EmbeddingProvider,
) -> list[tuple[str, str, str, str]]:
    """Return database rows for runbook insertion."""
    rows: list[tuple[str, str, str, str]] = []
    for document in documents:
        embedding = embedding_provider.embed_query(
            f"{document.title}\n\n{document.body}",
        )
        rows.append(
            (
                document.runbook_id,
                document.title,
                document.body,
                format_vector(embedding),
            ),
        )
    return rows


def reset_embedding_columns(cursor: object, dimensions: int) -> None:
    """Reset pgvector columns to the configured embedding dimensions."""
    execute = getattr(cursor, "execute")
    execute("UPDATE past_incidents SET embedding = NULL")
    execute(
        f"ALTER TABLE runbooks ALTER COLUMN embedding TYPE vector({dimensions}) "
        "USING NULL",
    )
    execute(
        f"ALTER TABLE past_incidents ALTER COLUMN embedding TYPE vector({dimensions}) "
        "USING NULL",
    )


def past_incident_embedding_rows(
    rows: Sequence[Sequence[object]],
    embedding_provider: EmbeddingProvider,
) -> list[tuple[str, str]]:
    """Return database rows for past incident embedding updates."""
    updates: list[tuple[str, str]] = []
    for row in rows:
        incident_id = str(row[0])
        searchable_text = "\n".join(str(value) for value in row[1:] if value)
        embedding = embedding_provider.embed_query(searchable_text)
        updates.append((format_vector(embedding), incident_id))
    return updates


def zero_vector(dimensions: int) -> str:
    """Return a zero vector literal."""
    return "[" + ",".join("0.0" for _ in range(dimensions)) + "]"


def format_vector(values: Sequence[float]) -> str:
    """Return a pgvector literal."""
    return "[" + ",".join(str(value) for value in values) + "]"


if __name__ == "__main__":
    try:
        seed_runbooks()
    except ValueError as exc:
        sys.exit(str(exc))
