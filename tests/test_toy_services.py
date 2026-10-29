from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from services.auth_service import create_app as create_auth_app
from services.payment_api import create_app as create_payment_app
from services.runtime import ServiceRuntime


class ToyServiceTests(unittest.TestCase):
    def test_auth_fault_is_injectable_and_recoverable(self) -> None:
        client = TestClient(create_auth_app(ServiceRuntime()))

        healthy = client.get("/verify")
        client.post("/fault")
        failed = client.get("/verify")
        client.post("/recover")
        recovered = client.get("/verify")

        self.assertEqual(healthy.status_code, 200)
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(recovered.status_code, 200)

    def test_payment_reports_dependency_failure_in_metrics(self) -> None:
        runtime = ServiceRuntime()
        client = TestClient(create_payment_app(AlwaysFailVerifier(), runtime))

        charge = client.post("/charge")
        metrics = client.get("/metrics")

        self.assertEqual(charge.status_code, 503)
        self.assertIn(
            'toy_http_requests_total{service="payment-api",status="error"} 1',
            metrics.text,
        )


class AlwaysFailVerifier:
    def verify(self) -> bool:
        return False


if __name__ == "__main__":
    unittest.main()
