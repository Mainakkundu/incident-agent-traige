# RB-01 - Postgres Connection Pressure During Checkout

Use when a downstream service reports pool exhaustion, "too many clients", slow
token validation, or intermittent 503s after a quiet deploy window. This is not
always a database outage; first prove whether the DB is refusing connections or
the application pool is leaking them.

Symptoms seen in past incidents:

- Postgres emits "FATAL: sorry, too many clients already" or max_connections reached.
- auth-service says connection pool exhausted after 5000ms.
- payment-api reports upstream auth-service timeout or charge endpoint 503.
- Graph impact can look reversed in dashboards: payment-api is noisy, but the
  pressure starts below auth-service.

Checks:

- Count active and idle DB sessions grouped by application name.
- Compare connection count before and after reconciliation, receipt, or ledger jobs.
- Check whether recent deploys changed pool size, retry policy, or worker count.
- Confirm redis is not causing repeated token issuance; redis warnings can be a
  side effect, not the root cause.

Do not jump straight to raising max_connections. If idle sessions belong to a
batch job, terminate a small sample and watch auth-service recover. Raising the
limit without fixing the leak usually moves the incident to CPU or memory.

Useful ticket update evidence:

- first Postgres refusal timestamp
- auth-service pool timeout line
- payment-api upstream timeout line
- dependency chain from CMDB

