"""
Generate a realistic historical log corpus for the 12-service topology.

Replaces the HDFS data, which is Hadoop block-replication chatter and has
nothing to do with the failure modes this agent investigates.

Produces ~30 days of logs with:
  - normal operational noise (the bulk)
  - a handful of seeded historical incidents with proper causal chains,
    so get_similar_incidents() has real precedent to find

Run:  python generate_logs.py
"""

import os
import random
from datetime import datetime, timedelta, timezone

import psycopg
from dotenv import load_dotenv

load_dotenv()

DSN = os.getenv("DB_DSN", "postgresql://agent:agent@localhost:5432/incidents")

random.seed(42)
NOW = datetime.now(timezone.utc)

SERVICES = [
    "payment-api", "checkout-web", "auth-service", "user-service",
    "notification-svc", "ledger-service", "postgres-main",
    "postgres-replica", "redis-cache", "kafka-broker",
    "s3-receipts", "api-gateway",
]

DEPENDS_ON = {
    "checkout-web": ["api-gateway"],
    "api-gateway": ["payment-api"],
    "payment-api": ["auth-service", "ledger-service", "kafka-broker"],
    "auth-service": ["postgres-main", "redis-cache"],
    "user-service": ["postgres-replica"],
    "ledger-service": ["postgres-main"],
    "notification-svc": ["kafka-broker", "s3-receipts"],
    "postgres-replica": ["postgres-main"],
}

# ── normal traffic ──────────────────────────────────────────────
NORMAL = {
    "payment-api": [
        "POST /charge 200 amount={amt} currency=INR latency={ms}ms",
        "POST /refund 200 txn={txn} latency={ms}ms",
        "GET /health 200 latency={ms}ms",
    ],
    "checkout-web": [
        "GET /checkout 200 session={txn} latency={ms}ms",
        "POST /cart/update 200 items={n} latency={ms}ms",
    ],
    "auth-service": [
        "token issued subject=user_{n} ttl=3600 latency={ms}ms",
        "token validated subject=user_{n} latency={ms}ms",
        "pool stats active={n} idle={n} max=20",
    ],
    "user-service": [
        "GET /users/{n} 200 latency={ms}ms",
        "profile cache hit ratio=0.9{n}",
    ],
    "notification-svc": [
        "email dispatched template=receipt recipient=user_{n}",
        "sms dispatched provider=twilio recipient=user_{n}",
    ],
    "ledger-service": [
        "journal entry posted txn={txn} debit={amt} credit={amt}",
        "batch reconciliation complete entries={n} duration={ms}ms",
    ],
    "postgres-main": [
        "checkpoint complete wrote={n} buffers sync={ms}ms",
        "connection accepted client=10.0.1.{n} db=app",
        "autovacuum: table=public.transactions removed={n} rows",
    ],
    "postgres-replica": [
        "streaming replication lag={ms}ms",
        "read query served relation=users duration={ms}ms",
    ],
    "redis-cache": [
        "GET session:{txn} hit latency={ms}ms",
        "keyspace stats keys={n} evicted=0 memory_used_pct={n}",
    ],
    "kafka-broker": [
        "produced topic=payments partition={n} offset={n}",
        "consumer group=notifications lag={n}",
    ],
    "s3-receipts": [
        "PUT receipts/{txn}.pdf 200 size={n}KB",
        "GET receipts/{txn}.pdf 200 latency={ms}ms",
    ],
    "api-gateway": [
        "routed GET /checkout -> checkout-web 200 latency={ms}ms",
        "rate limit check client={n} remaining={n}",
    ],
}

# ── failure signatures, keyed by root cause ─────────────────────
# each entry: root service -> ordered list of (service, level, message)
INCIDENT_PATTERNS = {
    "postgres_connection_exhaustion": {
        "root": "postgres-main",
        "title": "Database connection limit reached",
        "signature": "postgres max connections reached connection pool exhausted",
        "root_cause": "postgres-main hit max_connections; a batch job held idle connections open without releasing them",
        "resolution": "Terminated idle connections from the reconciliation batch job and added an explicit connection release in its teardown. Raised max_connections from 100 to 150 as headroom.",
        "chain": [
            ("postgres-main", "WARN", "connections in use: 94 of 100"),
            ("postgres-main", "ERROR", "FATAL: sorry, too many clients already"),
            ("postgres-main", "ERROR", "max_connections reached, rejecting new connections"),
            ("auth-service", "ERROR", "connection pool exhausted, no available connections after 5000ms"),
            ("auth-service", "ERROR", "failed to acquire connection from pool: timeout"),
            ("payment-api", "ERROR", "upstream auth-service timeout after 3000ms"),
            ("payment-api", "ERROR", "POST /charge 503 upstream unavailable"),
        ],
    },
    "auth_service_down": {
        "root": "auth-service",
        "title": "Auth service unreachable",
        "signature": "auth service connection refused upstream down token validation failing",
        "root_cause": "auth-service container was OOM-killed after a memory leak in the token cache",
        "resolution": "Restarted auth-service and capped the in-memory token cache at 10k entries with LRU eviction. Raised the container memory limit to 512Mi.",
        "chain": [
            ("auth-service", "WARN", "heap usage 91% of limit"),
            ("auth-service", "ERROR", "OutOfMemoryError: token cache exceeded heap"),
            ("payment-api", "ERROR", "dial tcp auth-service:9002: connection refused"),
            ("payment-api", "ERROR", "POST /charge 503 auth unavailable"),
            ("api-gateway", "ERROR", "upstream payment-api returned 503"),
        ],
    },
    "deploy_regression": {
        "root": "payment-api",
        "title": "Elevated error rate after deploy",
        "signature": "error rate spike after deployment null pointer regression new version",
        "root_cause": "payment-api v1.4.2 introduced a null dereference on refund requests missing an optional metadata field",
        "resolution": "Rolled back payment-api to v1.4.1 and added a null guard plus a regression test for refunds without metadata.",
        "chain": [
            ("payment-api", "INFO", "starting payment-api version=v1.4.2"),
            ("payment-api", "ERROR", "NullPointerException at RefundHandler.processMetadata line 88"),
            ("payment-api", "ERROR", "POST /refund 500 internal error"),
            ("api-gateway", "WARN", "upstream payment-api error rate 14% over 5m"),
        ],
    },
    "redis_eviction_storm": {
        "root": "redis-cache",
        "title": "Session cache eviction storm",
        "signature": "redis memory limit evicting keys session lost users logged out",
        "root_cause": "redis-cache reached its maxmemory limit and began evicting session keys, forcing repeated re-authentication",
        "resolution": "Increased redis maxmemory to 2GB and set session TTL to 30 minutes so stale sessions expire before pressure builds.",
        "chain": [
            ("redis-cache", "WARN", "memory_used_pct=97 approaching maxmemory"),
            ("redis-cache", "WARN", "evicted 4821 keys in last 60s policy=allkeys-lru"),
            ("auth-service", "WARN", "session lookup miss rate 62%, re-issuing tokens"),
            ("auth-service", "WARN", "token issuance rate 8x baseline"),
            ("postgres-main", "WARN", "connections in use: 78 of 100"),
        ],
    },
    "kafka_consumer_lag": {
        "root": "kafka-broker",
        "title": "Notification delivery delayed",
        "signature": "kafka consumer lag growing notifications delayed backlog",
        "root_cause": "A single slow consumer in notification-svc blocked its partition, causing the payments topic backlog to grow",
        "resolution": "Increased notification-svc consumer concurrency from 1 to 4 and added a 10s timeout on the SMS provider call.",
        "chain": [
            ("kafka-broker", "WARN", "consumer group=notifications lag=18420 and growing"),
            ("notification-svc", "WARN", "sms provider call exceeded 30000ms"),
            ("notification-svc", "ERROR", "consumer poll interval exceeded, partition rebalancing"),
            ("kafka-broker", "ERROR", "consumer group=notifications rebalance triggered"),
        ],
    },
    "replica_lag": {
        "root": "postgres-replica",
        "title": "Stale reads from replica",
        "signature": "replication lag stale reads replica behind primary",
        "root_cause": "A long-running analytical query on postgres-replica blocked WAL replay, pushing replication lag past 5 minutes",
        "resolution": "Killed the analytical query and moved reporting workloads to a dedicated replica with hot_standby_feedback disabled.",
        "chain": [
            ("postgres-replica", "WARN", "streaming replication lag=142000ms"),
            ("postgres-replica", "ERROR", "WAL replay paused, conflict with running query pid=8842"),
            ("user-service", "WARN", "profile read returned stale data, updated_at older than request"),
        ],
    },
    "s3_throttling": {
        "root": "s3-receipts",
        "title": "Receipt upload failures",
        "signature": "s3 slow down throttling rate exceeded upload failing",
        "root_cause": "A month-end receipt regeneration job exceeded the S3 request rate and triggered throttling",
        "resolution": "Added exponential backoff to the upload client and spread the regeneration job over 6 hours with a token bucket limiter.",
        "chain": [
            ("s3-receipts", "WARN", "SlowDown: please reduce your request rate"),
            ("s3-receipts", "ERROR", "PUT receipts/batch 503 throttled"),
            ("notification-svc", "ERROR", "receipt attachment unavailable, email queued for retry"),
        ],
    },
}


def rand_fill(template: str) -> str:
    out = template
    while "{ms}" in out:
        out = out.replace("{ms}", str(random.randint(2, 240)), 1)
    while "{n}" in out:
        out = out.replace("{n}", str(random.randint(1, 999)), 1)
    while "{amt}" in out:
        out = out.replace("{amt}", str(random.randint(99, 99999)), 1)
    while "{txn}" in out:
        out = out.replace("{txn}", f"txn_{random.randint(100000, 999999)}", 1)
    return out


def main() -> None:
    rows: list[tuple] = []

    # ── 30 days of normal noise ─────────────────────────────────
    for day in range(30):
        for svc in SERVICES:
            for _ in range(random.randint(40, 70)):
                ts = NOW - timedelta(
                    days=day,
                    hours=random.randint(0, 23),
                    minutes=random.randint(0, 59),
                    seconds=random.randint(0, 59),
                )
                level = "WARN" if random.random() < 0.04 else "INFO"
                msg = rand_fill(random.choice(NORMAL[svc]))
                rows.append((ts, svc, level, msg))

    # ── seeded historical incidents ─────────────────────────────
    incidents = []
    inc_num = 3800
    for key, pat in INCIDENT_PATTERNS.items():
        # each pattern occurred 1-2 times in the past 30 days
        for _ in range(random.randint(1, 2)):
            inc_num += random.randint(3, 40)
            occurred = NOW - timedelta(
                days=random.randint(3, 29),
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59),
            )
            for offset, (svc, level, msg) in enumerate(pat["chain"]):
                rows.append((
                    occurred + timedelta(seconds=offset * random.randint(20, 90)),
                    svc, level, msg,
                ))
                # repeat the error a few times, as real incidents do
                if level == "ERROR":
                    for r in range(random.randint(3, 12)):
                        rows.append((
                            occurred + timedelta(seconds=offset * 60 + r * 7),
                            svc, level, msg,
                        ))

            incidents.append((
                f"INC-{inc_num}",
                pat["title"],
                pat["signature"],
                pat["root_cause"],
                pat["resolution"],
                pat["root"],
                occurred,
            ))

    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE logs RESTART IDENTITY")
        cur.executemany(
            "INSERT INTO logs (ts, service, level, message) VALUES (%s,%s,%s,%s)",
            rows,
        )
        cur.execute("TRUNCATE past_incidents")
        cur.executemany(
            """INSERT INTO past_incidents
               (id, title, signature, root_cause, resolution, service, occurred_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            incidents,
        )
        conn.commit()

        print(f"loaded {len(rows)} log lines")
        print(f"loaded {len(incidents)} past incidents\n")

        cur.execute("SELECT level, count(*) FROM logs GROUP BY level ORDER BY 2 DESC")
        for lvl, n in cur.fetchall():
            print(f"  {lvl:<8} {n}")

        print()
        cur.execute(
            "SELECT service, count(*) FROM logs WHERE level='ERROR' "
            "GROUP BY service ORDER BY 2 DESC"
        )
        print("  errors by service:")
        for svc, n in cur.fetchall():
            print(f"    {svc:<20} {n}")


if __name__ == "__main__":
    main()
