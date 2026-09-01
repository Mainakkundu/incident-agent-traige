# RB-03 - Payment API Deploy Regression With Mixed Traffic

Use when payment-api itself starts returning 500s after a version change. The
problem may only hit refund or metadata paths, so aggregate error rate can hide
the exact failure until logs are grouped by route.

Signals:

- deploy event within the incident lookback window
- new version line shortly before errors
- NullPointerException, validation panic, schema mismatch, or 500s in payment-api
- dependency logs are clean or only show retry noise from payment-api

Checks:

- Read deploys before chasing the dependency graph too far.
- Search payment-api logs by route: charge, refund, capture, webhook.
- Compare one clean request path and one failing request path.
- Inspect api-gateway only for confirmation of elevated upstream error rate.

Messy reality:

- auth-service timeouts can appear after payment-api retry storms.
- ledger-service may show duplicate-id warnings because payment-api retried.
- A clean health check does not prove payment-api business routes are healthy.

Suggested response:

- roll back the version if a new release correlates tightly with first error
- add regression test for the route and payload shape
- include deploy hash, first exception, and affected route in ticket evidence

