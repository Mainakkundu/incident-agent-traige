"""GLPI ITSM and CMDB client."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Sequence

import httpx

from src.config import Settings
from src.clients.protocols import (
    ConfigurationItem,
    Dependency,
    Ticket,
    TicketWriteResult,
)


COMPUTER_ITEM_TYPE = "Computer"
DEFAULT_RELATION_TYPE = "depends_on"
GLPI_STATUS_SOLVED = 5


class GLPIClientError(RuntimeError):
    """Raised when GLPI returns unexpected data."""


@dataclass(frozen=True, slots=True)
class GLPIAuth:
    """Credentials required for GLPI API calls."""

    app_token: str
    user_token: str


class GLPIClient:
    """HTTP client for GLPI tickets and CMDB relationships."""

    def __init__(
        self,
        base_url: str,
        auth: GLPIAuth,
        timeout_seconds: float,
        list_page_size: int,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.timeout_seconds = timeout_seconds
        self.list_page_size = list_page_size
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self.session_token: str | None = None

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        client: httpx.Client | None = None,
    ) -> GLPIClient:
        """Create a GLPI client from typed settings."""
        if not settings.glpi_app_token or not settings.glpi_user_token:
            msg = "GLPI_APP_TOKEN and GLPI_USER_TOKEN are required"
            raise ValueError(msg)

        return cls(
            base_url=settings.glpi_url,
            auth=GLPIAuth(
                app_token=settings.glpi_app_token,
                user_token=settings.glpi_user_token,
            ),
            timeout_seconds=settings.http_timeout_seconds,
            list_page_size=settings.glpi_list_page_size,
            client=client,
        )

    def init_session(self) -> str:
        """Start a GLPI API session."""
        response = self.client.get(
            self._url("initSession"),
            headers={
                "Authorization": f"user_token {self.auth.user_token}",
                "App-Token": self.auth.app_token,
            },
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or not isinstance(body.get("session_token"), str):
            msg = "GLPI initSession response did not contain session_token"
            raise GLPIClientError(msg)
        self.session_token = body["session_token"]
        return self.session_token

    def kill_session(self) -> None:
        """Close the active GLPI API session."""
        if not self.session_token:
            return
        response = self.client.get(self._url("killSession"), headers=self._headers())
        response.raise_for_status()
        self.session_token = None

    def get_ticket(self, ticket_id: str) -> Ticket:
        """Return one incident ticket."""
        body = self._get_item("Ticket", ticket_id)
        return ticket_from_glpi(body)

    def get_ci(self, name_or_id: str) -> ConfigurationItem:
        """Return one CMDB configuration item."""
        if name_or_id.isdigit():
            return configuration_item_from_glpi(
                self._get_item(COMPUTER_ITEM_TYPE, name_or_id),
            )
        return self._get_ci_by_name(name_or_id)

    def get_ci_dependencies(self, name_or_id: str) -> Sequence[Dependency]:
        """Return direct dependencies for one CMDB configuration item."""
        source = self.get_ci(name_or_id)
        relations = self._list_items("ImpactRelation")
        dependencies: list[Dependency] = []

        for relation in relations:
            if not relation_matches_impacted_ci(relation, source.ci_id):
                continue
            target_id = require_string(relation, "items_id_source")
            target = self.get_ci(target_id)
            dependencies.append(
                Dependency(
                    source=source,
                    target=target,
                    relation_type=DEFAULT_RELATION_TYPE,
                ),
            )

        return tuple(dependencies)

    def update_ticket(
        self,
        ticket_id: str,
        diagnosis: str,
        evidence: Sequence[str],
        confidence: float,
        approval_token: str,
    ) -> TicketWriteResult:
        """Write a diagnosis to one ticket."""
        require_approval_token(approval_token)
        content = format_ticket_update(diagnosis, evidence, confidence)
        response = self.client.post(
            self._url("TicketFollowup"),
            headers=self._headers(),
            json={"input": {"tickets_id": int(ticket_id), "content": content}},
        )
        response.raise_for_status()
        return TicketWriteResult(
            ticket_id=ticket_id,
            status="updated",
            written=True,
            message="ticket followup created",
        )

    def close_ticket(
        self,
        ticket_id: str,
        reason: str,
        approval_token: str,
    ) -> TicketWriteResult:
        """Close one ticket."""
        require_approval_token(approval_token)
        response = self.client.put(
            self._url(f"Ticket/{ticket_id}"),
            headers=self._headers(),
            json={"input": {"status": GLPI_STATUS_SOLVED, "content": reason}},
        )
        response.raise_for_status()
        return TicketWriteResult(
            ticket_id=ticket_id,
            status="closed",
            written=True,
            message="ticket marked solved",
        )

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        if not self.session_token:
            self.init_session()
        return {
            "App-Token": self.auth.app_token,
            "Session-Token": require_session_token(self.session_token),
            "Content-Type": "application/json",
        }

    def _get_item(self, item_type: str, item_id: str) -> dict[str, Any]:
        response = self.client.get(
            self._url(f"{item_type}/{item_id}"),
            headers=self._headers(),
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            msg = f"GLPI {item_type}/{item_id} response was not an object"
            raise GLPIClientError(msg)
        return body

    def _list_items(self, item_type: str) -> list[dict[str, Any]]:
        response = self.client.get(
            self._url(item_type),
            headers=self._headers(),
            params={"range": f"0-{self.list_page_size - 1}"},
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, list):
            msg = f"GLPI {item_type} list response was not a list"
            raise GLPIClientError(msg)
        return [item for item in body if isinstance(item, dict)]

    def _get_ci_by_name(self, name: str) -> ConfigurationItem:
        items = self._list_items(COMPUTER_ITEM_TYPE)
        for item in items:
            if str(item.get("name")) == name:
                return configuration_item_from_glpi(item)
        msg = f"Configuration item not found: {name}"
        raise GLPIClientError(msg)


def require_session_token(session_token: str | None) -> str:
    """Return a session token or raise."""
    if not session_token:
        msg = "GLPI session token is missing"
        raise GLPIClientError(msg)
    return session_token


def require_approval_token(approval_token: str) -> None:
    """Reject writes without an approval token."""
    if not approval_token:
        msg = "approval_token is required for GLPI writes"
        raise PermissionError(msg)


def require_string(body: dict[str, Any], key: str) -> str:
    """Return one GLPI field as a string."""
    value = body.get(key)
    if value is None:
        msg = f"Missing GLPI field: {key}"
        raise GLPIClientError(msg)
    return str(value)


def optional_string(body: dict[str, Any], key: str) -> str | None:
    """Return one optional GLPI field as a string."""
    value = body.get(key)
    return None if value is None else str(value)


def parse_glpi_datetime(value: Any) -> datetime:
    """Parse a GLPI datetime value."""
    if not value:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def ticket_from_glpi(body: dict[str, Any]) -> Ticket:
    """Map a GLPI Ticket object into a protocol model."""
    return Ticket(
        ticket_id=require_string(body, "id"),
        title=require_string(body, "name"),
        description=str(body.get("content") or ""),
        service=str(body.get("service") or body.get("item_name") or ""),
        status=require_string(body, "status"),
        created_at=parse_glpi_datetime(body.get("date_creation") or body.get("date")),
    )


def configuration_item_from_glpi(body: dict[str, Any]) -> ConfigurationItem:
    """Map a GLPI Computer object into a protocol model."""
    return ConfigurationItem(
        ci_id=require_string(body, "id"),
        name=require_string(body, "name"),
        item_type=str(body.get("itemtype") or COMPUTER_ITEM_TYPE),
        description=optional_string(body, "comment"),
    )


def relation_matches_impacted_ci(relation: dict[str, Any], ci_id: str) -> bool:
    """Return whether an ImpactRelation belongs to one impacted CI."""
    return (
        str(relation.get("itemtype_impacted")) == COMPUTER_ITEM_TYPE
        and str(relation.get("items_id_impacted")) == ci_id
        and str(relation.get("itemtype_source")) == COMPUTER_ITEM_TYPE
    )


def format_ticket_update(
    diagnosis: str,
    evidence: Sequence[str],
    confidence: float,
) -> str:
    """Format a ticket followup body."""
    evidence_text = "\n".join(f"- {line}" for line in evidence)
    return (
        f"Diagnosis:\n{diagnosis}\n\n"
        f"Evidence:\n{evidence_text}\n\n"
        f"Confidence: {confidence:.2f}"
    )
