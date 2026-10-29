"""Fault scenarios and dependency-guided investigation harness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ServiceSignal:
    """Runtime health evidence for one service."""

    healthy: bool
    dependencies: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ChaosScenario:
    """One injected fault and its expected conclusion."""

    name: str
    alerted_service: str
    expected_root: str | None
    signals: Mapping[str, ServiceSignal]


@dataclass(frozen=True, slots=True)
class ChaosResult:
    """Observed conclusion from one dependency-guided investigation."""

    name: str
    expected_root: str | None
    observed_root: str | None
    services_inspected: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """Return whether the observed root matches the labelled scenario."""
        return self.observed_root == self.expected_root


class DependencyInvestigator:
    """Walk only unhealthy dependencies exposed by the current service."""

    def investigate(self, scenario: ChaosScenario) -> ChaosResult:
        """Return the deepest unhealthy dependency reachable from the alert."""
        inspected: list[str] = []
        current = scenario.alerted_service
        root: str | None = None
        while current not in inspected:
            inspected.append(current)
            signal = scenario.signals[current]
            if signal.healthy:
                break
            root = current
            unhealthy_dependencies = tuple(
                dependency
                for dependency in signal.dependencies
                if not scenario.signals[dependency].healthy
            )
            if not unhealthy_dependencies:
                break
            current = unhealthy_dependencies[0]
        return ChaosResult(
            name=scenario.name,
            expected_root=scenario.expected_root,
            observed_root=root,
            services_inspected=tuple(inspected),
        )


def scenarios() -> tuple[ChaosScenario, ...]:
    """Return the six fixed chaos cases, including a clean control."""
    return (
        scenario(
            "postgres_connection_exhaustion",
            "payment-api",
            "postgres-main",
            unhealthy=("payment-api", "auth-service", "postgres-main"),
        ),
        scenario(
            "auth_service_oom",
            "payment-api",
            "auth-service",
            unhealthy=("payment-api", "auth-service"),
        ),
        scenario(
            "payment_deploy_regression",
            "payment-api",
            "payment-api",
            unhealthy=("payment-api",),
        ),
        scenario(
            "redis_eviction_storm",
            "auth-service",
            "redis-cache",
            unhealthy=("auth-service", "redis-cache"),
        ),
        scenario(
            "s3_throttling",
            "notification-svc",
            "s3-receipts",
            unhealthy=("notification-svc", "s3-receipts"),
        ),
        scenario(
            "nothing_is_wrong",
            "payment-api",
            None,
            unhealthy=(),
        ),
    )


def scenario(
    name: str,
    alerted_service: str,
    expected_root: str | None,
    unhealthy: tuple[str, ...],
) -> ChaosScenario:
    """Build a scenario over the fixed service topology."""
    topology = {
        "payment-api": ("auth-service",),
        "auth-service": ("postgres-main", "redis-cache"),
        "postgres-main": (),
        "redis-cache": (),
        "notification-svc": ("s3-receipts",),
        "s3-receipts": (),
    }
    unhealthy_set = set(unhealthy)
    signals = {
        service: ServiceSignal(
            healthy=service not in unhealthy_set,
            dependencies=dependencies,
        )
        for service, dependencies in topology.items()
    }
    return ChaosScenario(name, alerted_service, expected_root, signals)


def run_named_scenario(name: str) -> ChaosResult:
    """Run one named scenario or reject an unknown name."""
    matches = tuple(item for item in scenarios() if item.name == name)
    if not matches:
        raise ValueError(f"unknown chaos scenario: {name}")
    return DependencyInvestigator().investigate(matches[0])
