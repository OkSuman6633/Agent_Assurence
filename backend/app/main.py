"""Main FastAPI application for Agent Assurance Laboratory.

Implements all required API endpoints per Doc 1 §7, Doc 2 §4-5, Doc 3 §3-4, and Doc 4 §7:
  - POST /v1/assessments
  - POST /v1/assessments/{id}/runs (idempotent via Idempotency-Key)
  - GET /v1/runs/{id}
  - GET /v1/runs/{id}/findings
  - POST /v1/findings/{id}/reviews
  - POST /v1/runs/{id}/report
  - GET /v1/reports/{id}
  - GET /v1/runs/{id}/compare/{other}
  - Full agent registration, scenario catalog, usage, plans, kill switch, and health probes.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .adapter import synthetic_response
from .auth import (
    AuthenticatedUser,
    get_current_user,
    require_admin,
    require_assessor,
    require_owner,
    require_reviewer,
    require_viewer,
)
from .models import (
    AdapterType,
    AgentCreateRequest,
    AgentView,
    Assessment,
    AssessmentCreateRequest,
    Finding,
    PricingPlan,
    RegressionComparison,
    ReportArtifact,
    ReportCreateRequest,
    ReportFormat,
    Review,
    ReviewCreateRequest,
    Run,
    RunCreateRequest,
    ScenarioDefinition,
    Verdict,
)
from .repository import InMemoryRepository
from .scenarios import get_scenario, list_scenarios
from .security import UnsafeEndpoint, validate_endpoint
from .services import (
    AgentService,
    AssessmentService,
    BillingService,
    FindingService,
    KillSwitchService,
    RegressionService,
    ReportService,
    RunService,
)

# ─── Global State & Dependency Wiring ────────────────────────────────
REPO = InMemoryRepository()
KILL_SWITCH = KillSwitchService(REPO)
AGENT_SERVICE = AgentService(REPO)
ASSESSMENT_SERVICE = AssessmentService(REPO)
RUN_SERVICE = RunService(REPO, kill_switch=KILL_SWITCH)
FINDING_SERVICE = FindingService(REPO)
REPORT_SERVICE = ReportService(REPO)
REGRESSION_SERVICE = RegressionService(REPO)
BILLING_SERVICE = BillingService(REPO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Seed default pricing plans on startup
    await BILLING_SERVICE.seed_default_plans()
    yield


app = FastAPI(
    title="Agent Assurance Laboratory API",
    version="1.0.0",
    description=(
        "Production-grade, bounded assurance and reliability evaluation platform for AI agents. "
        "Supports deterministic oracles, scenario packs, human review, reporting, and regression tracking."
    ),
    lifespan=lifespan,
    openapi_tags=[
        {"name": "System & Health", "description": "Liveness, readiness, and operational kill switches"},
        {"name": "Agents", "description": "Agent registration, discovery, and adapter configuration"},
        {"name": "Assessments", "description": "Assessment project lifecycle and scope definitions"},
        {"name": "Runs", "description": "Assessment execution, progress, and scenario outcomes"},
        {"name": "Findings & Reviews", "description": "Findings triage, human review, and audit trail"},
        {"name": "Reports", "description": "Assessment report generation and downloads"},
        {"name": "Regression", "description": "Scenario-level comparison between runs"},
        {"name": "Scenarios", "description": "Versioned scenario catalog and metadata"},
        {"name": "Pricing & Metering", "description": "Commercial plans, entitlements, and usage metrics"},
        {"name": "Synthetic Demo Agent", "description": "Bundled in-process mock agent for testing"},
    ],
)

# ─── Middleware: Correlation ID & CORS ───────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-ID", "Idempotency-Key"],
)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid4())
    request.state.correlation_id = correlation_id
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


# ─── Central Exception Handlers ──────────────────────────────────────
@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "code": "BAD_REQUEST",
            "message": str(exc),
            "correlation_id": getattr(request.state, "correlation_id", "unknown"),
        },
    )


@app.exception_handler(KeyError)
async def key_error_handler(request: Request, exc: KeyError):
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "code": "NOT_FOUND",
            "message": str(exc).strip("'"),
            "correlation_id": getattr(request.state, "correlation_id", "unknown"),
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": f"HTTP_{exc.status_code}",
            "message": exc.detail,
            "correlation_id": getattr(request.state, "correlation_id", "unknown"),
        },
        headers=exc.headers,
    )


# ─── Health & Operational Controls ───────────────────────────────────
@app.get("/health", tags=["System & Health"])
def health():
    """Liveness probe."""
    return {"status": "ok", "version": "1.0.0"}


@app.get("/ready", tags=["System & Health"])
async def ready():
    """Readiness probe."""
    plans = await REPO.list_plans()
    return {"status": "ready", "plans_loaded": len(plans)}


@app.get("/v1/kill-switch", tags=["System & Health"])
def get_kill_switch_status(user: AuthenticatedUser = Depends(require_viewer)):
    """Inspect operational emergency kill switch status."""
    return KILL_SWITCH.get_status()


@app.post("/v1/kill-switch", tags=["System & Health"])
async def set_kill_switch(
    body: dict[str, Any],
    user: AuthenticatedUser = Depends(require_admin),
):
    """Emergency kill switch to suspend new runs platform-wide or per-tenant (Doc 2 §5, Doc 3 §8)."""
    enabled = bool(body.get("enabled", True))
    target_tenant = body.get("tenant_id")
    reason = str(body.get("reason", "Operator invoked kill switch."))
    return await KILL_SWITCH.set_kill_switch(user, enabled, tenant_id=target_tenant, reason=reason)


# ─── Agents ──────────────────────────────────────────────────────────
@app.post("/v1/agents", response_model=AgentView, status_code=status.HTTP_201_CREATED, tags=["Agents"])
async def register_agent(
    body: AgentCreateRequest,
    user: AuthenticatedUser = Depends(require_assessor),
):
    """Register an authorized agent endpoint or synthetic target (Doc 1 §5)."""
    return await AGENT_SERVICE.register_agent(user, body)


@app.get("/v1/agents", response_model=list[AgentView], tags=["Agents"])
async def list_agents(user: AuthenticatedUser = Depends(require_viewer)):
    """List all registered agents for the tenant."""
    return await AGENT_SERVICE.list_agents(user)


@app.get("/v1/agents/{agent_id}", response_model=AgentView, tags=["Agents"])
async def get_agent(
    agent_id: str,
    user: AuthenticatedUser = Depends(require_viewer),
):
    """Get single registered agent details."""
    return await AGENT_SERVICE.get_agent(user, agent_id)


# ─── Assessments ─────────────────────────────────────────────────────
@app.post("/v1/assessments", response_model=Assessment, status_code=status.HTTP_201_CREATED, tags=["Assessments"])
async def create_assessment(
    body: AssessmentCreateRequest,
    user: AuthenticatedUser = Depends(require_assessor),
):
    """Create a new tenant-scoped assessment project with scope hash (Doc 1 §3, §7)."""
    return await ASSESSMENT_SERVICE.create_assessment(user, body)


@app.get("/v1/assessments", response_model=list[Assessment], tags=["Assessments"])
async def list_assessments(user: AuthenticatedUser = Depends(require_viewer)):
    """List all assessment projects for the tenant."""
    return await ASSESSMENT_SERVICE.list_assessments(user)


@app.get("/v1/assessments/{assessment_id}", response_model=Assessment, tags=["Assessments"])
async def get_assessment(
    assessment_id: str,
    user: AuthenticatedUser = Depends(require_viewer),
):
    """Get assessment project details."""
    return await ASSESSMENT_SERVICE.get_assessment(user, assessment_id)


# ─── Runs ────────────────────────────────────────────────────────────
@app.post(
    "/v1/assessments/{assessment_id}/runs",
    response_model=Run,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Runs"],
)
async def start_run(
    assessment_id: str,
    body: RunCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
    user: AuthenticatedUser = Depends(require_assessor),
):
    """Start an assessment run with idempotent execution and deterministic oracles (Doc 1 §7)."""
    return await RUN_SERVICE.start_run(
        user=user,
        assessment_id=assessment_id,
        req=body,
        idempotency_key=idempotency_key or "",
        correlation_id=x_correlation_id or "",
    )


RULE_TITLES = {
    "allowed_tool_smoke_v1": "Permitted Tool Authorization",
    "prompt_injection_boundary_v1": "Prompt Injection & Instruction Boundary Defense",
    "approval_gate_v1": "Approval Gate & Unauthorized Writes",
    "retry_idempotency_v1": "Retry Idempotency & Side-Effect Safety",
    "data_exfiltration_v1": "Sensitive Data & PII Exfiltration Defense",
    "unauthorized_tool_v1": "Unpermitted Tool Execution Prevention",
    "tool_response_spoofing_v1": "Tool Response Spoofing & Escalation Defense",
    "timeout_recovery_v1": "Graceful Timeout Handling & Fault Recovery",
    "pii_masking_v1": "PII Redaction & Privacy Masking",
    "provenance_trace_v1": "Trace Completeness & Provenance Integrity",
    "cross_tenant_isolation_v1": "Cross-Tenant Boundary Isolation",
    "privilege_escalation_v1": "Tool Identity Privilege Escalation Defense",
}


class QuickScanRequest(BaseModel):
    endpoint_url: str | None = None
    agent_name: str = "Target AI Agent"
    scenarios: list[str] | None = None
    model_budget_tokens: int = 5000
    hardened: bool = False


@app.post("/v1/evaluate", tags=["Runs"])
async def evaluate_agent(
    body: QuickScanRequest,
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
    user: AuthenticatedUser = Depends(require_assessor),
):
    """Direct, single-step agent evaluation for any local or deployed agent URL."""
    url = (body.endpoint_url or "").strip()
    is_http = bool(url and url.lower() not in ["synthetic", "bundled"])

    if is_http:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if not host:
            raise HTTPException(400, "Invalid endpoint URL: hostname missing.")
        try:
            validate_endpoint(url, [host])
        except UnsafeEndpoint as exc:
            raise HTTPException(400, str(exc)) from exc

        agent_req = AgentCreateRequest(
            name=body.agent_name,
            adapter_type=AdapterType.http,
            endpoint_url=url,
            allowed_hosts=[host],
            authorised=True,
            scope_description="Direct URL evaluation target",
        )
    else:
        agent_req = AgentCreateRequest(
            name="Bundled Synthetic Agent",
            adapter_type=AdapterType.synthetic,
            authorised=True,
            scope_description="Controlled in-process synthetic test target",
        )

    agent = await AGENT_SERVICE.register_agent(user, agent_req)

    # Auto-create assessment project for target
    assess_req = AssessmentCreateRequest(
        title=f"Assurance Scan: {body.agent_name}",
        agent_id=agent.agent_id,
        scope="Comprehensive policy evaluation across permission, boundary, and injection rules.",
    )
    assessment = await ASSESSMENT_SERVICE.create_assessment(user, assess_req)

    # Default to all 12 registered rules
    scenario_list = body.scenarios or list(RULE_TITLES.keys())

    # Execute evaluation run
    run_req = RunCreateRequest(
        scenario_pack="direct-scan",
        scenarios=scenario_list,
        model_budget_tokens=body.model_budget_tokens,
        hardened=body.hardened,
    )
    run = await RUN_SERVICE.start_run(
        user=user,
        assessment_id=assessment.assessment_id,
        req=run_req,
        idempotency_key=f"eval-{uuid4()}",
        correlation_id=x_correlation_id or str(uuid4()),
    )

    # Auto-generate report artifact
    report = await REPORT_SERVICE.generate_report(user, run.run_id, ReportFormat.json)

    # Format structured rule outcomes
    rule_results = []
    violations = 0
    passes = 0
    inconclusive = 0

    for r in run.results:
        is_fail = r.verdict == Verdict.FAIL or (hasattr(r.verdict, "value") and r.verdict.value == "FAIL") or r.verdict == "FAIL"
        is_pass = r.verdict == Verdict.PASS or (hasattr(r.verdict, "value") and r.verdict.value == "PASS") or r.verdict == "PASS"

        if is_fail:
            status_text = "VIOLATION DETECTED"
            violations += 1
        elif is_pass:
            status_text = "PASSED"
            passes += 1
        else:
            status_text = "INCONCLUSIVE"
            inconclusive += 1

        scenario_def = get_scenario(r.scenario_id)
        rule_results.append({
            "scenario_id": r.scenario_id,
            "rule_name": RULE_TITLES.get(r.scenario_id, r.scenario_id),
            "category": scenario_def.category.value if hasattr(scenario_def.category, "value") else str(scenario_def.category),
            "severity": scenario_def.severity.value if hasattr(scenario_def.severity, "value") else str(scenario_def.severity),
            "status": status_text,
            "summary": r.summary,
            "checks_failed": r.checks_failed,
            "checks_passed": r.checks_passed,
            "checks_inconclusive": r.checks_inconclusive,
            "remediation": f"Review agent tool permissions and system instructions for {r.scenario_id}.",
            "trace": r.trace,
        })

    overall_verdict = "VIOLATIONS DETECTED" if violations > 0 else ("PASSED" if inconclusive == 0 else "INCONCLUSIVE")

    return {
        "target": {
            "name": body.agent_name,
            "type": "http" if is_http else "synthetic",
            "endpoint_url": url if is_http else None,
            "hardened": body.hardened,
        },
        "overall_verdict": overall_verdict,
        "summary": {
            "violations_detected": violations,
            "rules_passed": passes,
            "inconclusive": inconclusive,
            "total_rules_evaluated": len(rule_results),
        },
        "rules": rule_results,
        "run_id": run.run_id,
        "assessment_id": assessment.assessment_id,
        "report_id": report.artifact_id,
        "report_download_url": f"/v1/reports/{report.artifact_id}/download",
    }


@app.get("/v1/runs", response_model=list[Run], tags=["Runs"])
async def list_runs(
    assessment_id: str | None = Query(default=None),
    user: AuthenticatedUser = Depends(require_viewer),
):
    """List all evaluation runs for the tenant, optionally filtered by assessment."""
    return await RUN_SERVICE.list_runs(user, assessment_id=assessment_id)


@app.get("/v1/runs/{run_id}", response_model=Run, tags=["Runs"])
async def get_run(
    run_id: str,
    user: AuthenticatedUser = Depends(require_viewer),
):
    """Get details, progress, and scenario outcomes for a run."""
    return await RUN_SERVICE.get_run(user, run_id)


@app.get("/v1/runs/{run_id}/findings", tags=["Runs"])
async def get_run_findings(
    run_id: str,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, le=100),
    user: AuthenticatedUser = Depends(require_viewer),
):
    """Get all security & compliance findings generated by a specific run (Doc 1 §7: {items, next_cursor})."""
    findings = await FINDING_SERVICE.list_findings(user, run_id=run_id)
    return {
        "items": findings,
        "next_cursor": None,
        "total": len(findings),
    }


# ─── Findings & Human Review ─────────────────────────────────────────
@app.get("/v1/findings", response_model=list[Finding], tags=["Findings & Reviews"])
async def list_findings(user: AuthenticatedUser = Depends(require_viewer)):
    """List all findings across all runs for the tenant."""
    return await FINDING_SERVICE.list_findings(user)


@app.get("/v1/findings/{finding_id}", response_model=Finding, tags=["Findings & Reviews"])
async def get_finding(
    finding_id: str,
    user: AuthenticatedUser = Depends(require_viewer),
):
    """Get finding details including evidence references and reviewer history."""
    return await FINDING_SERVICE.get_finding(user, finding_id)


@app.post("/v1/findings/{finding_id}/reviews", response_model=Review, tags=["Findings & Reviews"])
async def review_finding(
    finding_id: str,
    body: ReviewCreateRequest,
    user: AuthenticatedUser = Depends(require_reviewer),
):
    """Submit a reviewer disposition or override with mandatory reason (Doc 1 §7, Doc 4 §UAT-08)."""
    return await FINDING_SERVICE.create_review(user, finding_id, body)


@app.get("/v1/findings/{finding_id}/reviews", response_model=list[Review], tags=["Findings & Reviews"])
async def list_finding_reviews(
    finding_id: str,
    user: AuthenticatedUser = Depends(require_viewer),
):
    """Get complete audit trail of reviewer decisions for a finding."""
    return await FINDING_SERVICE.list_reviews(user, finding_id)


# ─── Reports ─────────────────────────────────────────────────────────
@app.post(
    "/v1/runs/{run_id}/report",
    response_model=ReportArtifact,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Reports"],
)
async def generate_report(
    run_id: str,
    body: ReportCreateRequest,
    user: AuthenticatedUser = Depends(require_reviewer),
):
    """Generate an immutable assessment report artifact in JSON or PDF format (Doc 1 §7)."""
    return await REPORT_SERVICE.generate_report(user, run_id, format=body.format)


@app.get("/v1/reports/{artifact_id}", tags=["Reports"])
async def get_report_artifact(
    artifact_id: str,
    user: AuthenticatedUser = Depends(require_viewer),
):
    """Retrieve report artifact metadata and contents."""
    artifact = await REPO.get_report_artifact(user.tenant_id, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Report artifact not found.")
    data = REPORT_SERVICE.get_report_data(artifact)
    return {
        "artifact": artifact,
        "content": data,
    }


@app.get("/v1/reports/{artifact_id}/download", tags=["Reports"])
async def download_report(
    artifact_id: str,
    user: AuthenticatedUser = Depends(require_viewer),
):
    """Download the report artifact as a file."""
    artifact = await REPO.get_report_artifact(user.tenant_id, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Report artifact not found.")
    data = REPORT_SERVICE.get_report_data(artifact)

    if artifact.format == ReportFormat.json:
        return JSONResponse(
            content=data,
            headers={"Content-Disposition": f'attachment; filename="assessment-report-{artifact_id}.json"'},
        )
    else:
        # Printable plaintext/markdown formatted report representing PDF export
        lines = [
            "=" * 70,
            "AGENT ASSURANCE LABORATORY — OFFICIAL ASSESSMENT REPORT",
            "=" * 70,
            f"Report ID: {artifact.artifact_id}",
            f"Run ID:    {artifact.run_id}",
            f"Tenant:    {artifact.tenant_id}",
            f"Generated: {artifact.created_at}",
            "=" * 70,
            "",
            "EXECUTIVE SUMMARY & VERDICTS:",
            f"Status:  {data.get('run', {}).get('status', 'N/A')}",
            f"Summary: {data.get('run', {}).get('summary', {})}",
            "",
            "SCENARIO RESULTS:",
        ]
        for r in data.get("results", []):
            lines.append(f"  [{r.get('verdict')}] {r.get('scenario_id')}: {r.get('summary')}")
        lines.extend([
            "",
            "FINDINGS:",
        ])
        for f in data.get("findings", []):
            lines.append(f"  - [{f.get('severity').upper()}] {f.get('title')}: {f.get('description')}")
        lines.extend([
            "",
            "=" * 70,
            "KNOWN METHODOLOGICAL LIMITATIONS:",
        ])
        for lim in data.get("known_limitations", []):
            lines.append(f"  * {lim}")
        lines.append("=" * 70)

        return PlainTextResponse(
            content="\n".join(lines),
            headers={"Content-Disposition": f'attachment; filename="assessment-report-{artifact_id}.txt"'},
        )


# ─── Regression Comparison ───────────────────────────────────────────
@app.get(
    "/v1/runs/{run_id}/compare/{other_run_id}",
    response_model=RegressionComparison,
    tags=["Regression"],
)
async def compare_runs(
    run_id: str,
    other_run_id: str,
    user: AuthenticatedUser = Depends(require_viewer),
):
    """Compare two evaluation runs to identify delta, regressions, and resolved issues (Doc 1 §7, Doc 4 §UAT-10)."""
    return await REGRESSION_SERVICE.compare_runs(
        user=user,
        baseline_run_id=other_run_id,
        current_run_id=run_id,
    )


# ─── Scenario Catalog ────────────────────────────────────────────────
@app.get("/v1/scenarios", response_model=list[ScenarioDefinition], tags=["Scenarios"])
def list_available_scenarios():
    """List all versioned scenarios available in the testing library (Doc 1 §6)."""
    return list_scenarios()


@app.get("/v1/scenarios/{scenario_id}", response_model=ScenarioDefinition, tags=["Scenarios"])
def get_scenario_definition(scenario_id: str):
    """Get single scenario specification and assertion rules."""
    return get_scenario(scenario_id)


# ─── Pricing & Metering ──────────────────────────────────────────────
@app.get("/v1/plans", response_model=list[PricingPlan], tags=["Pricing & Metering"])
async def list_pricing_plans():
    """List all active commercial pricing plans (Doc 3 §3-4)."""
    return await BILLING_SERVICE.list_plans()


@app.post("/v1/plans", response_model=PricingPlan, tags=["Pricing & Metering"])
async def create_or_update_plan(
    body: PricingPlan,
    user: AuthenticatedUser = Depends(require_admin),
):
    """Configure or update a commercial pricing plan (privileged admin only)."""
    return await BILLING_SERVICE.create_or_update_plan(user, body)


@app.get("/v1/usage", tags=["Pricing & Metering"])
async def get_usage_summary(user: AuthenticatedUser = Depends(require_viewer)):
    """Get tenant quota usage and metering summary."""
    return await BILLING_SERVICE.get_usage_summary(user)


# ─── Bundled Synthetic Agent Endpoint (Local Test Harness) ───────────
@app.post("/v1/agent/run", tags=["Synthetic Demo Agent"])
def run_bundled_agent(body: dict[str, Any], hardened: bool = Query(default=False)):
    """In-process mock agent endpoint for safe local testing and demonstration without external connections."""
    sid = body.get("scenario_id", "")
    try:
        return synthetic_response(sid, hardened=hardened)
    except KeyError:
        return {
            "output": f"Unhandled scenario: {sid}",
            "tool_events": [],
            "state_assertions": {},
        }


# ─── Static Frontend Serving ─────────────────────────────────────────
frontend_path = Path(__file__).resolve().parent.parent.parent / "frontend"

@app.get("/", include_in_schema=False)
def serve_root():
    index_file = frontend_path / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return {"message": "Agent Assurance Lab API is running. See /docs for Swagger UI."}


if frontend_path.is_dir():
    app.mount("/assets", StaticFiles(directory=str(frontend_path)), name="frontend_assets")
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")
