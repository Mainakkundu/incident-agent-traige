"""Breakable authentication dependency for the local incident demo."""

from __future__ import annotations

from fastapi import FastAPI, Response, status

from services.runtime import ServiceRuntime, render_metrics


SERVICE_NAME = "auth-service"


def create_app(runtime: ServiceRuntime | None = None) -> FastAPI:
    """Create an isolated auth-service application."""
    effective_runtime = runtime or ServiceRuntime()
    app = FastAPI(title=SERVICE_NAME)
    app.state.runtime = effective_runtime
    app.add_api_route("/health", AuthHealthEndpoint(), methods=["GET"])
    app.add_api_route("/verify", VerifyEndpoint(effective_runtime), methods=["GET"])
    app.add_api_route(
        "/fault",
        FaultEndpoint(effective_runtime, True),
        methods=["POST"],
    )
    app.add_api_route(
        "/recover",
        FaultEndpoint(effective_runtime, False),
        methods=["POST"],
    )
    app.add_api_route("/metrics", MetricsEndpoint(effective_runtime), methods=["GET"])
    return app


class AuthHealthEndpoint:
    """Health endpoint independent of the injected business fault."""

    def __call__(self) -> dict[str, str]:
        """Return process health."""
        return {"status": "up"}


class VerifyEndpoint:
    """Authentication call used by payment-api."""

    def __init__(self, runtime: ServiceRuntime) -> None:
        self.runtime = runtime

    def __call__(self, response: Response) -> dict[str, str]:
        """Return a token check or injected connection failure."""
        failed = self.runtime.fault_enabled()
        self.runtime.record(not failed)
        if failed:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"error": "postgres-main connection pool exhausted"}
        return {"status": "valid"}


class FaultEndpoint:
    """Toggle the deterministic auth dependency fault."""

    def __init__(self, runtime: ServiceRuntime, enabled: bool) -> None:
        self.runtime = runtime
        self.enabled = enabled

    def __call__(self) -> dict[str, bool]:
        """Set and return the fault state."""
        self.runtime.set_fault(self.enabled)
        return {"fault_enabled": self.enabled}


class MetricsEndpoint:
    """Expose auth request counters to Prometheus."""

    def __init__(self, runtime: ServiceRuntime) -> None:
        self.runtime = runtime

    def __call__(self) -> Response:
        """Return Prometheus text exposition."""
        return Response(
            render_metrics(SERVICE_NAME, self.runtime.counts()),
            media_type="text/plain; version=0.0.4",
        )

