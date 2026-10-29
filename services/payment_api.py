"""Payment API whose dependency failure produces a victim alert."""

from __future__ import annotations

import os
from typing import Protocol

import httpx
from fastapi import FastAPI, Response, status

from services.runtime import ServiceRuntime, render_metrics


SERVICE_NAME = "payment-api"
DEFAULT_AUTH_URL = "http://auth-service:9002"
DEFAULT_TIMEOUT_SECONDS = 1.0


class AuthVerifier(Protocol):
    """Dependency needed to authorize a charge."""

    def verify(self) -> bool:
        """Return whether authentication succeeded."""
        ...


class HttpAuthVerifier:
    """HTTP adapter for the auth-service dependency."""

    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def verify(self) -> bool:
        """Call auth-service and classify its response."""
        try:
            response = httpx.get(
                f"{self.base_url}/verify",
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError:
            return False
        return response.status_code == status.HTTP_200_OK


def create_app(
    verifier: AuthVerifier | None = None,
    runtime: ServiceRuntime | None = None,
) -> FastAPI:
    """Create an isolated payment application."""
    effective_runtime = runtime or ServiceRuntime()
    effective_verifier = verifier or HttpAuthVerifier(
        os.environ.get("AUTH_SERVICE_URL", DEFAULT_AUTH_URL),
        DEFAULT_TIMEOUT_SECONDS,
    )
    app = FastAPI(title=SERVICE_NAME)
    app.state.runtime = effective_runtime
    app.add_api_route("/health", PaymentHealthEndpoint(), methods=["GET"])
    app.add_api_route(
        "/charge",
        ChargeEndpoint(effective_verifier, effective_runtime),
        methods=["POST"],
    )
    app.add_api_route("/metrics", MetricsEndpoint(effective_runtime), methods=["GET"])
    return app


class PaymentHealthEndpoint:
    """Process health endpoint."""

    def __call__(self) -> dict[str, str]:
        """Return process health."""
        return {"status": "up"}


class ChargeEndpoint:
    """Charge endpoint that depends on authentication."""

    def __init__(self, verifier: AuthVerifier, runtime: ServiceRuntime) -> None:
        self.verifier = verifier
        self.runtime = runtime

    def __call__(self, response: Response) -> dict[str, str]:
        """Return a charge result and record the dependency outcome."""
        authenticated = self.verifier.verify()
        self.runtime.record(authenticated)
        if not authenticated:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"error": "upstream auth-service unavailable"}
        return {"status": "charged"}


class MetricsEndpoint:
    """Expose payment outcome counters to Prometheus."""

    def __init__(self, runtime: ServiceRuntime) -> None:
        self.runtime = runtime

    def __call__(self) -> Response:
        """Return Prometheus text exposition."""
        return Response(
            render_metrics(SERVICE_NAME, self.runtime.counts()),
            media_type="text/plain; version=0.0.4",
        )

