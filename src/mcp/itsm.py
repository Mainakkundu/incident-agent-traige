"""Standalone ITSM MCP tool functions."""

from __future__ import annotations

from typing import Any, Sequence

from src.clients.glpi import require_approval_token
from src.clients.protocols import (
    CMDBReader,
    IncidentSearcher,
    RunbookSearcher,
    TicketReader,
    TicketWriter,
)
from src.mcp.observability import serialize_dataclass, serialize_dataclass_rows


class ITSMTools:
    """ITSM tools backed by GLPI and semantic retrieval clients."""

    def __init__(
        self,
        ticket_reader: TicketReader,
        ticket_writer: TicketWriter,
        cmdb_reader: CMDBReader,
        incident_searcher: IncidentSearcher,
        runbook_searcher: RunbookSearcher,
    ) -> None:
        self.ticket_reader = ticket_reader
        self.ticket_writer = ticket_writer
        self.cmdb_reader = cmdb_reader
        self.incident_searcher = incident_searcher
        self.runbook_searcher = runbook_searcher

    def get_ticket(self, ticket_id: str) -> dict[str, Any]:
        """Return one incident ticket from ITSM."""
        ticket = self.ticket_reader.get_ticket(ticket_id)
        return {"ticket": serialize_dataclass(ticket)}

    def get_ci(self, name_or_id: str) -> dict[str, Any]:
        """Return one configuration item from the CMDB."""
        ci = self.cmdb_reader.get_ci(name_or_id)
        return {"ci": serialize_dataclass(ci)}

    def get_ci_dependencies(self, name_or_id: str) -> dict[str, Any]:
        """Return direct dependency edges for one configuration item."""
        dependencies = self.cmdb_reader.get_ci_dependencies(name_or_id)
        return {
            "name_or_id": name_or_id,
            "retrieval_style": "graph",
            "dependencies": serialize_dataclass_rows(dependencies),
        }

    def get_similar_incidents(
        self,
        signature: str,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Return semantically similar past incidents."""
        incidents = self.incident_searcher.get_similar_incidents(signature, limit)
        return {
            "signature": signature,
            "retrieval_style": "vector",
            "incidents": serialize_dataclass_rows(incidents),
        }

    def search_runbooks(
        self,
        query: str,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Return semantically relevant runbooks."""
        runbooks = self.runbook_searcher.search_runbooks(query, limit)
        return {
            "query": query,
            "retrieval_style": "vector",
            "runbooks": serialize_dataclass_rows(runbooks),
        }

    def update_ticket(
        self,
        ticket_id: str,
        diagnosis: str,
        evidence: Sequence[str],
        confidence: float,
        approval_token: str,
    ) -> dict[str, Any]:
        """Write a diagnosis to one ticket after approval."""
        require_approval_token(approval_token)
        result = self.ticket_writer.update_ticket(
            ticket_id=ticket_id,
            diagnosis=diagnosis,
            evidence=evidence,
            confidence=confidence,
            approval_token=approval_token,
        )
        return {"result": serialize_dataclass(result)}

    def close_ticket(
        self,
        ticket_id: str,
        reason: str,
        approval_token: str,
    ) -> dict[str, Any]:
        """Close one ticket after approval."""
        require_approval_token(approval_token)
        result = self.ticket_writer.close_ticket(
            ticket_id=ticket_id,
            reason=reason,
            approval_token=approval_token,
        )
        return {"result": serialize_dataclass(result)}
