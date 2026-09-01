# RB-02 - Auth Service Memory Leak, OOM, and Restart Loop

Use when token issuance fails, health checks flap, or clients see connection
refused from auth-service. This can resemble a Postgres problem because auth
often logs DB pool errors near the crash; look for memory pressure before
blaming the database.

Likely clues:

- heap usage above 90 percent of container limit
- token cache growth without matching eviction
- OutOfMemoryError, OOMKilled, restart count increment
- payment-api sees dial tcp auth-service connection refused

Investigation path:

- Confirm auth-service container restart time against the alert start.
- Compare auth-service memory and request rate; a flat request rate with rising
  heap points to leak or cache growth.
- Search for token-cache, session, and JWT validation errors around the same
  window.
- Check Postgres only after proving auth-service stayed alive long enough to
  request a DB connection.

Common false lead: repeated payment-api 503s are victim symptoms. Do not name
payment-api as root cause unless a recent payment deploy or local exception
appears.

Mitigation notes:

- restart auth-service if it is actively down
- cap token cache size
- lower token cache TTL temporarily
- preserve crash logs before container rotation removes them

