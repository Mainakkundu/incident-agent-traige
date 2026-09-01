from __future__ import annotations

import inspect
import unittest
from datetime import UTC, datetime
from typing import Sequence

from src.config import LogLevel
from src.clients.protocols import (
    CMDBReader,
    ConfigurationItem,
    Dependency,
    ErrorRate,
    LogEntry,
    LogReader,
    Ticket,
    TicketReader,
    TicketWriteResult,
    TicketWriter,
)


NOW = datetime(2026, 8, 31, 9, 30, tzinfo=UTC)


class ReadOnlyITSMClient:
    def get_ticket(self, ticket_id: str) -> Ticket:
        return Ticket(
            ticket_id=ticket_id,
            title="payment-api errors",
            description="payment-api error rate is elevated",
            service="payment-api",
            status="new",
            created_at=NOW,
        )

    def get_ci(self, name_or_id: str) -> ConfigurationItem:
        return ConfigurationItem(
            ci_id="1",
            name=name_or_id,
            item_type="Computer",
            description=None,
        )

    def get_ci_dependencies(self, name_or_id: str) -> Sequence[Dependency]:
        return ()


class WritableITSMClient(ReadOnlyITSMClient):
    def update_ticket(
        self,
        ticket_id: str,
        diagnosis: str,
        evidence: Sequence[str],
        confidence: float,
        approval_token: str,
    ) -> TicketWriteResult:
        return TicketWriteResult(
            ticket_id=ticket_id,
            status="updated",
            written=bool(approval_token),
            message=diagnosis,
        )

    def close_ticket(
        self,
        ticket_id: str,
        reason: str,
        approval_token: str,
    ) -> TicketWriteResult:
        return TicketWriteResult(
            ticket_id=ticket_id,
            status="closed",
            written=bool(approval_token),
            message=reason,
        )


class LogStoreClient:
    def search_logs(
        self,
        service: str,
        window_start: datetime,
        window_end: datetime,
        level: LogLevel | None = None,
        keyword: str | None = None,
        limit: int | None = None,
    ) -> Sequence[LogEntry]:
        return ()

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
            total_count=0,
            error_count=0,
            rate=0.0,
        )


class ProtocolTests(unittest.TestCase):
    def test_read_interfaces_are_separate_from_write_interface(self) -> None:
        read_only = ReadOnlyITSMClient()

        self.assertIsInstance(read_only, TicketReader)
        self.assertIsInstance(read_only, CMDBReader)
        self.assertNotIsInstance(read_only, TicketWriter)

    def test_writable_client_can_satisfy_read_and_write_interfaces(self) -> None:
        writable = WritableITSMClient()

        self.assertIsInstance(writable, TicketReader)
        self.assertIsInstance(writable, CMDBReader)
        self.assertIsInstance(writable, TicketWriter)

    def test_ticket_writer_methods_require_approval_token(self) -> None:
        update_signature = inspect.signature(TicketWriter.update_ticket)
        close_signature = inspect.signature(TicketWriter.close_ticket)

        self.assertIn("approval_token", update_signature.parameters)
        self.assertIn("approval_token", close_signature.parameters)

    def test_log_reader_contract_has_exact_windowed_log_search(self) -> None:
        log_reader = LogStoreClient()
        search_signature = inspect.signature(LogReader.search_logs)

        self.assertIsInstance(log_reader, LogReader)
        self.assertIn("service", search_signature.parameters)
        self.assertIn("window_start", search_signature.parameters)
        self.assertIn("window_end", search_signature.parameters)
        self.assertIn("keyword", search_signature.parameters)


if __name__ == "__main__":
    unittest.main()
