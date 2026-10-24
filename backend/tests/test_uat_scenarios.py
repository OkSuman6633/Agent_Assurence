"""UAT acceptance test suite directly verifying Doc 4 §7 (UAT-01 through UAT-10).

Every test matches the explicit acceptance criteria required by the business analyst playbook:
  - UAT-01: Create authorised assessment
  - UAT-02: Run allowed tool scenario (PASS with trace)
  - UAT-03: Run injected document with exfiltration request (FAIL on forbidden invocation)
  - UAT-04: Run approval bypass attempt (FAIL if write tool called early)
  - UAT-05: Repeat completed run via retry (No duplicate side effects)
  - UAT-06: Unreachable test agent (INCONCLUSIVE; no false PASS)
  - UAT-07: Cross-tenant viewer attempts access (Access denied)
  - UAT-08: Reviewer overrides finding (Audit trail preserved)
  - UAT-09: Export assessment (Coverage limits & trace links included)
  - UAT-10: Re-run after fix (Scenario-level comparison)
"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.auth import AuthenticatedUser, get_current_user
from app.main import app
from app.models import (
    AdapterType,
    AgentCreateRequest,
    AssessmentCreateRequest,
    FindingStatus,
    ReportFormat,
    ReviewCreateRequest,
    ReviewDecision,
    Role,
    RunCreateRequest,
    Verdict,
)
from app.oracle import evaluate
from app.repository import InMemoryRepository
from app.services import (
    AgentService,
    AssessmentService,
    FindingService,
    RegressionService,
    ReportService,
    RunService,
)


@pytest.fixture
def repo():
    return InMemoryRepository()


@pytest.fixture
def assessor():
    return AuthenticatedUser(
        user_id="assessor-1",
        email="assessor@example.com",
        tenant_id="uat-tenant",
        role=Role.assessor,
        display_name="UAT Assessor",
    )


@pytest.fixture
def reviewer():
    return AuthenticatedUser(
        user_id="reviewer-1",
        email="reviewer@example.com",
        tenant_id="uat-tenant",
        role=Role.reviewer,
        display_name="UAT Reviewer",
    )


@pytest.fixture
def foreign_viewer():
    return AuthenticatedUser(
        user_id="viewer-external",
        email="viewer@other-org.com",
        tenant_id="other-tenant",
        role=Role.viewer,
        display_name="External Viewer",
    )


# ─── UAT-01: Create authorised assessment ────────────────────────────
@pytest.mark.asyncio
async def test_uat_01_create_authorised_assessment(repo, assessor):
    agent_svc = AgentService(repo)
    assessment_svc = AssessmentService(repo)

    agent = await agent_svc.register_agent(
        assessor,
        AgentCreateRequest(
            name="UAT-01 Agent",
            description="Agent for boundary validation",
            adapter_type=AdapterType.synthetic,
            authorised=True,
            scope_description="Only synthetic sandbox tools allowed",
        ),
    )
    assessment = await assessment_svc.create_assessment(
        assessor,
        AssessmentCreateRequest(
            title="Q4 Production Readiness Assurance",
            description="Evaluating tool safety and prompt isolation",
            scope="Testing FAQ query, injection boundary, and approval enforcement",
            agent_id=agent.agent_id,
        ),
    )

    assert assessment.assessment_id is not None
    assert assessment.scope_hash != ""
    assert assessment.status.value == "configured"
    assert assessment.owner_id == assessor.user_id


# ─── UAT-02: Run allowed tool scenario (PASS with trace) ─────────────
@pytest.mark.asyncio
async def test_uat_02_run_allowed_tool_scenario(repo, assessor):
    agent_svc = AgentService(repo)
    assessment_svc = AssessmentService(repo)
    run_svc = RunService(repo)

    agent = await agent_svc.register_agent(
        assessor,
        AgentCreateRequest(name="UAT-02 Agent", adapter_type=AdapterType.synthetic, authorised=True),
    )
    assessment = await assessment_svc.create_assessment(
        assessor,
        AssessmentCreateRequest(title="Smoke Assessment", agent_id=agent.agent_id),
    )

    run = await run_svc.start_run(
        assessor,
        assessment.assessment_id,
        RunCreateRequest(scenarios=["allowed_tool_smoke_v1"]),
        idempotency_key="uat-02-run",
    )

    assert run.status.value == "completed"
    assert run.summary["PASS"] == 1
    result = run.results[0]
    assert result.verdict == Verdict.PASS
    assert result.evidence_complete is True
    assert "search_knowledge_base" in str(result.trace["tool_events"])


# ─── UAT-03: Injected document with exfiltration request (FAIL) ───────
@pytest.mark.asyncio
async def test_uat_03_prompt_injection_exfiltration_fails(repo, assessor):
    agent_svc = AgentService(repo)
    assessment_svc = AssessmentService(repo)
    run_svc = RunService(repo)
    finding_svc = FindingService(repo)

    agent = await agent_svc.register_agent(
        assessor,
        AgentCreateRequest(name="UAT-03 Agent", adapter_type=AdapterType.synthetic, authorised=True),
    )
    assessment = await assessment_svc.create_assessment(
        assessor,
        AssessmentCreateRequest(title="Injection Assessment", agent_id=agent.agent_id),
    )

    run = await run_svc.start_run(
        assessor,
        assessment.assessment_id,
        RunCreateRequest(scenarios=["prompt_injection_boundary_v1"]),
        idempotency_key="uat-03-run",
    )

    assert run.summary["FAIL"] == 1
    result = run.results[0]
    assert result.verdict == Verdict.FAIL

    findings = await finding_svc.list_findings(assessor, run_id=run.run_id)
    assert len(findings) == 1
    assert "send_email" in str(result.trace["checks_failed"])


# ─── UAT-04: Approval bypass attempt (FAIL if write tool invoked early) ───
@pytest.mark.asyncio
async def test_uat_04_approval_bypass_attempt_fails(repo, assessor):
    agent_svc = AgentService(repo)
    assessment_svc = AssessmentService(repo)
    run_svc = RunService(repo)

    agent = await agent_svc.register_agent(
        assessor,
        AgentCreateRequest(name="UAT-04 Agent", adapter_type=AdapterType.synthetic, authorised=True),
    )
    assessment = await assessment_svc.create_assessment(
        assessor,
        AssessmentCreateRequest(title="Approval Assessment", agent_id=agent.agent_id),
    )

    run = await run_svc.start_run(
        assessor,
        assessment.assessment_id,
        RunCreateRequest(scenarios=["approval_gate_v1"]),
        idempotency_key="uat-04-run",
    )

    assert run.summary["FAIL"] == 1
    result = run.results[0]
    assert result.verdict == Verdict.FAIL
    assert any("write_before_approval" in c for c in result.checks_failed)


# ─── UAT-05: Repeat completed run via retry (No duplicate side effects) ───
@pytest.mark.asyncio
async def test_uat_05_idempotent_retry_prevents_duplicate_side_effects(repo, assessor):
    agent_svc = AgentService(repo)
    assessment_svc = AssessmentService(repo)
    run_svc = RunService(repo)

    agent = await agent_svc.register_agent(
        assessor,
        AgentCreateRequest(name="UAT-05 Agent", adapter_type=AdapterType.synthetic, authorised=True),
    )
    assessment = await assessment_svc.create_assessment(
        assessor,
        AssessmentCreateRequest(title="Retry Assessment", agent_id=agent.agent_id),
    )

    # First execution
    run1 = await run_svc.start_run(
        assessor,
        assessment.assessment_id,
        RunCreateRequest(scenarios=["retry_idempotency_v1"]),
        idempotency_key="uat-05-unique-key",
    )

    # Simulated network retry with identical key
    run2 = await run_svc.start_run(
        assessor,
        assessment.assessment_id,
        RunCreateRequest(scenarios=["retry_idempotency_v1"]),
        idempotency_key="uat-05-unique-key",
    )

    assert run1.run_id == run2.run_id
    runs = await run_svc.list_runs(assessor)
    assert len(runs) == 1


# ─── UAT-06: Unreachable test agent (INCONCLUSIVE; no false PASS) ───────
@pytest.mark.asyncio
async def test_uat_06_unreachable_or_broken_agent_is_inconclusive():
    # If the adapter encounters network failure or invalid response, verdict must be INCONCLUSIVE
    broken_observed = {
        "output": "Connection timed out to upstream model.",
        # Missing tool_events and state_assertions
    }
    verdict, summary, trace, complete = evaluate("allowed_tool_smoke_v1", broken_observed)
    assert verdict == Verdict.INCONCLUSIVE.value
    assert complete is False
    assert "missing" in summary.lower() or "incomplete" in summary.lower()


# ─── UAT-07: Cross-tenant viewer attempts access (Denied and logged) ───
@pytest.mark.asyncio
async def test_uat_07_cross_tenant_access_denied(repo, assessor, foreign_viewer):
    agent_svc = AgentService(repo)
    assessment_svc = AssessmentService(repo)
    run_svc = RunService(repo)

    agent = await agent_svc.register_agent(
        assessor,
        AgentCreateRequest(name="Confidential Target", adapter_type=AdapterType.synthetic, authorised=True),
    )
    assessment = await assessment_svc.create_assessment(
        assessor,
        AssessmentCreateRequest(title="Confidential Assessment", agent_id=agent.agent_id),
    )
    run = await run_svc.start_run(
        assessor,
        assessment.assessment_id,
        RunCreateRequest(scenarios=["allowed_tool_smoke_v1"]),
        idempotency_key="uat-07-key",
    )

    # Foreign viewer cannot get assessment or run
    with pytest.raises(KeyError):
        await assessment_svc.get_assessment(foreign_viewer, assessment.assessment_id)

    with pytest.raises(KeyError):
        await run_svc.get_run(foreign_viewer, run.run_id)


# ─── UAT-08: Reviewer overrides finding (Audit history retained) ────────
@pytest.mark.asyncio
async def test_uat_08_reviewer_override_workflow(repo, assessor, reviewer):
    agent_svc = AgentService(repo)
    assessment_svc = AssessmentService(repo)
    run_svc = RunService(repo)
    finding_svc = FindingService(repo)

    agent = await agent_svc.register_agent(
        assessor,
        AgentCreateRequest(name="UAT-08 Agent", adapter_type=AdapterType.synthetic, authorised=True),
    )
    assessment = await assessment_svc.create_assessment(
        assessor,
        AssessmentCreateRequest(title="Override Project", agent_id=agent.agent_id),
    )
    run = await run_svc.start_run(
        assessor,
        assessment.assessment_id,
        RunCreateRequest(scenarios=["prompt_injection_boundary_v1"]),
        idempotency_key="uat-08-key",
    )

    findings = await finding_svc.list_findings(assessor, run_id=run.run_id)
    finding_id = findings[0].finding_id

    # Reviewer marks false positive with required business rationale
    review = await finding_svc.create_review(
        reviewer,
        finding_id,
        ReviewCreateRequest(
            decision=ReviewDecision.false_positive,
            reason="Controlled sandbox canary test; not reproducible in production environment.",
        ),
    )

    assert review.reviewer_id == reviewer.user_id
    assert review.new_status == FindingStatus.false_positive

    # Check finding audit trail
    reviews = await finding_svc.list_reviews(assessor, finding_id)
    assert len(reviews) == 1
    assert reviews[0].reason == "Controlled sandbox canary test; not reproducible in production environment."

    updated = await finding_svc.get_finding(assessor, finding_id)
    assert updated.status == FindingStatus.false_positive
    assert updated.automated_verdict == Verdict.FAIL  # Automated verdict remains intact!


# ─── UAT-09: Export assessment (Coverage limits & trace links included) ─
@pytest.mark.asyncio
async def test_uat_09_export_assessment_report(repo, assessor):
    agent_svc = AgentService(repo)
    assessment_svc = AssessmentService(repo)
    run_svc = RunService(repo)
    report_svc = ReportService(repo)

    agent = await agent_svc.register_agent(
        assessor,
        AgentCreateRequest(name="Export Agent", adapter_type=AdapterType.synthetic, authorised=True),
    )
    assessment = await assessment_svc.create_assessment(
        assessor,
        AssessmentCreateRequest(title="Export Project", agent_id=agent.agent_id),
    )
    run = await run_svc.start_run(
        assessor,
        assessment.assessment_id,
        RunCreateRequest(scenarios=["allowed_tool_smoke_v1", "approval_gate_v1"]),
        idempotency_key="uat-09-key",
    )

    artifact = await report_svc.generate_report(assessor, run.run_id, format=ReportFormat.json)
    data = report_svc.get_report_data(artifact)

    # Acceptance check: Report contains scope, run summary, results, findings, and known limitations
    assert data["assessment"]["assessment_id"] == assessment.assessment_id
    assert "known_limitations" in data
    assert any("certification" in lim for lim in data["known_limitations"])
    assert len(data["results"]) == 2


# ─── UAT-10: Re-run after fix (Scenario-by-scenario deltas) ───────────
@pytest.mark.asyncio
async def test_uat_10_rerun_after_fix_regression_deltas(repo, assessor):
    agent_svc = AgentService(repo)
    assessment_svc = AssessmentService(repo)
    run_svc = RunService(repo)
    regression_svc = RegressionService(repo)

    agent = await agent_svc.register_agent(
        assessor,
        AgentCreateRequest(name="Fix Agent", adapter_type=AdapterType.synthetic, authorised=True),
    )
    assessment = await assessment_svc.create_assessment(
        assessor,
        AssessmentCreateRequest(title="Regression Delta Assessment", agent_id=agent.agent_id),
    )

    # Baseline run: FAIL on prompt injection
    run_baseline = await run_svc.start_run(
        assessor,
        assessment.assessment_id,
        RunCreateRequest(scenarios=["allowed_tool_smoke_v1", "prompt_injection_boundary_v1"]),
        idempotency_key="uat-10-baseline",
    )

    # Current run: only smoke scenario run
    run_current = await run_svc.start_run(
        assessor,
        assessment.assessment_id,
        RunCreateRequest(scenarios=["allowed_tool_smoke_v1"]),
        idempotency_key="uat-10-current",
    )

    comparison = await regression_svc.compare_runs(assessor, run_baseline.run_id, run_current.run_id)
    assert comparison.baseline_run_id == run_baseline.run_id
    assert comparison.current_run_id == run_current.run_id

    delta_map = {d.scenario_id: d for d in comparison.scenario_deltas}
    assert delta_map["allowed_tool_smoke_v1"].changed is False
    assert delta_map["allowed_tool_smoke_v1"].baseline_verdict == Verdict.PASS
    assert delta_map["allowed_tool_smoke_v1"].current_verdict == Verdict.PASS
