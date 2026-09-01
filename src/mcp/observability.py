"""Standalone observability MCP tool functions."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Sequence

from src.clients.protocols import DeployReader, LogReader, MetricReader
from src.config import LogLevel, Settings


class ObservabilityTools:
    """Read-only observability tools backed by a logstore client."""

    def __init__(
        self,
        log_reader: LogReader,
        deploy_reader: DeployReader,
        metric_reader: MetricReader,
        settings: Settings,
    ) -> None:
        self.log_reader = log_reader
        self.deploy_reader = deploy_reader
        self.metric_reader = metric_reader
        self.settings = settings

    def search_logs(
        self,
        service: str,
        window_start: str,
        window_end: str,
        level: LogLevel | None = None,
        keyword: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Return exact, time-bounded logs for one service."""
        start = parse_datetime(window_start)
        end = parse_datetime(window_end)
        effective_limit = limit or self.settings.log_search_limit
        logs = self.log_reader.search_logs(
            service=service,
            window_start=start,
            window_end=end,
            level=level,
            keyword=keyword,
            limit=effective_limit,
        )
        return {
            "service": service,
            "window_start": window_start,
            "window_end": window_end,
            "retrieval_style": "fulltext",
            "logs": serialize_dataclass_rows(logs),
        }

    def get_error_rate(
        self,
        service: str,
        window_start: str,
        window_end: str,
    ) -> dict[str, Any]:
        """Return error rate for one service and time window."""
        start = parse_datetime(window_start)
        end = parse_datetime(window_end)
        error_rate = self.log_reader.get_error_rate(service, start, end)
        return {
            "retrieval_style": "fulltext",
            "error_rate": serialize_dataclass(error_rate),
        }

    def get_recent_deploys(
        self,
        service: str,
        reference_time: str,
        hours: int | None = None,
    ) -> dict[str, Any]:
        """Return deploys for one service before a reference time."""
        reference = parse_datetime(reference_time)
        effective_hours = hours or self.settings.recent_deploys_hours
        since = reference - timedelta(hours=effective_hours)
        deploys = self.deploy_reader.get_recent_deploys(service, since)
        return {
            "service": service,
            "since": since.isoformat(),
            "reference_time": reference_time,
            "retrieval_style": "fulltext",
            "deploys": serialize_dataclass_rows(deploys),
        }

    def get_metric(
        self,
        name: str,
        window_start: str,
        window_end: str,
        service: str | None = None,
    ) -> dict[str, Any]:
        """Return metric samples for a service and time window."""
        start = parse_datetime(window_start)
        end = parse_datetime(window_end)
        points = self.metric_reader.get_metric(name, start, end, service)
        return {
            "name": name,
            "service": service,
            "window_start": window_start,
            "window_end": window_end,
            "retrieval_style": "fulltext",
            "points": serialize_dataclass_rows(points),
        }


def parse_datetime(value: str) -> datetime:
    """Parse one ISO-8601 datetime."""
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def serialize_dataclass_rows(rows: Sequence[object]) -> list[dict[str, Any]]:
    """Serialize dataclass rows for MCP responses."""
    return [serialize_dataclass(row) for row in rows]


def serialize_dataclass(row: object) -> dict[str, Any]:
    """Serialize one dataclass row for MCP responses."""
    raw = asdict(row)
    return {key: serialize_value(value) for key, value in raw.items()}


def serialize_value(value: object) -> Any:
    """Serialize one value for MCP responses."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value
