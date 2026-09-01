# RB-04 - Redis Eviction Causing Token and Session Storm

Use when redis-cache logs evictions or maxmemory pressure and auth-service starts
issuing far more tokens than normal. This incident often has WARN-heavy logs
with few or no ERROR lines, so searching only for ERROR can miss it.

Observed clues:

- memory_used_pct above 95
- evicted keys rising quickly
- session lookup miss rate jumps
- token issuance rate rises, then database connections also rise
- users report login loops or checkout session resets

Investigation:

- Search redis-cache WARN logs, not only ERROR.
- Compare auth-service token issuance against baseline.
- Check session TTL and recent config edits to cache size or eviction policy.
- Verify Postgres connection growth is caused by auth-service re-auth traffic
  before blaming Postgres.

False leads:

- Postgres may show connection pressure as a secondary effect.
- payment-api may show 401/503 depending on retry behavior.
- A deploy may be unrelated if cache pressure started earlier.

Mitigation:

- raise maxmemory only after checking stale-key growth
- reduce session TTL if stale sessions dominate
- restore eviction policy if it was changed
- clear only safe namespaces; do not flush all keys during checkout peak

