from __future__ import annotations

import unittest
from datetime import UTC, datetime

from src.clients.protocols import ConfigurationItem, Dependency, LogEntry
from src.gld_001 import (
    GLD001_EXPECTED_CHAIN,
    GLD001_EXPECTED_ROOT,
    assert_gld001_result,
    run_gld001_with_tools,
)
from src.mcp.itsm import ITSMTools
from src.mcp.observability import ObservabilityTools
from tests.test_mcp_observability import FakeObservabilityClient, make_settings


class Gld001Tests(unittest.TestCase):
    def test_gld001_runner_reaches_expected_root_and_gate(self) -> None:
        settings = make_settings()
        observability = ObservabilityTools(
            Gld001ObservabilityClient(),
            Gld001ObservabilityClient(),
            Gld001ObservabilityClient(),
            settings,
        )
        cmdb = Gld001CMDBClient()
        itsm = ITSMTools(cmdb, cmdb, cmdb, cmdb, cmdb)

        state = run_gld001_with_tools(settings, observability, itsm)

        self.assertEqual(state["gate_decision"]["status"], "auto_write")
        self.assertTrue(state["approval_token"])
        result = assertable_result(state)
        self.assertEqual(result["root_cause"], GLD001_EXPECTED_ROOT)
        self.assertEqual(tuple(result["causal_chain"]), GLD001_EXPECTED_CHAIN)
        assert_gld001_result(result["typed"])


class Gld001ObservabilityClient(FakeObservabilityClient):
    def search_logs(
        self,
        service: str,
        window_start: datetime,
        window_end: datetime,
        level: str | None = None,
        keyword: str | None = None,
        limit: int | None = None,
    ) -> tuple[LogEntry, ...]:
        return (
            LogEntry(
                timestamp=datetime(2026, 7, 31, 20, 21, tzinfo=UTC),
                service=service,
                level="ERROR",
                message=message_for_service(service),
            ),
        )


class Gld001CMDBClient:
    def get_ticket(self, ticket_id: str) -> object:
        raise NotImplementedError

    def get_ci(self, name_or_id: str) -> ConfigurationItem:
        return ci(name_or_id)

    def get_ci_dependencies(self, name_or_id: str) -> tuple[Dependency, ...]:
        if name_or_id == "payment-api":
            return (Dependency(ci("payment-api"), ci("auth-service"), "depends_on"),)
        if name_or_id == "auth-service":
            return (Dependency(ci("auth-service"), ci("postgres-main"), "depends_on"),)
        return ()

    def get_similar_incidents(self, signature: str, limit: int | None = None) -> tuple:
        return ()

    def search_runbooks(self, query: str, limit: int | None = None) -> tuple:
        return ()

    def update_ticket(self, *args: object, **kwargs: object) -> object:
        raise NotImplementedError

    def close_ticket(self, *args: object, **kwargs: object) -> object:
        raise NotImplementedError


def ci(name: str) -> ConfigurationItem:
    """Return one configuration item."""
    return ConfigurationItem(
        ci_id=name,
        name=name,
        item_type="Computer",
        description=None,
    )


def message_for_service(service: str) -> str:
    """Return one gld_001 evidence message."""
    if service == "postgres-main":
        return "FATAL: sorry, too many clients already"
    if service == "auth-service":
        return "connection pool exhausted, no available connections after 5000ms"
    return "upstream auth-service timeout after 3000ms"


def assertable_result(state: dict) -> dict:
    """Return both raw and typed runner results."""
    from src.gld_001 import result_from_state

    typed = result_from_state(state)
    return {
        "typed": typed,
        "root_cause": typed.root_cause,
        "causal_chain": typed.causal_chain,
    }


if __name__ == "__main__":
    unittest.main()
