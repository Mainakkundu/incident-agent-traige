"""Continuous deterministic load for the payment-api toy service."""

from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI


DEFAULT_PAYMENT_URL = "http://payment-api:9001"
DEFAULT_INTERVAL_SECONDS = 0.2
DEFAULT_TIMEOUT_SECONDS = 1.0


class TrafficGenerator:
    """Background loop that exercises the payment endpoint."""

    def __init__(self, payment_url: str, interval_seconds: float) -> None:
        self.payment_url = payment_url.rstrip("/")
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        """Start generating traffic."""
        self._thread.start()

    def stop(self) -> None:
        """Stop generating traffic and join its thread."""
        self._stop.set()
        self._thread.join(timeout=DEFAULT_TIMEOUT_SECONDS)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                httpx.post(
                    f"{self.payment_url}/charge",
                    timeout=DEFAULT_TIMEOUT_SECONDS,
                )
            except httpx.HTTPError:
                pass
            self._stop.wait(self.interval_seconds)


class TrafficApplication:
    """Own the traffic-generator lifecycle without module globals."""

    def __init__(self, generator: TrafficGenerator) -> None:
        self.generator = generator

    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncIterator[None]:
        """Start and stop background traffic with the ASGI process."""
        del app
        self.generator.start()
        yield
        self.generator.stop()


def create_app(generator: TrafficGenerator | None = None) -> FastAPI:
    """Create the traffic-generator process application."""
    effective_generator = generator or TrafficGenerator(
        os.environ.get("PAYMENT_API_URL", DEFAULT_PAYMENT_URL),
        DEFAULT_INTERVAL_SECONDS,
    )
    owner = TrafficApplication(effective_generator)
    app = FastAPI(title="traffic-gen", lifespan=owner.lifespan)
    app.add_api_route("/health", TrafficHealthEndpoint(), methods=["GET"])
    return app


class TrafficHealthEndpoint:
    """Health endpoint for container orchestration."""

    def __call__(self) -> dict[str, str]:
        """Return process health."""
        return {"status": "up"}
