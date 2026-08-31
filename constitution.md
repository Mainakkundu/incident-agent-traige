# Constitution

Rules that do not change. If this file conflicts with a coding agent's
suggestion or with what seems convenient in the moment — **this file wins**.

---

## 1. Business problem

An alert fires at 2am: payment-api error rate 12%, normally 0.3%. An engineer
opens the ticket, checks deploys, reads logs, finds timeouts to auth-service,
looks up what auth-service depends on, reads postgres logs, finds
max_connections reached. 30–45 minutes, most of it in the last three steps.

**The expensive part is finding the problem, not fixing it.**

**What this builds:** an agent that runs that investigation and writes root
cause, evidence chain and confidence back to the ticket — or escalates.

**Success test:** given an alert on a service that is a *victim*, the agent
names the true root cause and the chain connecting them.

---

## 2. Why an agent — and only in one place

**Alerting is a rules problem, already solved.** Investigation is a search
where the tree is discovered as you walk it: the logs mention auth-service, so
you go there. Had they said "disk full" you'd go elsewhere. Neither the number
of steps nor the choice of each is knowable in advance.

**Test applied to every component: does the next step depend on what the last
step returned?** No → deterministic code. Yes → agent.

| Step | Agent? |
|---|---|
| Fetch ticket, query logs, read dependencies, compute error rate | No |
| **Decide where to look next** | **Yes** |
| Write the justification | No — one LLM call |

One row in six. Building the rest as agents is over-engineering, and saying so
is part of the deliverable.

---

## 3. Scope

**In:** webhook ingestion · one supervisor with a ReAct loop · two MCP servers ·
CMDB graph traversal · semantic retrieval over past incidents and runbooks ·
confidence gate with HITL · approval-gated write-back · OTel tracing · eval
harness · chaos suite · container + CI.

**Out — do not let these creep in:** multi-agent crews · auto-remediation ·
anomaly detection · fine-tuning · a UI · streaming · >12 services · a running
K8s cluster as a dependency.

Rejected ideas go in `decisions.md` so they are not re-raised next week.

---

## 4. Data — decided, do not deviate

| Data | Store | Retrieval | Real? |
|---|---|---|---|
| Historical logs | Postgres GIN | exact, time-bounded | synthetic (§4.1) |
| Past incidents, runbooks | pgvector | semantic | synthetic |
| Service topology | GLPI CMDB | graph walk | invented |
| **Live failure logs** | Postgres | exact | **real** |
| Golden cases | `evals/goldens.yaml` | — | hand-labelled |

**Never put logs in a vector store.** Log queries are exact and time-bounded;
embeddings return similar lines from the wrong service at the wrong time.

### 4.1 Why the historical logs are synthetic — state this, don't hide it

Loghub HDFS was loaded and rejected: 2,000 lines, 1,920 INFO, 80 WARN, **zero
ERROR**, all Hadoop block-replication chatter. No bearing on pool exhaustion or
OOM kills.

**Synthetic data with correct causal structure beats real data from the wrong
domain.** The generated corpus has seven failure patterns, each a proper causal
chain with realistic inter-service delay. This appears in the README, not
buried.

---

## 5. Topology and failure patterns — fixed

12 services, 12 edges:

```
checkout-web → api-gateway → payment-api ─┬→ auth-service ─┬→ postgres-main
                                          │                └→ redis-cache
                                          ├→ ledger-service → postgres-main
                                          └→ kafka-broker
user-service → postgres-replica → postgres-main
notification-svc ─┬→ kafka-broker
                  └→ s3-receipts
```

| # | Pattern | Root | Difficulty |
|---|---|---|---|
| 1 | postgres connection exhaustion | postgres-main | 3-hop cascade |
| 2 | auth-service OOM | auth-service | must *stop*, not blame the DB |
| 3 | deploy regression | payment-api | requires the deploy log |
| 4 | redis eviction storm | redis-cache | WARN only, no ERRORs |
| 5 | kafka consumer lag | notification-svc | consumer, not broker |
| 6 | replica lag | postgres-replica | replica, not primary |
| 7 | s3 throttling | s3-receipts | external dependency |

An eighth pattern requires a golden case and a chaos script in the same commit.

---

## 6. Architecture

```
Alertmanager ──webhook──> FastAPI ──> Supervisor (LangGraph, ReAct, cap 15)
                                            │
                                    Confidence gate  ≥0.8 auto / else HITL
                                            │
                          MCP: observability   ·   MCP: ITSM (GLPI)
```

**One supervisor. No crews. Final.** Diagnosis writes to a ticket someone will
audit; peer-to-peer negotiation produces conclusions nobody can reconstruct.
Specialisation lives in the tools, not the reasoning.

**The MCP boundary is the point.** Everything above it is system-agnostic —
swapping GLPI for ServiceNow means rewriting six tool functions; the graph,
gate, evals and tracing don't change.

### Governance — enforced in code, never in the prompt

- **G1** Read tools free. Write tools require an approval token issued only by
  the gate or a human.
- **G2** Hard step cap 15. On cap-hit: best hypothesis, low-confidence flag,
  escalate.
- **G3** Every tool call logged with the trace ID.

---

## 7. Build sequence — non-negotiable order

```
infra → data → tools → agent → observability → API/trigger
      → evaluation → chaos → ship
```

**No phase starts before the one before it is finished.**

| # | Phase | Exit criteria |
|---|---|---|
| 0 | Infra | 4 containers up; GLPI `initSession` returns a token |
| 1 | Data | 12 CI + 12 edges; causal chain reads in correct order; 30 goldens written |
| 2 | Tools | 11 tools each callable **standalone, no agent**; write tools reject a missing token |
| 3 | Agent | gld_001 → `postgres-main` with the 3-hop chain; interrupt survives a restart |
| 4 | Observability | one trace per run, spans nested; `GET /runs/{id}` reconstructs an old run |
| 5 | API + trigger | webhook returns <200ms; a hand-broken service reaches the agent with no human |
| 6 | Evaluation | `REPORT.md` generated by pytest; both hard gates wired |
| 7 | Chaos | `make chaos-suite` — 6 faults, 6 correct, incl. "nothing is wrong" |
| 8 | Ship | green CI; README with measured numbers and stated limitations |

**Golden cases are written before the tools.** They decide what the tools must
return. Building tools first means discovering on day 2 that nothing is
verifiable.

**Every tool is tested standalone before the agent touches it.** A broken tool
looks exactly like a bad agent.

### Cut order if time runs short

Helm → Render deploy → 2 of 6 chaos scenarios (never the clean one) →
`search_runbooks` → `get_metric`.

**Never cut:** the two MCP servers, the 30 goldens, the E3 causal-validity
assertion, the audit endpoint.

---

## 8. Coding standards — non-negotiable

**C1. No nested functions.** No `def` inside a `def`. Ever. Shared state → a
class. Helper → a module-level function.

**C2. SOLID.**
- **S** — a client calls the API; it does not format prompts or score confidence.
- **O** — an eighth pattern must not require editing the supervisor. New
  behaviour from new data or tools, never new `if` branches in the graph.
- **L** — any `ToolClient` usable wherever the base is expected.
- **I** — a read-only client does not inherit a `write()` it raises on.
- **D** — the supervisor takes a tool registry, never a concrete `GLPIClient`.

**C3.** Every abstraction is a `Protocol` or `ABC` with typed signatures.
**C4.** No module-level mutable globals. Config is passed in.
**C5.** Type hints on every public function. Enforced in CI.
**C6.** If a docstring needs "and" for the return value, split it.
**C7.** No magic numbers. Step cap, thresholds, windows, DSNs → `config.py`.
**C8.** Secrets in `.env` only, gitignored before the first commit.

---

## 9. LangGraph style — official Graph API

Per `docs.langchain.com/oss/python/langgraph/quickstart`, **Graph API tab**.
Not the Functional API — explicit nodes and edges are what make the trace
readable, which is half the point.

**Tools:** `@tool` decorated. The docstring is a prompt — write it for the model.

```python
@tool
def get_ci_dependencies(service: str) -> list[str]:
    """Return the services that `service` directly depends on.

    Args:
        service: Configuration item name, e.g. "payment-api"
    """
    return CMDB.dependencies_of(service)
```

**State:** `TypedDict` with `Annotated` reducers. `services_seen` exists to
enforce §10 E3.

```python
class TriageState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    llm_calls: int
    services_seen: Annotated[list[str], operator.add]
    approval_token: str | None
```

**Nodes** take state, return a partial dict. **Routing lives in a conditional
edge, never inside a node.**

```python
def should_continue(state: TriageState) -> Literal["tool_node", "gate"]:
    """Route to tools if the model called one, else to the gate."""
    if state["llm_calls"] >= settings.max_steps:
        return "gate"
    return "tool_node" if state["messages"][-1].tool_calls else "gate"
```

**Graph assembled explicitly, compiled once**, `interrupt_before=["write"]` for
HITL — the graph genuinely pauses, not a polling loop.

Rules on top: the step cap is an **edge, not a prompt** (a prompt is a request;
an edge is a guarantee). A checkpointer is required. **One graph, no subgraphs**
without a `decisions.md` entry first.

---

## 10. Evaluation

| ID | Measures | Gate |
|---|---|---|
| E1 | Root cause vs goldens | **HARD** |
| E2 | Tool calls to conclusion, cap-hits | soft |
| E3 | Causal validity of the trail | **HARD** |
| E4 | False alarm rate on clean cases | soft |
| E5 | Summary quality (judge) | soft |
| E6 | Auto-resolution rate | headline |

**E1 is not one number.** Missing a real incident at 2am is far worse than a
false alarm. Report the confusion matrix; **gate on missed incidents, not
accuracy.** 90% with three misses is worse than 85% with none.

**E3 — the assertion almost nobody writes.** Every service the agent queried
must have appeared in an earlier tool result, or in the CMDB dependencies of a
service already seen. If `search_logs("auth-service")` fires before anything
mentioned auth-service, the agent guessed and got lucky. That is a failure even
when the answer is right.

**Judge health every run.** A judge is a classifier. Hand-label 30 summaries,
print TPR and TNR. If TPR drifts, every E5 number above it is fiction.

**Two hard gates in CI, not six.** Gate on seven thresholds and someone adds
`--skip-evals` within a month.

---

## 11. Nothing is claimed that isn't measured

- No README statement without a number from code in this repo on the stated
  golden set.
- The §4.1 synthetic-data decision appears in the README.
- Limitations listed, not omitted: in-memory checkpointer, 12-service topology,
  synthetic historical logs. A reader who finds an unlisted limitation trusts
  nothing else.
- **Two days is two days.** Presented as *"a working version against a real ITSM
  platform with a CMDB, real failing services, and an eval harness"* — never as
  production experience.

---

## 12. Conflict resolution

1. **§6 governance, §8 or §9 violated** → stop, fix, do not proceed.
2. **Agent performs worse than expected** → that is a *result*, not a bug.
   Record it. Do not tune the prompt until it passes — that is fitting to the
   test set.
3. **A phase runs long** → cut inside the phase (§7), never skip exit criteria.
4. **A better idea appears** → `decisions.md` as a candidate, not code today.
5. **An assistant suggests multi-agent, subgraphs or auto-remediation** → §3 and
   §6 already rejected these. Point and move on.
6. **Reality contradicts this document** → update it, dated entry in
   `decisions.md`. Never let code and constitution silently diverge.

---

## 13. Definition of done

One command runs the stack and produces:

1. An Alertmanager alert reaching the agent by webhook
2. Root cause, dependency chain, confidence
3. A trace showing every node, tool call, token count, latency
4. A diagnosis written back to GLPI, after an approval gate
5. `GET /runs/{id}` returning the full decision trail
6. `make chaos-suite` — 6 real faults, 6 correct conclusions
7. `evals/REPORT.md` from pytest, both hard gates passing
8. Green CI

If a reader can see all eight, the project stands on its own.
