# Security & Threat Model — Agent Assurance Laboratory

## 1. Authentication & Tenancy Model (Doc 1 §5, Doc 2 §4)

### Identity Verification
- In production, incoming requests present a scoped Bearer token verified via **Firebase Admin SDK / Google Cloud Identity Platform**.
- Token claims are unpacked to verify `uid`, `email`, `tenant_id`, and `role`.
- In local development (`ENVIRONMENT != "production"`), explicit mock identity is enabled when `AUTH_DISABLED=true`. Production strictly denies auth bypass.

### Role-Based Access Control (RBAC)
FastAPI dependency factories (`require_role`) enforce strict role gating on state-changing operations:

| Role | Register Agents | Create Assessments | Launch Runs | Review / Override Findings | Generate Reports | Configure Plans & Kill Switch |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Owner** | Yes | Yes | Yes | Yes | Yes | Yes |
| **Assessor** | Yes | Yes | Yes | View only | View only | No |
| **Reviewer** | View only | View only | View only | Yes | Yes | No |
| **Viewer** | View only | View only | View only | View only | View only | No |
| **Platform Admin** | Yes | Yes | Yes | Yes | Yes | Yes |

### Multi-Tenant Isolation
- Tenant scoping is enforced at the repository, object storage path, and BigQuery query layers.
- Object direct references (e.g. `agent_id`, `assessment_id`, `run_id`, `finding_id`) are always queried with `tenant_id` preconditions.
- Automated tests in `backend/tests/test_tenancy_isolation.py` prove that Tenant A cannot read, modify, or list Tenant B's assets.

---

## 2. Server-Side Request Forgery (SSRF) & Network Egress Defenses (Doc 1 §6, Doc 2 §4)

Invoking remote AI agent targets introduces SSRF and network egress risks. The platform implements multi-layer defense in `backend/app/security.py`:

```
User Input Endpoint URL
        |
        v
[ 1. Hostname Allowlist Check ] ---> Rejects unlisted domains
        |
        v
[ 2. URL Scheme Validation ] --------> HTTPS required (HTTP only for explicit loopback in dev)
        |
        v
[ 3. Embedded Credentials Check ] --> Rejects http://user:pass@host
        |
        v
[ 4. DNS Resolution & IP Range Check ]
        |
        +---> Rejects IPv4/IPv6 Loopback (127.0.0.0/8, ::1) unless explicitly allowlisted for local dev
        +---> Rejects RFC 1918 Private ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
        +---> Rejects Link-Local / Cloud Metadata (169.254.169.254, fe80::/10)
        +---> Rejects Multicast & Reserved (224.0.0.0/4, 240.0.0.0/4)
        |
        v
[ 5. HTTP Client Egress Constraints ]
        +---> follow_redirects = False (Prevents redirect-based SSRF bypass)
        +---> Strict total timeout (default 15s, max 60s)
        +---> Bounded token budget
```

---

## 3. Secret Management & Evidence Redaction (Doc 1 §5, Doc 2 §2)

- **Zero Raw Secrets Stored in Database**: When registering remote HTTP agents, users configure `auth_env_var` (the server-side variable name hosting the secret), never the raw secret itself.
- **Trace Redaction**: Telemetry events, tool calls, and error traces are scrubbed to prevent logging bearer tokens, Authorization headers, or customer secrets.
- **Canary Data Only**: Test scenarios use harmless synthetic canary values (e.g. `[SYNTHETIC_CANARY]`, fake SSNs `000-00-0000`). Never evaluate against live financial systems or real customer PII in this test harness.

---

## 4. Operational Emergency Kill Switch (Doc 2 §5, Doc 3 §8)

- Provides an immediate operational circuit-breaker to halt assessment execution during suspected downstream agent compromise or upstream quota abuse.
- Can be activated globally or targeted to a specific tenant.
- Preserves all historical evidence and traces in immutable storage while rejecting new run dispatches with `HTTP 400 Execution suspended`.
