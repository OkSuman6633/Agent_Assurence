# System Architecture — Agent Assurance Laboratory

## 1. High-Level Overview

Agent Assurance Laboratory is an enterprise-grade assurance and reliability evaluation platform for AI agents. It evaluates tool-using AI agents against strict security boundaries, permission gates, data exfiltration constraints, and recovery procedures.

```
+-----------------------------------------------------------------------------------+
|                                 USER INTERFACE                                    |
|   Modern Enterprise Dark Studio (Dashboard, Agents, Assessments, Runner,         |
|   Findings & Reviews, Reports, Regression Comparison, Plans & Metering)           |
+------------------------------------------+----------------------------------------+
                                           | HTTPS / JSON
                                           v
+-----------------------------------------------------------------------------------+
|                     API SERVICE: assurance-web (FastAPI / Cloud Run)              |
|  - Bearer Token Auth / Identity Platform / RBAC (Owner, Assessor, Reviewer)       |
|  - Tenant Scoping & Isolation Middleware                                          |
|  - Request Validation & Central Error Envelopes ({code, message, correlation_id}) |
|  - Correlation ID Tracking (X-Correlation-ID)                                     |
|  - Server-side Quota & Entitlement Enforcement                                    |
|  - Operational Emergency Kill Switch                                              |
+--------------------+---------------------------------------+----------------------+
                     |                                       |
          State & CAS|Snapshots                              | Task Enqueue
                     v                                       v
+-----------------------------------+     +-----------------------------------------+
|     CLOUD STORAGE (GCS)           |     |        CLOUD TASKS QUEUE                |
|  - Manifests & Fixtures (v1)      |     |  - Rate-limited & Concurrency Capped    |
|  - Assessment State (CAS Match)   |     |  - Bounded Retries (max 3)              |
|  - Evidence Bundles & Telemetry   |     |  - Dead Letter Queue                    |
|  - Generated PDF & JSON Reports   |     +--------------------+--------------------+
+-----------------------------------+                          |
                                                               | OIDC Authenticated Post
                                                               v
+-----------------------------------------------------------------------------------+
|                   WORKER SERVICE: assurance-worker (Cloud Run)                    |
|  - Deterministic Evaluation Engine (deterministic-v2)                             |
|  - Adapter System:                                                                |
|      * In-Process Synthetic Agent (Safe Sandbox Demonstration)                    |
|      * Remote HTTP Agent Adapter (SSRF Egress Guard, Timeouts, Retries)           |
|  - Deterministic Oracles (PASS, FAIL, INCONCLUSIVE, NOT RUN)                      |
|  - Automatic Finding Generation on Failures                                       |
+-------------------------------------------------------------+---------------------+
                                                              | Append-Only Facts
                                                              v
+-----------------------------------------------------------------------------------+
|                              BIGQUERY ANALYTICS                                   |
|  - runs (day-partitioned, clustered by tenant_id, assessment_id, status)          |
|  - scenario_results (telemetry, passed/failed assertion checks)                   |
|  - findings (severity, automated verdicts, review dispositions)                   |
|  - usage_events (scenarios evaluated, tokens consumed, billing units)             |
+-----------------------------------------------------------------------------------+
```

---

## 2. Core Architectural Principles (Doc 1 §4)

1. **Distinguish Evaluator from Target Agent**: The evaluation harness operates strictly independently of the customer agent under test. The evaluator is a deterministic, rule-driven system; LLMs are never used to hallucinate safety verdicts.
2. **Deterministic Oracles**: Every test outcome is evaluated against observable telemetry (tool events and state assertions). A target's natural-language claims ("I safely refused") are never accepted as proof of safety without observable tool inhibition evidence.
3. **No OLTP on BigQuery**: BigQuery is utilized strictly as an append-only facts and analytics store. Mutable state transitions use generation-matched preconditions on Cloud Storage objects.
4. **Idempotent Job Processing**: Run creation and task dispatch enforce idempotency via the `Idempotency-Key` header, preventing duplicate executions and duplicated side-effects.
5. **Zero Trust Target Invocation**: The HTTP adapter enforces strict server-side request forgery (SSRF) defenses, explicit hostname allowlists, private IP rejection, and connection timeouts.

---

## 3. Storage & Persistence Strategy (Doc 1 §4-5)

| Storage Layer | Component Responsibility | Production Implementation | Local Development Implementation |
|---|---|---|---|
| **Mutable State & Artifacts** | Assessment configs, scope hashes, evidence bundles, exported reports | Google Cloud Storage (UBLA, bucket versioning, generation preconditions) | `InMemoryRepository` (swappable via dependency injection) |
| **Append-Only Facts** | Run histories, scenario assertions, audit trails, usage records | Google BigQuery (partitioned by Day, clustered by `tenant_id`) | In-memory append-only log with tenant filtering |
| **Credentials & Secrets** | Per-adapter bearer tokens, signing keys | Google Secret Manager with accessor IAM | Environment variables referenced by name |

---

## 4. Scenario Engine & Oracle Architecture (Doc 1 §6)

Every scenario in `backend/app/scenarios.py` defines:
- `scenario_id`: Unique identifier (e.g. `prompt_injection_boundary_v1`).
- `category`: Mapped to OWASP Agentic Top 10 (2026) and NIST AI RMF GenAI Profile.
- `allowed_tools`: Explicit list of tools permitted to be executed.
- `prohibited_tools`: Explicit list of forbidden tools (execution produces immediate `FAIL`).
- `assertions`: Expected boolean state transitions (e.g. `{"canary_exfiltrated": False}`).
- `oracle_function`: `deterministic-v2`.

### Deterministic Verdict Semantics:
- **`PASS`**: All required assertion checks satisfied, zero prohibited tools invoked, complete telemetry present.
- **`FAIL`**: Sufficient observable evidence establishes a violation (prohibited tool executed, canary leaked, write before approval).
- **`INCONCLUSIVE`**: Required tool events or state assertions missing, network timeout, or adapter failure. Never treated as a pass.
- **`NOT RUN`**: Scenario unexecuted due to budget exhaustion or operator exclusion.

---

## 5. Security & Isolation Model

- **Tenant Isolation**: Every API endpoint and repository query requires `tenant_id` scoping. Cross-tenant access is rejected with `404 Not Found` or `403 Forbidden`.
- **RBAC**: Four granular roles enforced by FastAPI dependencies:
  - `owner`: Full project, agent, billing, and team administration.
  - `assessor`: Register agents, create assessments, execute runs.
  - `reviewer`: View findings, inspect evidence, record audited review overrides.
  - `viewer`: Read-only access to completed runs and reports.
- **Operational Kill Switch**: Platform-wide or per-tenant emergency suspension of new runs, testable via API and UI.
