# AGENT.md

Read `constitution.md` first. It wins every conflict. This file is only:
how to work, and what is done.

---

## How to work

1. Find the first unticked step below.
2. Do **only** that step.
3. Meet its exit criteria (constitution §7) before ticking.
4. Deviated from the constitution? Dated entry in `decisions.md`. Silent
   deviation is the failure this file exists to prevent.
5. Unsure? Ask. Do not guess, do not expand scope.

## Traps

| Temptation | Rule |
|---|---|
| "Add a researcher agent and an analyst agent" | §6 — one supervisor. Final. |
| "Helper `def` inside this function" | C1 — never |
| "The prompt says stop after 15 steps" | §9 — cap is an edge, not a prompt |
| "Test the tools through the agent" | §7 — standalone first |
| "Tests once it works" | §7 — tests ship with the code |
| "Make it auto-fix the problem" | §3 — diagnosis only |
| "Tune the prompt until the eval passes" | §12.2 — that's fitting the test set |
| "90% accuracy, good enough" | §10 — gate on missed incidents |
| "Functional API is shorter" | §9 — Graph API |

---

## Status

```
0 Infra          ██████  done
1 Data           ██████  done
2 Tools          ░░░░░░  ← here
3 Agent          ░░░░░░
4 Observability  ░░░░░░
5 API + trigger  ░░░░░░
6 Evaluation     ░░░░░░
7 Chaos          ░░░░░░
8 Ship           ░░░░░░
```

### 0 — Infra ✅

- [x] Docker Desktop — 7 CPU / 8GB / 128GB
- [x] Python 3.14.7 — *system 3.9 can't parse `X | None`; venv rebuilt*
- [x] 4 containers: db, glpi, pgvector, phoenix
      *No `name:` key in docker-compose.yml — it renames volumes and orphans
      data. A stale GLPI project held port 8080; removed.*
- [x] GLPI installed, glpi/glpi
- [x] API + tokens working
      *Legacy API is `/api.php/v1`, not `/apirest.php` — moved in GLPI 11.
      `are_apiclients_tokens_encrypted=1`, so tokens can't be read or set via
      the DB. The UI is the only way.*

### 1 — Data ✅

- [x] CMDB: 12 services, 12 edges via `ImpactRelation` (writable over the
      legacy API). Reads as `source → impacted`.
- [x] Schema: `logs` (GIN), `past_incidents`, `runbooks`, `deploys`
- [x] Corpus: 19,654 lines / 18,687 INFO / 789 WARN / 178 ERROR, 9 incidents
      over 7 patterns. *Loghub rejected — 0 ERRORs, wrong domain. Constitution
      §4.1. Must appear in the README.*
- [x] 30 goldens: 18 real / 5 clean / 2 concurrent / 2 inconclusive /
      3 efficiency

### 2 — Tools ⬜

- [ ] 2.1 `src/config.py` — every constant, typed
- [ ] 2.2 `src/clients/protocols.py` — read and write interfaces separated
- [ ] 2.3 `src/clients/glpi.py`
- [ ] 2.4 `src/clients/logstore.py`
- [ ] 2.5 7 runbooks + 5 decoys, embedded
- [ ] 2.6 `src/mcp/observability.py` — 4 tools
- [ ] 2.7 `src/mcp/itsm.py` — 7 tools, writes assert a token
- [ ] 2.8 All 11 tested standalone

### 3 — Agent ⬜

- [ ] 3.1 `state.py` — must include `services_seen` for E3
- [ ] 3.2 `prompts.py` — method, not answers; no root-cause hints
- [ ] 3.3 `graph.py` — nodes, edges, cap in `should_continue`
- [ ] 3.4 `gate.py` — confidence, token issuance, escalation
- [ ] 3.5 HITL via `interrupt_before`
- [ ] 3.6 gld_001 end to end

### 4 — Observability ⬜

- [ ] 4.1 `tracing.py` — Phoenix + OpenInference
- [ ] 4.2 span attrs incl. `retrieval_style`, `hypothesis_at_this_step`
- [ ] 4.3 `GET /runs/{id}` audit trail

### 5 — API + trigger ⬜

- [ ] 5.1 3 endpoints; 202 + run_id, idempotency on alert fingerprint
- [ ] 5.2 toy services: payment-api, auth-service, traffic-gen
- [ ] 5.3 Prometheus + Alertmanager → webhook

### 6 — Evaluation ⬜

- [ ] 6.1 E1, E2, E4, E6 — code-based
- [ ] 6.2 E3 causal validity assertion
- [ ] 6.3 judge + TPR/TNR every run
- [ ] 6.4 `REPORT.md` with deltas vs baseline
- [ ] 6.5 two hard gates in CI

### 7 — Chaos ⬜

- [ ] 7.1 6 scripts incl. one where nothing is wrong
- [ ] 7.2 `make chaos-suite` — 6 rows, 6 passes

### 8 — Ship ⬜

- [ ] 8.1 Dockerfile
- [ ] 8.2 CI
- [ ] 8.3 Helm
- [ ] 8.4 Render
- [ ] 8.5 README — measured numbers, §4.1 decision, limitations

---

**Next: 2.1 `src/config.py`.**

Move `seed_cmdb.py` and `generate_logs.py` to `scripts/`. Delete
`load_logs.py` — dead, record why in `decisions.md`.
