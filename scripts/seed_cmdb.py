"""
Seed GLPI with a small service topology for the incident triage agent.

Creates one Computer per service, then wires dependency edges using
GLPI's Impact Analysis relations (ImpactRelation).

Run:  python seed_cmdb.py
"""

import os
import sys
import httpx
from dotenv import load_dotenv

load_dotenv()

BASE = os.getenv("GLPI_URL", "http://localhost:8080/api.php/v1")
APP_TOKEN = os.getenv("GLPI_APP_TOKEN")
USER_TOKEN = os.getenv("GLPI_USER_TOKEN")

if not APP_TOKEN or not USER_TOKEN:
    sys.exit("Set GLPI_APP_TOKEN and GLPI_USER_TOKEN in .env")


# ── the topology ────────────────────────────────────────────────
# (name, comment)
SERVICES = [
    ("payment-api",     "Public payment endpoint. Entry point for charges."),
    ("checkout-web",    "Customer-facing checkout UI."),
    ("auth-service",    "Token issuance and validation."),
    ("user-service",    "User profile reads."),
    ("notification-svc", "Email and SMS dispatch."),
    ("ledger-service",  "Double-entry ledger writes."),
    ("postgres-main",   "Primary transactional database."),
    ("postgres-replica", "Read replica of postgres-main."),
    ("redis-cache",     "Session and token cache."),
    ("kafka-broker",    "Event bus."),
    ("s3-receipts",     "Receipt object storage."),
    ("api-gateway",     "Edge routing and rate limiting."),
]

# (depends_on_source, target)  =>  source DEPENDS ON target
DEPENDENCIES = [
    ("checkout-web",     "api-gateway"),
    ("api-gateway",      "payment-api"),
    ("payment-api",      "auth-service"),
    ("payment-api",      "ledger-service"),
    ("payment-api",      "kafka-broker"),
    ("auth-service",     "postgres-main"),
    ("auth-service",     "redis-cache"),
    ("user-service",     "postgres-replica"),
    ("ledger-service",   "postgres-main"),
    ("notification-svc", "kafka-broker"),
    ("notification-svc", "s3-receipts"),
    ("postgres-replica", "postgres-main"),
]


# ── session handling ────────────────────────────────────────────
def init_session() -> str:
    r = httpx.get(
        f"{BASE}/initSession",
        headers={
            "Authorization": f"user_token {USER_TOKEN}",
            "App-Token": APP_TOKEN,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["session_token"]


def kill_session(session: str) -> None:
    httpx.get(f"{BASE}/killSession", headers=headers(session), timeout=30)


def headers(session: str) -> dict:
    return {
        "App-Token": APP_TOKEN,
        "Session-Token": session,
        "Content-Type": "application/json",
    }


# ── creation ────────────────────────────────────────────────────
def create_computer(session: str, name: str, comment: str) -> int:
    r = httpx.post(
        f"{BASE}/Computer",
        headers=headers(session),
        json={"input": {"name": name, "comment": comment, "entities_id": 0}},
        timeout=30,
    )
    r.raise_for_status()
    body = r.json()
    return body["id"] if isinstance(body, dict) else body[0]["id"]


def create_dependency(session: str, source_id: int, target_id: int) -> bool:
    """source depends on target."""
    r = httpx.post(
        f"{BASE}/ImpactRelation",
        headers=headers(session),
        json={
            "input": {
                "itemtype_source": "Computer",
                "items_id_source": target_id,
                "itemtype_impacted": "Computer",
                "items_id_impacted": source_id,
            }
        },
        timeout=30,
    )
    return r.status_code in (200, 201)


# ── main ────────────────────────────────────────────────────────
def main() -> None:
    session = init_session()
    print(f"session ok\n")

    ids: dict[str, int] = {}
    for name, comment in SERVICES:
        cid = create_computer(session, name, comment)
        ids[name] = cid
        print(f"  created  {name:<20} id={cid}")

    print()
    ok = 0
    for source, target in DEPENDENCIES:
        if create_dependency(session, ids[source], ids[target]):
            print(f"  edge     {source:<20} -> {target}")
            ok += 1
        else:
            print(f"  FAILED   {source:<20} -> {target}")

    print(f"\n{len(ids)} services, {ok}/{len(DEPENDENCIES)} edges")
    kill_session(session)


if __name__ == "__main__":
    main()
