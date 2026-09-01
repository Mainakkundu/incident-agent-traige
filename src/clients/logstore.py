"""Postgres-backed observability and retrieval client."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Protocol, Sequence

import psycopg

from src.config import LogLevel, Settings
from src.clients.protocols import (
    Deploy,
    EmbeddingProvider,
    ErrorRate,
    LogEntry,
    MetricPoint,
    Runbook,
    SimilarIncident,
)


LOG_SEARCH_TABLE = "logs"
DEPLOYS_TABLE = "deploys"
PAST_INCIDENTS_TABLE = "past_incidents"
RUNBOOKS_TABLE = "runbooks"
DEFAULT_VECTOR_SCORE_BASE = 1.0
ERROR_RATE_METRIC_NAME = "error_rate"
ERROR_RATE_METRIC_UNIT = "ratio"


class CursorLike(Protocol):
    """Minimal DB cursor interface used by LogStoreClient."""

    def execute(self, query: str, params: Sequence[Any] | None = None) -> Any:
        """Execute one SQL statement."""
        ...

    def fetchall(self) -> list[Any]:
        """Return all rows from the last query."""
        ...

    def fetchone(self) -> Any:
        """Return one row from the last query."""
        ...


class CursorContext(Protocol):
    """Context manager returning a cursor."""

    def __enter__(self) -> CursorLike:
        """Enter the cursor context."""
        ...

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """Exit the cursor context."""
        ...


class ConnectionLike(Protocol):
    """Minimal DB connection interface used by LogStoreClient."""

    def cursor(self) -> CursorContext:
        """Return a cursor context manager."""
        ...

    def __enter__(self) -> ConnectionLike:
        """Enter the connection context."""
        ...

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """Exit the connection context."""
        ...


ConnectionFactory = Callable[[str], ConnectionLike]


class LogStoreClientError(RuntimeError):
    """Raised when logstore data is unavailable or malformed."""


class LogStoreClient:
    """Client for logs, deploys, metrics, incidents, and runbooks in Postgres."""

    def __init__(
        self,
        dsn: str,
        log_search_limit: int,
        vector_search_limit: int,
        embedding_provider: EmbeddingProvider | None = None,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self.dsn = dsn
        self.log_search_limit = log_search_limit
        self.vector_search_limit = vector_search_limit
        self.embedding_provider = embedding_provider
        self.connection_factory = connection_factory or psycopg.connect

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        embedding_provider: EmbeddingProvider | None = None,
        connection_factory: ConnectionFactory | None = None,
    ) -> LogStoreClient:
        """Create a logstore client from typed settings."""
        return cls(
            dsn=settings.postgres_dsn,
            log_search_limit=settings.log_search_limit,
            vector_search_limit=settings.vector_search_limit,
            embedding_provider=embedding_provider,
            connection_factory=connection_factory,
        )

    def search_logs(
        self,
        service: str,
        window_start: datetime,
        window_end: datetime,
        level: LogLevel | None = None,
        keyword: str | None = None,
        limit: int | None = None,
    ) -> Sequence[LogEntry]:
        """Return logs matching the requested service and window."""
        effective_limit = limit or self.log_search_limit
        where_clauses = ["service = %s", "ts >= %s", "ts <= %s"]
        params: list[Any] = [service, window_start, window_end]

        if level is not None:
            where_clauses.append("level = %s")
            params.append(level)
        if keyword:
            where_clauses.append(
                "to_tsvector('english', message) @@ plainto_tsquery('english', %s)",
            )
            params.append(keyword)

        query = (
            "SELECT ts, service, level, message "
            f"FROM {LOG_SEARCH_TABLE} "
            f"WHERE {' AND '.join(where_clauses)} "
            "ORDER BY ts ASC "
            "LIMIT %s"
        )
        params.append(effective_limit)

        rows = self._fetch_all(query, params)
        return tuple(log_entry_from_row(row) for row in rows)

    def get_error_rate(
        self,
        service: str,
        window_start: datetime,
        window_end: datetime,
    ) -> ErrorRate:
        """Return an error rate for one service and window."""
        query = (
            "SELECT count(*) AS total_count, "
            "count(*) FILTER (WHERE level = 'ERROR') AS error_count "
            f"FROM {LOG_SEARCH_TABLE} "
            "WHERE service = %s AND ts >= %s AND ts <= %s"
        )
        row = self._fetch_one(query, (service, window_start, window_end))
        total_count = int(row[0] or 0)
        error_count = int(row[1] or 0)
        rate = error_count / total_count if total_count else 0.0
        return ErrorRate(
            service=service,
            window_start=window_start,
            window_end=window_end,
            total_count=total_count,
            error_count=error_count,
            rate=rate,
        )

    def get_recent_deploys(self, service: str, since: datetime) -> Sequence[Deploy]:
        """Return deploys for one service since a timestamp."""
        query = (
            "SELECT service, version, ts, author "
            f"FROM {DEPLOYS_TABLE} "
            "WHERE service = %s AND ts >= %s "
            "ORDER BY ts DESC"
        )
        rows = self._fetch_all(query, (service, since))
        return tuple(deploy_from_row(row) for row in rows)

    def get_metric(
        self,
        name: str,
        window_start: datetime,
        window_end: datetime,
        service: str | None = None,
    ) -> Sequence[MetricPoint]:
        """Return samples for one metric and window."""
        if name != ERROR_RATE_METRIC_NAME:
            msg = f"Unsupported derived metric: {name}"
            raise LogStoreClientError(msg)
        if service is None:
            msg = "service is required for error_rate metric"
            raise LogStoreClientError(msg)

        error_rate = self.get_error_rate(service, window_start, window_end)
        return (
            MetricPoint(
                name=ERROR_RATE_METRIC_NAME,
                service=service,
                timestamp=window_end,
                value=error_rate.rate,
                unit=ERROR_RATE_METRIC_UNIT,
            ),
        )

    def get_similar_incidents(
        self,
        signature: str,
        limit: int | None = None,
    ) -> Sequence[SimilarIncident]:
        """Return incidents similar to a failure signature."""
        vector_literal = self._embed_for_pgvector(signature)
        effective_limit = limit or self.vector_search_limit
        query = (
            "SELECT id, title, signature, root_cause, resolution, service, "
            "occurred_at, %s - (embedding <=> %s::vector) AS score "
            f"FROM {PAST_INCIDENTS_TABLE} "
            "WHERE embedding IS NOT NULL "
            "ORDER BY embedding <=> %s::vector "
            "LIMIT %s"
        )
        rows = self._fetch_all(
            query,
            (
                DEFAULT_VECTOR_SCORE_BASE,
                vector_literal,
                vector_literal,
                effective_limit,
            ),
        )
        return tuple(similar_incident_from_row(row) for row in rows)

    def search_runbooks(
        self,
        query_text: str,
        limit: int | None = None,
    ) -> Sequence[Runbook]:
        """Return runbooks relevant to a query."""
        vector_literal = self._embed_for_pgvector(query_text)
        effective_limit = limit or self.vector_search_limit
        query = (
            "SELECT id, title, body, %s - (embedding <=> %s::vector) AS score "
            f"FROM {RUNBOOKS_TABLE} "
            "WHERE embedding IS NOT NULL "
            "ORDER BY embedding <=> %s::vector "
            "LIMIT %s"
        )
        rows = self._fetch_all(
            query,
            (
                DEFAULT_VECTOR_SCORE_BASE,
                vector_literal,
                vector_literal,
                effective_limit,
            ),
        )
        return tuple(runbook_from_row(row) for row in rows)

    def _fetch_all(self, query: str, params: Sequence[Any]) -> list[Any]:
        with self.connection_factory(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                return cursor.fetchall()

    def _fetch_one(self, query: str, params: Sequence[Any]) -> Any:
        with self.connection_factory(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                row = cursor.fetchone()
                if row is None:
                    msg = "Postgres query returned no row"
                    raise LogStoreClientError(msg)
                return row

    def _embed_for_pgvector(self, text: str) -> str:
        if self.embedding_provider is None:
            msg = "EmbeddingProvider is required for semantic search"
            raise LogStoreClientError(msg)
        vector = self.embedding_provider.embed_query(text)
        return format_pgvector(vector)


def log_entry_from_row(row: Sequence[Any]) -> LogEntry:
    """Map one logs row into a protocol model."""
    return LogEntry(
        timestamp=row[0],
        service=str(row[1]),
        level=to_log_level(row[2]),
        message=str(row[3]),
    )


def deploy_from_row(row: Sequence[Any]) -> Deploy:
    """Map one deploys row into a protocol model."""
    return Deploy(
        service=str(row[0]),
        version=str(row[1]),
        deployed_at=row[2],
        actor=optional_string(row[3]),
        change_id=None,
    )


def similar_incident_from_row(row: Sequence[Any]) -> SimilarIncident:
    """Map one past_incidents row into a protocol model."""
    return SimilarIncident(
        incident_id=str(row[0]),
        title=str(row[1]),
        signature=str(row[2]),
        root_cause=str(row[3]),
        resolution=str(row[4]),
        service=str(row[5]),
        occurred_at=row[6],
        score=float(row[7]),
    )


def runbook_from_row(row: Sequence[Any]) -> Runbook:
    """Map one runbooks row into a protocol model."""
    return Runbook(
        runbook_id=str(row[0]),
        title=str(row[1]),
        body=str(row[2]),
        score=float(row[3]),
    )


def to_log_level(value: Any) -> LogLevel:
    """Return a validated log level."""
    text = str(value)
    if text not in ("DEBUG", "INFO", "WARN", "ERROR"):
        msg = f"Unknown log level: {text}"
        raise LogStoreClientError(msg)
    return text


def optional_string(value: Any) -> str | None:
    """Return an optional value as a string."""
    return None if value is None else str(value)


def format_pgvector(vector: Sequence[float]) -> str:
    """Return a pgvector literal."""
    if not vector:
        msg = "Embedding vector cannot be empty"
        raise LogStoreClientError(msg)
    return "[" + ",".join(str(float(value)) for value in vector) + "]"
