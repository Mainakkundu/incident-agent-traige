# RB-24 - Internal Dashboard Query Timeout

Use for analytics dashboard slowness, ad-hoc reporting queries, or analyst
workbench timeouts. It overlaps with database terminology but is usually not a
production checkout incident unless the query runs on postgres-replica and blocks
WAL replay.

Checks:

- dashboard query text
- warehouse queue depth
- BI tool timeout setting
- analyst concurrency

Do not confuse this with auth-service connection pool exhaustion or
postgres-main max_connections. If user-service stale reads are present, use the
replica lag runbook instead.

