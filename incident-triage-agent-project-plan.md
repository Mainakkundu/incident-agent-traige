# Incident Triage Agent — Project Plan

An agent that investigates production incidents the way an on-call engineer does: reads the alert, follows the trail, finds the root cause, writes it back to the ticket.

Built to demonstrate platform engineering, agentic orchestration, enterprise integration, observability and evaluation — end to end, on free infrastructure.

---

## 1. The business problem, in simple words

It's 2am. An alert fires: **"payment-api error rate is 12%, normally 0.3%."**

An engineer gets paged. Here's what they actually do:

1. Open the ticket. Which service? Since when?
2. Check if anyone deployed recently. *No deploys in 3 days.*
3. Read the logs. *Floods of connection timeouts to `auth-service`.*
4. So payment-api isn't broken — something it depends on is. Check what it depends on.
5. Read `auth-service` logs. *Connection pool exhausted.*
6. What does `auth-service` depend on? *Postgres.*
7. Read Postgres logs. *Max connections reached at 02:09.*
8. Has this happened before? *Yes — six weeks ago, a batch job wasn't releasing connections.*
9. Write it all up in the ticket, wake up the right team.

**That takes 30–45 minutes.** Most of it is step 4 onward — following a trail where each thing you find tells you where to look next.

### Why this is worth automating

- Every company with production software has this problem. There is no exception.
- It happens at the worst possible time, which is when humans are slowest and most error-prone.
- Mean time to resolution is a number every engineering org tracks and gets measured on.
- The expensive part isn't fixing the problem — it's *finding* it. Fixing is usually quick once you know.

### Why an agent, and not a rules engine

This is the important question and you should have the answer ready.

A rules engine handles alerting fine — "if error rate above X, page someone." It cannot do the investigation, because **the next thing to check depends on what the last check returned.**

You cannot pre-write the path. When the logs mention `auth-service`, you go look at `auth-service`. If they had mentioned a disk full, you'd go somewhere completely different. The number of steps, and the choice of each step, are only knowable at runtime.

That is the definition of an agent, and it's the only part of this system that needs to be one. Everything else — fetching logs, querying the CMDB, computing error rates — is plain code.

**The line to say in an interview:**
> "Alerting is a rules problem and it's solved. Investigation is a search problem where the search tree is discovered as you walk it. That's the only part I made agentic — everything else is deterministic tools."

---

## 2. Where the data comes from

Three sources, three different jobs. Being able to explain why each one is the right *style* of retrieval for its data is the strongest single thing about this project.

### 2.1 Historical logs — Loghub (public, free)

**What:** A curated collection of 19 real-world system log datasets — distributed systems, supercomputers, operating systems, server applications. Mostly unsanitised production data. Used by IBM, Microsoft, Nvidia, Elastic and Splunk, downloaded ~90,000 times.

**Where:** `github.com/logpai/loghub` — grab the 2k sample sets, not the 77GB full archive.

**Which datasets:**
| Dataset | Why |
|---|---|
| **HDFS_v1** | Ships with **labelled anomaly blocks** — this is your golden set, free |
| **BGL** | Supercomputer logs with alert tags; adds a second system for realism |

**Job:** historical corpus. Feeds the past-incident RAG store and the eval harness.

**Citation to include in the README:**
> Zhu, He, He, Liu, Lyu. *Loghub: A Large Collection of System Log Datasets for AI-driven Log Analytics.* IEEE ISSRE, 2023.

### 2.2 Live logs — your own failing services

Loghub is history. For the demo you need **something you can actually break.**

Run two toy services in the compose stack:
- `payment-api` — calls auth-service, logs structured JSON
- `auth-service` — holds a Postgres connection pool, logs structured JSON
- a traffic generator hitting payment-api at ~5 rps

Now real failures produce real logs with real timestamps. When the agent gets it right, you know it read the system rather than your fixtures.

### 2.3 Service topology — GLPI CMDB

**What:** GLPI is an open-source ITSM platform. Ticketing tied to a CMDB — asset and configuration-item inventory with relationships between items. A pure ticketing system tells you a user reported a problem; GLPI ties the problem to the service, device or configuration item behind it.

**Job:** the dependency graph the agent walks. This is what makes the agent agentic — `get_ci_dependencies()` is a lookup it couldn't have planned in advance.

**Seed it small:** 12–15 configuration items with dependency edges. A fake but coherent topology is fine. The agent needs a graph to walk, not an accurate one.

**Why GLPI and not Zammad:** Zammad has a cleaner REST API but no CMDB. The CMDB is the whole point here.

**Bonus positioning:** GLPI is effectively open-source ServiceNow. "I built an incident triage agent against an ITSM platform with a CMDB" is a sentence that lands in every interview.

### 2.4 Data → retrieval style mapping

```
Loghub + live logs   →  Postgres full-text (GIN index)  →  search_logs
                        exact, structured, time-bounded

Past incidents       →  pgvector embeddings             →  get_similar_incidents
Runbooks (12 .md)    →  pgvector embeddings             →  search_runbooks
                        semantic — "pool exhausted" must match "too many connections"

GLPI CMDB            →  REST + graph traversal          →  get_ci_dependencies
                        relational walk, not retrieval

30 labelled HDFS     →  held out, never indexed         →  eval harness only
anomaly blocks
```

**Do not put logs in a vector store.** Log search is exact: "errors for this service in these 15 minutes." Embeddings make it *worse* — you get semantically similar logs from the wrong service at the wrong time. Say this out loud; plenty of candidates reflexively vectorise everything.

---

## 3. High-level architecture

### 3.1 System view

```
   Prometheus ──► Alertmanager
                       │ webhook POST
                       ▼
          ┌────────────────────────────┐
          │  FastAPI service           │
          │  POST /webhooks/incident   │ 202 + run_id, work in background
          │  POST /runs/{id}/approve   │
          │  GET  /runs/{id}           │
          └─────────────┬──────────────┘
                        ▼
          ┌────────────────────────────┐
          │  Supervisor (LangGraph)    │  ReAct — decides next tool
          │  hard step cap: 15         │
          └─────────────┬──────────────┘
                        ▼
          ┌────────────────────────────┐
          │  Confidence gate           │  ≥0.8 auto-write, else HITL
          └─────────────┬──────────────┘
              ┌─────────┴─────────┐
              ▼                   ▼
      ┌──────────────┐    ┌──────────────┐
      │ MCP Server A │    │ MCP Server B │
      │ Observability│    │ ITSM (GLPI)  │
      └──────┬───────┘    └──────┬───────┘
             ▼                   ▼
      Postgres/pgvector      GLPI + MariaDB
      (logs, incidents,      (tickets, CMDB)
       runbooks)
```

### 3.2 Why supervisor-ReAct and not a multi-agent crew

One reasoning loop, one decision path, fully logged. Debugging an incident triage system that itself needs debugging is a bad place to be — peer-to-peer agent negotiation produces conclusions nobody can reconstruct.

**Sub-agents are unnecessary here** because all the specialisation lives in the tools, not in the reasoning. There is only one job: figure out what broke.

Say this if challenged: *"I considered specialist agents per data source, but the specialisation is in the tool layer. Adding agents would have added coordination overhead and removed the single auditable decision path."*

### 3.3 Two MCP servers — the design point

```
MCP Server A — Observability        MCP Server B — ITSM (GLPI)
  search_logs(service, window,        get_ticket(id)
             level, keyword)          get_ci(ci_id)
  get_error_rate(service, window)     get_ci_dependencies(ci_id)   ← graph walk
  get_recent_deploys(service, hrs)    get_similar_incidents(sig)   ← RAG
  get_metric(name, window)            search_runbooks(query)       ← RAG
                                      update_ticket(id, diagnosis) ← WRITE, gated
                                      close_ticket(id, reason)     ← WRITE, gated
```

**Two servers over two systems is a stronger claim than one.** It shows MCP understood as an abstraction boundary, not a wrapper. Swap GLPI for ServiceNow and only Server B changes — the graph, the evals and the observability are untouched.

### 3.4 Two governance rules

**Read tools are free. Write tools require an approval token** issued only by the HITL gate. The agent physically cannot modify a ticket without either high confidence or a human click. Most candidates have no governance answer at all; this is yours.

**Hard step cap of 15.** An unbounded investigation loop against live systems is an incident, not a feature. On cap-hit, emit the best hypothesis with a low-confidence flag and escalate.

### 3.5 One worked trace

```
02:14  Alertmanager fires → POST /webhooks/incident

 1  get_ticket(INC-4471)               payment-api, 12% errors, since 02:11
 2  get_recent_deploys(payment-api)    none in 3 days      → not a deploy
 3  search_logs(payment-api, 02:00-15) timeouts to auth-service
 4  get_ci_dependencies(payment-api)   auth-service, postgres-main, redis
 5  search_logs(auth-service, ...)     connection pool exhausted
 6  get_ci_dependencies(auth-service)  postgres-main
 7  search_logs(postgres-main, ...)    max connections reached 02:09
 8  get_similar_incidents("postgres    INC-3902, 6 wks ago, same signature
    max connections")
 9  search_runbooks("postgres max      runbook RB-07
    connections")

    Root cause : postgres-main hit max_connections at 02:09
    Chain      : postgres-main → auth-service → payment-api
    Prior      : INC-3902 — batch job not releasing connections
    Suggested  : RB-07, check batch job connection cleanup
    Confidence : 0.87  → auto-write to ticket

    9 tool calls, ~40 seconds.
```

Note steps 5 and 7: it only knew to look at `auth-service` *because* step 3 said so, and at `postgres-main` *because* step 5 said so. That is the agentic property, and it's the thing to point at on a screen-share.

---

## 4. Tech stack

### 4.1 Containers — four plus two toys

```yaml
services:
  glpi           # ITSM + CMDB                    :8080
  glpi-db        # MariaDB 10.11 (GLPI dependency)
  pgvector       # logs + vectors (pgvector/pgvector:pg16)  :5432
  phoenix        # tracing UI (arizephoenix/phoenix)        :6006
  payment-api    # toy service to break                     :9001
  auth-service   # toy service to break                     :9002
  prometheus     # metrics + alert rules                    :9090
  alertmanager   # webhook sender                           :9093
```

**Why pgvector, not OpenSearch:** one container does both jobs. Postgres full-text search handles the log queries; pgvector handles the embeddings. OpenSearch would be a second heavy container for no gain at this scale.

### 4.2 Python

```
langgraph                  orchestration
langchain-core
fastapi + uvicorn          API surface
pydantic                   structured tool I/O
httpx                      GLPI REST client
mcp                        MCP servers
psycopg[binary] + pgvector data layer
anthropic (or openai)      LLM
arize-phoenix-otel         tracing
openinference-instrumentation-langchain
pytest                     eval harness
python-dotenv
```

### 4.3 Prerequisites

```
Docker Desktop   ≥6GB RAM allocated
Python 3.11+
Git
kind + helm      optional, only for the K8s claim
```

### 4.4 Repo layout

```
incident-triage-agent/
├── docker-compose.yml
├── Dockerfile
├── Makefile                      make up / chaos-suite / eval
├── helm/                         chart (counts even if never deployed)
├── .github/workflows/ci.yml
├── src/
│   ├── api.py                    FastAPI, 3 endpoints
│   ├── graph.py                  LangGraph supervisor
│   ├── mcp_observability.py      MCP Server A
│   ├── mcp_itsm.py               MCP Server B
│   ├── gate.py                   confidence + approval tokens
│   └── db/                       schema, loaders, embeddings
├── services/                     payment-api, auth-service toys
├── chaos/                        6 fault injection scripts
├── evals/
│   ├── goldens.yaml              30 labelled cases
│   ├── test_evals.py
│   └── REPORT.md                 regenerated by pytest
└── README.md                     architecture diagram + eval output
```

---

## 5. Observability

Three layers. All free, all already installed.

### 5.1 Trace layer — per incident

One trace per incident. Spans for the supervisor decision, each tool call, the gate, each write.

Span attributes to set explicitly:
```
service_investigated, time_window, tool_name,
tokens_in, tokens_out, model, latency_ms,
step_number, hypothesis_at_this_step, confidence,
retrieval_style  (fulltext | vector | graph)
```

`retrieval_style` is the one worth adding. It lets you answer "which retrieval mode actually contributes to correct diagnoses?" — a question most people can't even ask of their own system.

### 5.2 Aggregate layer — dashboard

- Tool calls per incident (histogram) — creeping up means degrading reasoning
- Cost and latency per incident, split by tool
- Confidence distribution, and auto-write vs escalate ratio
- Tool error rate per tool
- Cap-hit count

### 5.3 Drift layer — weekly

**Escalation rate.** Share of incidents falling below the confidence threshold. If it climbs, either the systems changed or the runbook corpus went stale. Cheapest early-warning signal available and it costs nothing to compute.

### 5.4 The audit endpoint

```
GET /runs/{id}   →  full decision trail
```

Every tool called, every result, the hypothesis at each step, final confidence, who approved, when. Six months later someone asks "why did the agent blame Postgres?" — this answers it.

This is what makes it enterprise software rather than a demo, and it's the endpoint an interviewer will notice.

---

## 6. Deployment

### 6.1 Local — the real environment

```bash
make up          # docker compose up, all 8 services
make seed        # GLPI CMDB items, load Loghub, build embeddings
make verify      # 10-step smoke test (see §8.1)
```

### 6.2 Containerised agent service

```dockerfile
FROM python:3.11-slim
# uvicorn, port 8000, non-root user, healthcheck on /health
```

### 6.3 CI/CD — GitHub Actions

```
on: push
  1. lint + type check
  2. unit tests (tools tested standalone)
  3. spin up pgvector service container
  4. run eval harness on 30 goldens
  5. fail the build if E1 missed-incidents > 1
  6. build + push image
```

**Gate on one metric only.** Missed incidents. If CI fails on six different thresholds, someone adds `--skip-evals` within a month and then there is no gate at all.

### 6.4 Public deploy — Render free tier

Render is the only major PaaS with an ongoing free option; free services spin down after 15 minutes idle and take 30–60s to wake. Railway and Fly.io have no permanent free tier — skip both.

Deploy **only the agent service**, pointed at recorded fixtures. GLPI and Postgres stay local. Nobody will click the link; the deploy exists so you can say *"containerised and deployed through CI/CD,"* which is a JD line.

### 6.5 Kubernetes — optional

Helm chart in `helm/`: deployment, service, ingress, configmap, secret, liveness/readiness probes, HPA. Run it on `kind` locally if day 2 goes well.

**A chart in the repo counts for the JD even if you never run a cluster.** Do not spend day 2 on this.

---

## 7. Integration

### 7.1 Trigger — webhook, production-shaped

```
Prometheus alert rule
      │
Alertmanager  ──webhook──►  POST /webhooks/incident
                                  │
                            202 Accepted + run_id     ← immediately
                                  │
                            background task → LangGraph
```

**Return 202 immediately.** A webhook that blocks 40 seconds gets retried by the sender and you process the same incident three times.

**Idempotency key on the alert fingerprint.** Retries must not double-fire.

### 7.2 GLPI integration

```
1. POST /apirest.php/initSession   with app_token + user_token → session_token
2. all calls carry Session-Token header
3. POST /apirest.php/killSession    on shutdown
```

Read: `Ticket`, `Computer`, `Software`, `Computer_Item` (dependency edges).
Write: `Ticket` followup + status change — **approval token required**.

**Gotcha:** GLPI's web installer is a multi-step wizard that must complete before the REST API works, and the app token is generated in the admin UI afterwards. Do this first, while fresh.

### 7.3 The swappability claim

```
Everything above the MCP boundary is system-agnostic.
Replacing GLPI with ServiceNow or Jira Service Management
means reimplementing 6 tool functions in mcp_itsm.py.
The graph, the gate, the evals and the tracing do not change.
```

This is the sentence that makes it a *platform* project rather than an app.

---

## 8. Testing — how you know it works end to end

### 8.1 Smoke test — is everything wired?

Run in order. Do not skip ahead when one fails.

| # | Check | Pass |
|---|---|---|
| 1 | `docker compose ps` | all healthy |
| 2 | `curl .../initSession` | GLPI session token |
| 3 | log query, service + 15min window | rows in <1s |
| 4 | `get_ci_dependencies("payment-api")` | 3 dependencies |
| 5 | vector search "connection pool exhausted" | returns INC-3902 |
| 6 | **each MCP tool standalone, no agent** | all 9 valid |
| 7 | graph on one scenario | ~9 calls, correct root cause |
| 8 | Phoenix | one trace, spans nested |
| 9 | approve → `curl` the GLPI ticket | diagnosis present |
| 10 | `pytest` | REPORT.md regenerates |

**Step 6 is the one people skip and regret.** A broken tool looks exactly like a bad agent, and you'll spend two hours tuning a prompt to fix a SQL bug.

### 8.2 Chaos suite — break it for real

Don't inject fake data. Kill actual services.

| Fault | How | Expected conclusion |
|---|---|---|
| Connection exhaustion | `ALTER SYSTEM SET max_connections=5` + reload | postgres → auth → payment chain |
| Upstream dead | `docker stop auth-service` | auth down, payment is a victim |
| Config regression | env `FAIL_RATE=0.3`, restart | recent config change |
| Slow dependency | `tc qdisc add dev eth0 root netem delay 2000ms` | latency, not errors |
| Resource starvation | `docker update --memory 64m auth-service` | OOM |
| **Nothing wrong** | fire a false alert on a healthy system | **no incident found** |

```bash
make chaos-suite
```
inject → wait for alert → agent runs → assert root cause → assert trail valid → revert → next.

Output is a six-row table. That's your end-to-end evidence, and it's the artifact to screen-share.

### 8.3 The four correctness gates

Beyond "did it answer":

**1. The trail is causally valid.**
Parse the trace. Assert every service the agent queried appeared in an earlier tool output or in the CMDB dependency list. If `search_logs("auth-service")` fires before anything mentioned auth-service, the agent guessed and got lucky.

*This is the single best correctness test for an agent and almost nobody writes it.*

**2. It changes its mind when you change the world.**
Same alert, different injected fault → different root cause. If stopping `auth-service` still produces "Postgres," it's pattern-matching the prompt.

**3. It shuts up when nothing is wrong.**
False alert on a healthy system → "no root cause identified, closing as false positive." An agent that always finds something is worse than no agent.

**4. The write actually landed — and refuses without approval.**
`curl` the ticket directly, not the UI. And confirm the write tool rejects a call with no approval token.

### 8.4 Eval harness — 30 goldens

Built from held-out labelled HDFS anomaly blocks plus the six chaos scenarios.

```
30 golden cases

E1  root cause correct        26/30    86.7%
      missed incidents   1   ← HARD GATE
      wrong root cause   3
E2  tool calls to answer      mean 7.4   cap-hits 0
E3  CMDB traversal correct    28/30
E4  false alarm rate          0/8 clean cases
E5  summary quality (judge)   0.88
E6  auto-resolved             22/30    73.3%

JUDGE HEALTH   E5 judge vs 30 human labels:  TPR 0.90  TNR 0.93
GATE: PASS
```

**The asymmetry, and why it matters.**
Missing a real incident at 2am is far worse than a false alarm that wakes someone unnecessarily. So E1 is not one accuracy number — report the confusion matrix and gate specifically on **missed incidents**. Not overall accuracy.

**Judge health printed every run.** E5 uses an LLM judge, so the judge is itself a classifier needing validation. Hand-label 30 summaries, report TPR and TNR against your labels. If TPR drifts, every E5 number above it is fiction.

---

## 9. Build sequence

### Day 1

**Morning — infrastructure up**
- compose stack running, all 8 services healthy
- GLPI installer completed, app token generated
- 12–15 CMDB items seeded with dependency edges
- *Checkpoint: `curl` a CMDB item and get dependencies back*

**Afternoon — data + tools**
- Loghub HDFS into Postgres, GIN index on message
- past-incident and runbook embeddings into pgvector
- 30 goldens written into `evals/goldens.yaml`
- both MCP servers, all 9 tools, **each tested standalone**
- *Checkpoint: every tool returns valid data with no agent involved*

### Day 2

**Morning — the agent**
- LangGraph supervisor, ReAct loop, step cap 15
- confidence gate + approval tokens
- FastAPI: webhook, approve, audit endpoints
- toy services + Prometheus/Alertmanager wired to the webhook
- *Checkpoint: real alert → real investigation → correct root cause*

**Afternoon — make it real**
- Phoenix tracing with custom span attributes
- 6 chaos scripts + `make chaos-suite`
- eval harness, REPORT.md generated
- Dockerfile, GitHub Actions, Render deploy, Helm chart
- README with architecture diagram and eval output

### If you slip, cut in this order

1. Helm chart
2. Render deploy
3. BGL as second dataset
4. two of the six chaos scenarios
5. `search_runbooks` (keep `get_similar_incidents`)

**Never cut:** the two MCP servers, the 30 goldens, the causal-validity assertion, the audit endpoint. Those four are what make this a platform project instead of a demo.

---

## 10. The screen-share script

> "Three windows. Left is the agent working — watch it decide where to look next based on what it just found. Middle is Phoenix: every tool call, token count, latency. Right is the ITSM system, and when I approve, the diagnosis writes back there.
>
> Here's the eval report — 30 labelled cases, gated on missed incidents rather than overall accuracy, because a miss at 2am is the error that actually costs you.
>
> And here's `make chaos-suite` — six real faults injected into running services, six correct root causes, including one case where the correct answer is *nothing is wrong.*"

Thirty seconds, and it covers agent design, observability, enterprise integration, governance and evaluation.

---

## 11. Interview answers to have ready

**"Why an agent and not a rules engine?"**
Alerting is a rules problem and it's solved. Investigation is a search problem where the tree is discovered as you walk it — the next check depends on the last result. Only that part is agentic; the tools are all deterministic.

**"Why one agent and not a crew?"**
The specialisation lives in the tools, not the reasoning. There's one job: find what broke. Adding agents would add coordination overhead and destroy the single auditable decision path — which matters because this system writes to a ticket someone will audit later.

**"Why not vector search on the logs?"**
Log queries are exact and time-bounded. Embeddings would return semantically similar logs from the wrong service at the wrong time. Vectors are right for past incidents and runbooks, where "pool exhausted" must match "too many open connections."

**"How do you stop it doing something expensive or wrong?"**
Hard step cap. Write tools require an approval token only the gate issues. Low confidence escalates regardless of what the agent concluded.

**"How do you know it works?"**
Six real faults injected into running services, plus 30 labelled cases in CI. I assert the reasoning trail is causally valid — every service queried must have been named by an earlier result — because an agent that guesses right is still broken.

**"How would this scale to a customer?"**
Everything above the MCP boundary is system-agnostic. Swapping GLPI for ServiceNow means reimplementing six tool functions. The graph, the evals and the tracing don't change. That boundary is the reason MCP is there.

---

## 12. One honest framing

Two days is two days. Don't present this as production experience.

> "I wanted to understand the integration surface properly, so I built a working version against a real ITSM platform with a CMDB, real failing services, and an eval harness."

That framing is stronger than overclaiming, because it demonstrates exactly the behaviour the role hires for: take an environment, map a business problem onto it, ship something that runs.
