# RB-22 - DNS Resolution Flap for Internal Services

Use when services intermittently cannot resolve names, CoreDNS restarts, or
clients show NXDOMAIN/SERVFAIL. This can cause timeouts that look like upstream
service incidents, but the key evidence is resolver failure rather than app
logs from the dependency itself.

Checks:

- resolver error rate
- DNS query latency
- CoreDNS pod restarts
- search path and ndots changes
- node-level /etc/resolv.conf drift

This is a decoy for incidents where auth-service, postgres-main, redis-cache,
kafka-broker, or s3-receipts have direct failure logs.

