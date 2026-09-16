from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime

from src.gate import (
    Diagnosis,
    diagnosis_from_message,
    gate_diagnosis,
    gate_state,
)
from src.state import initial_triage_state
from tests.test_mcp_observability import make_settings


class GateTests(unittest.TestCase):
    def test_gate_issues_approval_token_when_confidence_meets_threshold(self) -> None:
        decision = gate_diagnosis(
            confident_diagnosis(),
            make_settings(),
            token_factory=static_token,
            now=datetime(2026, 9, 16, 10, 0, tzinfo=UTC),
        )

        self.assertEqual(decision.status, "auto_write")
        self.assertEqual(decision.approval_token, "approval-token")
        self.assertEqual(decision.next_action, "update_ticket")
        self.assertEqual(decision.token_expires_at, "2026-09-16T10:15:00+00:00")

    def test_gate_escalates_when_confidence_is_below_threshold(self) -> None:
        diagnosis = confident_diagnosis(confidence=0.79)

        decision = gate_diagnosis(diagnosis, make_settings(), token_factory=static_token)

        self.assertEqual(decision.status, "escalate")
        self.assertIsNone(decision.approval_token)
        self.assertEqual(decision.reason, "confidence below threshold")

    def test_gate_escalates_when_step_cap_is_hit(self) -> None:
        decision = gate_diagnosis(
            confident_diagnosis(),
            make_settings(),
            cap_hit=True,
            token_factory=static_token,
        )

        self.assertEqual(decision.status, "escalate")
        self.assertEqual(decision.reason, "step cap hit")
        self.assertIsNone(decision.approval_token)

    def test_gate_escalates_uncertain_diagnosis(self) -> None:
        diagnosis = confident_diagnosis(next_action="escalate to human")

        decision = gate_diagnosis(diagnosis, make_settings(), token_factory=static_token)

        self.assertEqual(decision.status, "escalate")
        self.assertEqual(decision.reason, "diagnosis is uncertain")

    def test_gate_state_returns_state_update(self) -> None:
        message = FakeMessage(
            json.dumps(
                {
                    "root_cause": "postgres-main",
                    "impacted_service": "payment-api",
                    "causal_chain": ["postgres-main", "auth-service", "payment-api"],
                    "evidence": ["too many clients"],
                    "confidence": 0.87,
                    "next_action": "update_ticket",
                }
            )
        )
        state = initial_triage_state(messages=(message,))

        update = gate_state(
            state,
            make_settings(),
            token_factory=static_token,
            now=datetime(2026, 9, 16, 10, 0, tzinfo=UTC),
        )

        self.assertEqual(update["approval_token"], "approval-token")
        self.assertEqual(update["gate_decision"]["status"], "auto_write")

    def test_diagnosis_from_message_parses_json_content(self) -> None:
        diagnosis = diagnosis_from_message(
            FakeMessage(
                json.dumps(
                    {
                        "root_cause": "postgres-main",
                        "impacted_service": "payment-api",
                        "causal_chain": ["postgres-main", "payment-api"],
                        "evidence": ["max_connections reached"],
                        "confidence": 0.9,
                        "next_action": "update_ticket",
                    }
                )
            )
        )

        self.assertEqual(diagnosis.root_cause, "postgres-main")
        self.assertEqual(diagnosis.confidence, 0.9)

    def test_gate_rejects_invalid_confidence(self) -> None:
        with self.assertRaises(ValueError):
            gate_diagnosis(confident_diagnosis(confidence=1.2), make_settings())


class FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


def confident_diagnosis(
    confidence: float = 0.87,
    next_action: str = "update_ticket",
) -> Diagnosis:
    """Return a valid diagnosis for gate tests."""
    return Diagnosis(
        root_cause="postgres-main",
        impacted_service="payment-api",
        causal_chain=("postgres-main", "auth-service", "payment-api"),
        evidence=("too many clients", "connection pool exhausted"),
        confidence=confidence,
        next_action=next_action,
    )


def static_token() -> str:
    """Return a deterministic test token."""
    return "approval-token"


if __name__ == "__main__":
    unittest.main()
