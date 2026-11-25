"""Domain models for Agent Assurance Laboratory.

These are the core domain entities as specified in Doc 1 §5.
All models use Pydantic for validation. Storage-layer serialisation
is handled by the repository modules, not by the domain.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


# ─── Enums ────────────────────────────────────────────────────────────
class AdapterType(str, Enum):
    http = "http"
    synthetic = "synthetic"


class AssessmentStatus(str, Enum):
    draft = "draft"
    configured = "configured"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class RunStatus(str, Enum):
    pending = "pending"
    dispatched = "dispatched"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    timed_out = "timed_out"


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_RUN = "NOT RUN"


class Severity(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class FindingStatus(str, Enum):
    open = "open"
    confirmed = "confirmed"
    mitigated = "mitigated"
    false_positive = "false_positive"
    accepted_risk = "accepted_risk"


class ReviewDecision(str, Enum):
    confirmed = "confirmed"
    false_positive = "false_positive"
    mitigated = "mitigated"
    accepted_risk = "accepted_risk"
    needs_investigation = "needs_investigation"


class Role(str, Enum):
    owner = "owner"
    assessor = "assessor"
    reviewer = "reviewer"
    viewer = "viewer"
    platform_admin = "platform_admin"


class ReportFormat(str, Enum):
    pdf = "pdf"
    json = "json"


# ─── Agent / Adapter ─────────────────────────────────────────────────
class AgentManifest(BaseModel):
    """Registered agent endpoint for assurance testing (Doc 1 §5)."""
    agent_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    capabilities: list[str] = Field(default_factory=list)
    functions: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    adapter_type: AdapterType = AdapterType.synthetic
    endpoint_url: str | None = None
    allowed_hosts: list[str] = Field(default_factory=list)
    auth_env_var: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{1,127}$")
    timeout_seconds: float = Field(default=15.0, ge=1.0, le=60.0)
    authorised: bool = False
    scope_description: str = Field(default="", max_length=2000)
    environment: str = Field(default="sandbox", max_length=100)
    version_info: str = Field(default="", max_length=500)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @field_validator("allowed_hosts")
    @classmethod
    def normalize_hosts(cls, values: list[str]) -> list[str]:
        return [v.strip().lower().rstrip(".") for v in values if v.strip()]


class AgentView(BaseModel):
    """Public view of agent — never includes auth_env_var."""
    agent_id: str
    tenant_id: str
    name: str
    description: str
    capabilities: list[str] = Field(default_factory=list)
    functions: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    adapter_type: AdapterType
    endpoint_url: str | None
    allowed_hosts: list[str]
    timeout_seconds: float
    authorised: bool
    scope_description: str
    environment: str
    version_info: str
    created_at: str
    updated_at: str


# ─── Assessment ───────────────────────────────────────────────────────
class Assessment(BaseModel):
    """Top-level assessment entity (Doc 1 §3-5)."""
    assessment_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    scope: str = Field(default="", max_length=5000)
    agent_id: str
    status: AssessmentStatus = AssessmentStatus.draft
    owner_id: str = ""
    scope_hash: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compute_scope_hash(self) -> str:
        data = json.dumps({"scope": self.scope, "agent_id": self.agent_id}, sort_keys=True)
        self.scope_hash = hashlib.sha256(data.encode()).hexdigest()[:16]
        return self.scope_hash


# ─── Scenario ─────────────────────────────────────────────────────────
class ScenarioCategory(str, Enum):
    permitted_tool_usage = "permitted_tool_usage"
    prompt_injection = "prompt_injection"
    unauthorized_tool = "unauthorized_tool"
    approval_bypass = "approval_bypass"
    data_exfiltration = "data_exfiltration"
    tool_response_spoofing = "tool_response_spoofing"
    retry_safety = "retry_safety"
    timeout_recovery = "timeout_recovery"
    pii_masking = "pii_masking"
    provenance_integrity = "provenance_integrity"
    cross_tenant_isolation = "cross_tenant_isolation"


class ScenarioDefinition(BaseModel):
    """Versioned scenario definition (Doc 1 §6)."""
    scenario_id: str
    version: str = "v1"
    category: ScenarioCategory
    description: str = ""
    objective: str = ""
    preconditions: list[str] = Field(default_factory=list)
    input_text: str
    adversarial_fixture: str = ""
    expected_behavior: str
    allowed_tools: list[str] = Field(default_factory=list)
    prohibited_tools: list[str] = Field(default_factory=list)
    expected_state_transitions: dict[str, Any] = Field(default_factory=dict)
    severity: Severity = Severity.medium
    assertions: dict[str, bool] = Field(default_factory=dict)
    oracle_function: str = "deterministic-v1"
    fixture_hash: str = ""
    execution_limits: dict[str, Any] = Field(default_factory=lambda: {"max_tokens": 5000, "timeout_seconds": 30})

    def __getitem__(self, item: str) -> Any:
        if item == "input":
            return self.input_text
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)


# ─── Run & Results ────────────────────────────────────────────────────
class ScenarioResult(BaseModel):
    """Individual scenario outcome within a run."""
    scenario_id: str
    verdict: Verdict
    summary: str
    trace: dict[str, Any] = Field(default_factory=dict)
    evidence_complete: bool = False
    oracle_id: str = "deterministic-v1"
    latency_ms: int = 0
    checks_passed: list[str] = Field(default_factory=list)
    checks_failed: list[str] = Field(default_factory=list)
    checks_inconclusive: list[str] = Field(default_factory=list)


class Run(BaseModel):
    """Assessment run record (Doc 1 §5)."""
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    assessment_id: str
    agent_id: str
    tenant_id: str
    status: RunStatus = RunStatus.pending
    scenario_pack: str = "core-v1"
    scenarios_requested: list[str] = Field(default_factory=list)
    results: list[ScenarioResult] = Field(default_factory=list)
    fixture_version: str = ""
    build_sha: str = ""
    model_budget_tokens: int = 5000
    idempotency_key: str = ""
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: str | None = None
    ended_at: str | None = None
    summary: dict[str, int] = Field(default_factory=lambda: {"PASS": 0, "FAIL": 0, "INCONCLUSIVE": 0, "NOT RUN": 0})
    error_message: str | None = None


# ─── Finding ──────────────────────────────────────────────────────────
class Finding(BaseModel):
    """Security/assurance finding (Doc 1 §5-7)."""
    finding_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    assessment_id: str
    tenant_id: str
    scenario_id: str
    category: str = ""
    severity: Severity = Severity.medium
    status: FindingStatus = FindingStatus.open
    title: str = ""
    description: str = ""
    impact: str = ""
    remediation: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    assertion_results: dict[str, Any] = Field(default_factory=dict)
    automated_verdict: Verdict = Verdict.FAIL
    reviewer_verdict: Verdict | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ─── Review ───────────────────────────────────────────────────────────
class Review(BaseModel):
    """Human review of a finding (Doc 1 §7, Doc 4 UAT-08)."""
    review_id: str = Field(default_factory=lambda: str(uuid4()))
    finding_id: str
    tenant_id: str
    reviewer_id: str
    reviewer_email: str = ""
    decision: ReviewDecision
    reason: str = Field(min_length=1, max_length=5000)
    previous_status: FindingStatus = FindingStatus.open
    new_status: FindingStatus = FindingStatus.confirmed
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ─── Audit ────────────────────────────────────────────────────────────
class AuditEvent(BaseModel):
    """Append-only audit record (Doc 1 §5)."""
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    actor_id: str
    actor_email: str = ""
    action: str
    resource_type: str
    resource_id: str
    details: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ─── Pricing & Entitlement (Doc 3 §3-4) ──────────────────────────────
class PricingPlan(BaseModel):
    """Configurable pricing plan."""
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    version: int = 1
    name: str
    description: str = ""
    currency: str = "GBP"
    base_amount_minor: int = 0  # Amount in pence/cents
    price_amount: int | None = None
    billing_interval: Literal["one_off", "monthly", "annual"] = "one_off"
    included_agents: int = 1
    included_scenarios: int = 50
    maximum_runs: int = 10
    retention_days: int = 14
    report_formats: list[ReportFormat] = Field(default_factory=lambda: [ReportFormat.json])
    reviewer_seats: int = 1
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    effective_from: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    overage_unit_price_minor: int = 0
    active: bool = True

    @model_validator(mode="before")
    @classmethod
    def populate_amounts(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "price_amount" in data and not data.get("base_amount_minor"):
                data["base_amount_minor"] = data["price_amount"]
            elif "base_amount_minor" in data and not data.get("price_amount"):
                data["price_amount"] = data["base_amount_minor"]
        return data


class TenantEntitlement(BaseModel):
    """Tenant's active plan and usage limits."""
    tenant_id: str
    plan_id: str
    plan_name: str = ""
    agents_used: int = 0
    agents_limit: int = 1
    scenarios_used: int = 0
    scenarios_limit: int = 50
    runs_used: int = 0
    runs_limit: int = 10
    retention_days: int = 14
    report_formats: list[ReportFormat] = Field(default_factory=lambda: [ReportFormat.json])
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    effective_from: str = ""
    expires_at: str | None = None


class UsageEvent(BaseModel):
    """Idempotent usage metering record (Doc 3 §4)."""
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    run_id: str
    scenario_count: int = 0
    compute_tokens: int = 0
    storage_bytes: int = 0
    billable_units: int = 0
    event_time: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_digest: str = ""


# ─── Report ───────────────────────────────────────────────────────────
class ReportRequest(BaseModel):
    format: ReportFormat = ReportFormat.json


ReportCreateRequest = ReportRequest


class ReportArtifact(BaseModel):
    artifact_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    tenant_id: str
    format: ReportFormat
    status: str = "pending"
    storage_path: str = ""
    report_data: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ─── Regression Comparison ────────────────────────────────────────────
class ScenarioDelta(BaseModel):
    scenario_id: str
    baseline_verdict: Verdict | None = None
    current_verdict: Verdict | None = None
    changed: bool = False
    notes: str = ""


class RegressionComparison(BaseModel):
    baseline_run_id: str
    current_run_id: str
    tenant_id: str
    overall_changed: bool = False
    new_failures: int = 0
    resolved_failures: int = 0
    new_passes: int = 0
    total_baseline: int = 0
    total_current: int = 0
    scenario_deltas: list[ScenarioDelta] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ─── API Request/Response Models ──────────────────────────────────────
class AgentCreateRequest(BaseModel):
    agent_id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    capabilities: list[str] = Field(default_factory=list)
    functions: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    adapter_type: AdapterType = AdapterType.synthetic
    endpoint_url: str | None = None
    allowed_hosts: list[str] = Field(default_factory=list)
    auth_env_var: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{1,127}$")
    timeout_seconds: float = Field(default=15.0, ge=1.0, le=60.0)
    authorised: bool = False
    scope_description: str = Field(default="", max_length=2000)
    environment: str = Field(default="sandbox", max_length=100)
    version_info: str = Field(default="", max_length=500)

    @field_validator("allowed_hosts")
    @classmethod
    def normalize_hosts(cls, values: list[str]) -> list[str]:
        return [v.strip().lower().rstrip(".") for v in values if v.strip()]


class AgentUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    capabilities: list[str] | None = None
    functions: list[dict[str, Any]] | None = None
    tools: list[str] | None = None
    metadata: dict[str, Any] | None = None
    adapter_type: AdapterType | None = None
    endpoint_url: str | None = None
    allowed_hosts: list[str] | None = None
    auth_env_var: str | None = None
    timeout_seconds: float | None = None
    authorised: bool | None = None
    scope_description: str | None = None
    environment: str | None = None
    version_info: str | None = None


class IntentDetectionRequest(BaseModel):
    prompt: str = Field(min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)


class IntentDetectionResponse(BaseModel):
    intent: str
    matched_agent_id: str | None = None
    matched_agent_name: str | None = None
    confidence: float = 0.0
    matched_capabilities: list[str] = Field(default_factory=list)
    suggested_tools: list[str] = Field(default_factory=list)
    registered_agents_considered: int = 0
    reason: str = ""


class AgentRoutingRequest(BaseModel):
    prompt: str = Field(min_length=1)
    required_capabilities: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class AgentRoutingResponse(BaseModel):
    routed: bool
    agent_id: str | None = None
    agent_name: str | None = None
    endpoint_url: str | None = None
    matched_capabilities: list[str] = Field(default_factory=list)
    matched_tools: list[str] = Field(default_factory=list)
    reason: str
    registered_agents_considered: int = 0


class AgentValidationResponse(BaseModel):
    valid: bool
    agent_id: str
    name: str
    checks: dict[str, bool] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class AgentFunctionMappingResponse(BaseModel):
    agent_id: str
    tenant_id: str
    name: str
    functions: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)


class AssessmentCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    scope: str = Field(default="", max_length=5000)
    agent_id: str


class RunCreateRequest(BaseModel):
    scenario_pack: str = Field(default="core-v1", min_length=1, max_length=100)
    scenarios: list[str] = Field(default_factory=lambda: [
        "allowed_tool_smoke_v1",
        "prompt_injection_boundary_v1",
        "approval_gate_v1",
        "retry_idempotency_v1",
    ], min_length=1, max_length=30)
    model_budget_tokens: int = Field(default=5000, ge=1, le=100000)
    adapter_override: AdapterType | None = None
    hardened: bool = False


class ReviewCreateRequest(BaseModel):
    decision: ReviewDecision
    reason: str = Field(min_length=1, max_length=5000)


class ErrorResponse(BaseModel):
    """Standard error response (Doc 1 §7)."""
    code: int
    message: str
    correlation_id: str = ""


class PaginatedResponse(BaseModel):
    items: list[Any] = Field(default_factory=list)
    next_cursor: str | None = None
    total: int = 0
