# RB-06 - Postgres Replica Lag and Stale User Reads

Use when user-service returns stale profile data or read-after-write consistency
breaks while the primary database remains healthy. This is a replica incident,
not a primary outage, unless primary WAL generation or replication slots are
also unhealthy.

Symptoms:

- postgres-replica streaming replication lag above normal
- WAL replay paused due to conflict with running query
- user-service logs stale updated_at value
- checkout or notification may reference old user preferences

Checks:

- Query replica lag and replay pause reason.
- Identify long-running read queries on the replica.
- Check reporting or analytics jobs that may have landed on the app replica.
- Confirm postgres-main is accepting writes and not the first failing system.

False leads:

- user-service is usually the victim.
- postgres-main connection count can be normal.
- cache misses can make stale-read symptoms louder without causing them.

Mitigation:

- cancel the blocking analytical query
- move reporting to a dedicated replica
- temporarily route critical reads to primary if correctness matters more than
  load
- record the blocked query id and lag duration

