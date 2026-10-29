"""Runnable application factory for the local end-to-end incident demo."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI

from src.api import create_incident_app
from src.audit import PhoenixRunAuditReader
from src.config import Settings, load_settings
from src.gld_001 import (
    RUN_SPAN_NAME,
    TRACER_NAME,
    gld001_result_attributes,
    gld001_run_attributes,
    run_gld001,
)
from src.ingestion import IncidentAlert, InMemoryRunRegistry, ThreadPoolIncidentDispatcher
from src.tracing import (
    TracingHandle,
    configure_tracing,
    get_tracer,
    set_span_attributes,
    shutdown_tracing,
)


class DemoIncidentHandler:
    """Connect the toy payment alert to the verified supervisor graph."""

    def __init__(self, settings: Settings, tracer: Any) -> None:
        self.settings = settings
        self.tracer = tracer

    def __call__(self, run_id: str, alert: IncidentAlert) -> None:
        """Run the traced investigation for the supported local demo alert."""
        if alert.service != "payment-api":
            raise ValueError(f"unsupported demo alert service: {alert.service}")
        with self.tracer.start_as_current_span(RUN_SPAN_NAME) as span:
            set_span_attributes(span, gld001_run_attributes(run_id))
            result = run_gld001(self.settings)
            set_span_attributes(span, gld001_result_attributes(result))


class RuntimeLifecycle:
    """Own application worker and tracing resources."""

    def __init__(
        self,
        dispatcher: ThreadPoolIncidentDispatcher,
        tracing_handle: TracingHandle,
    ) -> None:
        self.dispatcher = dispatcher
        self.tracing_handle = tracing_handle

    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncIterator[None]:
        """Release worker and trace exporter during application shutdown."""
        del app
        yield
        self.dispatcher.shutdown(wait=True)
        shutdown_tracing(self.tracing_handle)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the runnable API with a non-blocking supervisor dispatcher."""
    effective_settings = settings or load_settings()
    # Export spans in the background so an unavailable observability backend
    # cannot block alert ingestion or health checks.
    tracing_handle = configure_tracing(effective_settings, batch=True)
    tracer = get_tracer(TRACER_NAME)
    dispatcher = ThreadPoolIncidentDispatcher(
        DemoIncidentHandler(effective_settings, tracer),
        max_workers=1,
    )
    lifecycle = RuntimeLifecycle(dispatcher, tracing_handle)
    app = create_incident_app(
        PhoenixRunAuditReader.from_settings(effective_settings),
        InMemoryRunRegistry(),
        dispatcher,
        lifespan=lifecycle.lifespan,
    )
    app.state.incident_dispatcher = dispatcher
    return app
