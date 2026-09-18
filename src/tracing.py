"""Phoenix and OpenInference tracing setup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from opentelemetry import trace
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
from phoenix.otel import register

from src.config import Settings


PHOENIX_PROTOCOL = "http/protobuf"
DEFAULT_BATCH_EXPORT = False
DEFAULT_AUTO_INSTRUMENT = False


class TracerProviderLike(Protocol):
    """Minimal tracer provider interface used by the app."""

    def shutdown(self) -> None:
        """Flush and stop tracing."""
        ...


RegisterTracing = Callable[..., TracerProviderLike]


@dataclass(frozen=True, slots=True)
class TracingHandle:
    """Configured tracing provider."""

    tracer_provider: TracerProviderLike
    project_name: str
    endpoint: str


def configure_tracing(
    settings: Settings,
    register_tracing: RegisterTracing = register,
    batch: bool = DEFAULT_BATCH_EXPORT,
    auto_instrument: bool = DEFAULT_AUTO_INSTRUMENT,
) -> TracingHandle:
    """Configure Phoenix OpenInference tracing."""
    require_tracing_settings(settings)
    provider = register_tracing(
        project_name=settings.phoenix_project_name,
        endpoint=settings.otel_exporter_otlp_endpoint,
        protocol=PHOENIX_PROTOCOL,
        batch=batch,
        auto_instrument=auto_instrument,
        verbose=False,
        sampler=TraceIdRatioBased(settings.trace_sample_rate),
    )
    return TracingHandle(
        tracer_provider=provider,
        project_name=settings.phoenix_project_name,
        endpoint=settings.otel_exporter_otlp_endpoint,
    )


def shutdown_tracing(handle: TracingHandle) -> None:
    """Shutdown tracing for one configured provider."""
    handle.tracer_provider.shutdown()


def get_tracer(name: str) -> Any:
    """Return one OpenTelemetry tracer."""
    return trace.get_tracer(name)


def set_span_attributes(span: Any, attributes: Mapping[str, Any]) -> None:
    """Set supported OpenTelemetry span attributes."""
    for name, value in attributes.items():
        if value is None:
            continue
        span.set_attribute(name, value)


def require_tracing_settings(settings: Settings) -> None:
    """Validate tracing settings."""
    require_non_empty(settings.phoenix_project_name, "phoenix_project_name")
    require_non_empty(settings.otel_exporter_otlp_endpoint, "otel_exporter_otlp_endpoint")
    if settings.trace_sample_rate < 0.0 or settings.trace_sample_rate > 1.0:
        msg = "trace_sample_rate must be between 0.0 and 1.0"
        raise ValueError(msg)


def require_non_empty(value: str, name: str) -> None:
    """Require one non-empty string setting."""
    if not value.strip():
        msg = f"{name} is required"
        raise ValueError(msg)
