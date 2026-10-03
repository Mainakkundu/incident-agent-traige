# The Expensive Part of an Incident Is Finding the Problem

## Building a bounded, auditable incident-triage agent without turning the entire system into an agent

At 2:14 a.m., an alert says `payment-api` is returning errors at 12 percent.
The normal rate is 0.3 percent.

The page names `payment-api`, but that does not mean `payment-api` is broken.
It may be the first visible victim in a longer failure chain.

An experienced on-call engineer does not immediately restart the service. They
check recent deployments, inspect logs, follow upstream dependencies, compare
the symptoms with previous incidents, and look for a runbook. Each result
changes the next question.

That investigation is the part I wanted to model.

Not alerting. Alerting is already a rules problem. Not remediation either; an
incorrect diagnosis should not be allowed to restart databases or roll back
deployments. The scope is narrower: gather evidence, identify the likely root
cause, explain the causal chain, and write the result to the ticket only when
policy permits it.

This distinction shaped the whole architecture.

> The agent decides where to look next. Everything else is ordinary software.

![Incident triage architecture](incident-triage-architecture-simple.png)

The dotted boundary is the engineering harness around the model: state, typed
tools, limits, policy, human approval, evaluation hooks, and tracing. The
supervisor remains the only component choosing the next investigation step.

## The boundary matters more than the model

It is tempting to describe an incident platform as a collection of agents: a
log agent, a metrics agent, a CMDB agent, a runbook agent, and a manager agent
coordinating them. That creates an impressive diagram and a difficult system.

The specialist behavior in this project does not require specialist agents.
Searching a bounded log window is a deterministic operation. Reading a
dependency edge is a deterministic operation. Calculating an error rate is a
deterministic operation. Updating a ticket is also deterministic and should be
more constrained, not more autonomous.

The only question that benefits from an agentic loop is this:

**Given the evidence collected so far, what should I inspect next?**

The implementation therefore uses one LangGraph supervisor and two MCP tool
servers. The supervisor owns the investigation path. The tools own integration
with operational systems.

```text
Alert -> Incident API -> Single LangGraph supervisor
                              |              |
                              v              v
                     Observability MCP   ITSM/CMDB MCP
                              |              |
                              v              v
                       Postgres/pgvector    GLPI
                              \\              /
                               -> Phoenix <-

Supervisor -> confidence and approval gate -> ticket update or human review
```

There is no peer-to-peer agent negotiation. An incident diagnosis may be
reviewed weeks later, so a single reconstructable decision path is more useful
than a conversation among agents whose combined conclusion is hard to explain.

## A concrete investigation

Consider the original alert on `payment-api`.

The investigation proceeds like this:

1. Search `payment-api` logs for the incident window.
2. Find repeated timeouts to `auth-service`.
3. Read the CMDB dependencies for `payment-api`.
4. Confirm that `auth-service` is upstream.
5. Search `auth-service` logs.
6. Find connection-pool exhaustion.
7. Read the dependencies for `auth-service`.
8. Discover `postgres-main`.
9. Search `postgres-main` logs and find `too many clients` errors.

The result is not merely “Postgres is down.” It is a causal statement:

```text
postgres-main connection exhaustion
    -> auth-service pool exhaustion
    -> payment-api upstream timeouts
```

The important behavior is in steps three through eight. The supervisor did not
know the complete path when the run began. The next service came from the
previous tool result.

In the deterministic golden run, the system returns `postgres-main` as the root
cause with a confidence of `0.87`, then reaches the write-approval gate.

## Retrieval is not one problem

One of the easiest architectural mistakes in an AI system is to put every form
of data into a vector database. It simplifies the slide. It also weakens the
system.

Different operational questions need different retrieval semantics.

| Question | Retrieval method |
|---|---|
| “Show errors from `auth-service` between 02:09 and 02:14” | Exact, service-scoped, time-bounded full-text search |
| “Has a similar failure happened before?” | Vector similarity over past incidents |
| “Which runbook discusses pool exhaustion?” | Vector similarity over runbooks |
| “What does `auth-service` depend on?” | Directed CMDB graph traversal |

Logs are not embedded in this design. A semantically similar exception from
the wrong service or the wrong week is not evidence for the current incident.
Service identity and time are part of the query, not optional metadata to be
recovered after similarity search.

Past incidents and runbooks are different. Equivalent failures are often
described with different words, so semantic retrieval is useful there.

The CMDB is different again. Dependency direction is relational. If service A
depends on service B, reversing that edge changes the diagnosis. Similarity is
irrelevant.

The broader lesson is simple: retrieval architecture should follow data
semantics, not whichever AI component is currently fashionable.

## MCP is an integration boundary, not an agent strategy

The project exposes two MCP servers.

The observability server provides four read tools:

- search logs;
- calculate error rate;
- retrieve recent deploys;
- retrieve metric samples.

The ITSM server provides seven tools:

- read a ticket;
- read a configuration item;
- traverse direct dependencies;
- retrieve similar incidents;
- search runbooks;
- update a ticket;
- close a ticket.

The separation follows system ownership. Observability data comes from the
log and metric store. Tickets and topology come from GLPI and its CMDB.

Above that boundary, the supervisor knows tool contracts, not client
implementations. Replacing GLPI with ServiceNow should require a new adapter,
not a new reasoning graph or evaluation suite.

This is where typed ports matter. Read and write interfaces are separate. The
supervisor receives a registry of tools. A client is responsible for making an
API call; it is not responsible for formatting prompts or deciding confidence.

That separation is less exciting than another agent. It is also what makes the
system maintainable.

## Bounded autonomy is an engineering property

Prompts are useful for shaping behavior. They are not sufficient for enforcing
policy.

This system has a hard limit of 15 model steps. The limit is implemented as a
conditional edge in the LangGraph state machine. When the counter reaches the
limit, execution routes to the confidence gate. The model cannot talk its way
around it.

The same principle applies to writes.

Read tools are freely callable during an investigation. Write tools require an
approval token in their typed function signature. A missing token is rejected
by code. High confidence may allow the gate to issue a token with expiry
metadata, but the graph still pauses before the write node. A low-confidence
or uncertain diagnosis is escalated.

There is an important limitation in the current implementation: the writer
checks that a token is non-empty, but does not yet verify its provenance,
scope, expiry, or reuse. That is sufficient to test the control flow, not to
serve as a production authorization mechanism. A production token must be
server-validated, action-scoped, short-lived, and single-use.

The current policy is:

- confidence at or above `0.80`, with sufficient evidence: eligible for write;
- confidence below `0.80`: escalate;
- incomplete or explicitly uncertain diagnosis: escalate;
- hard step cap reached: escalate regardless of confidence.

The exact threshold will eventually need calibration against evaluation data.
The architectural point is that the threshold and capability check live in
deterministic code.

This leads to a useful rule for operational agents:

> Put behavioral guidance in prompts. Put safety guarantees in code and state transitions.

## The final answer is not the audit trail

An incident ticket containing “root cause: `postgres-main`” is not enough.

An operator needs to know:

- which services were inspected;
- which tools were called;
- which arguments were used;
- what each tool returned;
- what hypothesis motivated the next step;
- whether the loop hit its cap;
- how confidence was calculated and gated;
- whether a human approved the write.

Each incident therefore has a stable `run_id`. OpenTelemetry spans record the
supervisor path, tool arguments, bounded result previews, retrieval style,
hypothesis, latency, final diagnosis, and gate decision. Phoenix stores those
spans.

The read side is deliberately simple:

```text
GET /runs/{run_id}
```

The endpoint finds the root span by `incident.run_id`, loads the complete trace,
and reconstructs the decision trail. It returns approval state but never the
approval token.

This endpoint changes the nature of the system. Without it, the agent produces
an answer. With it, the system produces an answer that can be investigated.

## Evaluating the path, not only the answer

The repository contains 30 labelled cases: incident cases, clean cases,
concurrent failures, inconclusive cases, and efficiency cases. The evaluation
harness is the next major phase, but its contracts were defined before the
agent implementation.

Root-cause accuracy will be one measure, not the only measure.

The more interesting assertion is causal validity.

If the agent searches `auth-service` before an alert, a log line, or a CMDB edge
has mentioned `auth-service`, it guessed. The final root cause may still be
correct, but the investigation is not valid. A lucky answer should not pass an
operational evaluation.

The planned evaluation set covers:

- root cause and missed incidents;
- tool calls and step-cap hits;
- causal validity of every service transition;
- false alarms on clean cases;
- summary quality;
- the percentage of runs eligible for automatic write.

CI will have two hard gates: missed incidents and causal validity. The other
metrics will be reported. Too many hard thresholds tend to produce one outcome:
someone eventually bypasses the entire evaluation job.

There is another asymmetry worth preserving. Missing a real incident at 2 a.m.
is more costly than escalating a clean case. “Accuracy” hides that asymmetry,
so the report must include the confusion matrix rather than a single score.

## Synthetic data, stated plainly

The current historical log corpus is synthetic: 19,654 lines across seven
causal failure patterns.

That was not the original plan. I first sampled a public HDFS log dataset. It
contained 2,000 lines, including 1,920 informational messages, 80 warnings, and
no errors. It was real data from the wrong operational domain.

Using it would have improved the project's description and weakened the
project itself.

The generated corpus is not passed off as production data. Its value is that
the temporal and causal relationships are controlled: a database failure
precedes pool exhaustion, which precedes downstream timeout errors. That makes
the investigation path testable.

Synthetic data with explicit limitations is more credible than unrelated real
data used for appearance.

## What exists today

As of 3 October 2026, the repository contains:

- four running infrastructure services: MySQL, GLPI, Postgres/pgvector, and Phoenix;
- a 12-service CMDB topology with 12 directed edges;
- two MCP servers exposing 11 independently tested tools;
- a single-supervisor LangGraph with a required checkpointer and hard step cap;
- a confidence gate, approval-token metadata, and a human-in-the-loop interrupt;
- a verified three-hop golden investigation ending at `postgres-main`;
- OpenTelemetry instrumentation and a Phoenix-backed run-audit endpoint;
- 106 passing unit tests.

The following pieces are not complete and should not be implied otherwise:

- Alertmanager webhook ingestion and idempotent background execution;
- the approval API;
- live toy services and traffic generation;
- Prometheus integration;
- the evaluation report and CI gates;
- the six-scenario chaos suite;
- container packaging, CI, Helm, and public deployment.

One local integration defect is also open. Phoenix acknowledges new OTLP span
exports, but those exported spans are not currently queryable. The audit API
has been verified against a trace persisted through the Phoenix client, but
reliable OTLP ingestion must be fixed before the tracing path is called done in
a production sense.

That distinction—working code versus completed system—is intentional.

## What I would harden before production

The development version uses an in-memory graph checkpointer. A production
deployment needs durable checkpoints, a work queue, and idempotent ticket
writes.

It also needs controls that are easy to omit in an agent prototype:

- webhook authentication and replay protection;
- secret management and rotation;
- redaction of credentials and personal data before model calls;
- per-tool timeouts, retries, and circuit breakers;
- dead-letter handling for runs that cannot progress;
- prompt and model versioning on every trace;
- bounded tool results before they enter model context;
- trace and evidence retention policies;
- backup and restore tests for operational state;
- capacity limits for concurrent investigations.

The model is one dependency in that list. It is not the architecture.

## The engineering lesson

The useful question when designing an agentic system is not “Where can I add an
agent?” It is “Which decision genuinely cannot be determined until runtime
evidence arrives?”

For incident triage, that decision is where to look next.

Once that boundary is clear, the rest of the system becomes familiar
engineering: typed interfaces, retrieval chosen by data shape, bounded state
transitions, capability-based writes, durable execution, traces, audits, and
evaluation against failure costs.

That is a less theatrical architecture than a crew of autonomous agents.

It is also one I would be willing to put on an incident path.
