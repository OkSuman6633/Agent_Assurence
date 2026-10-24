"""Unit tests for services: Assessment, Run, Finding, Review, Report, Regression, Billing, KillSwitch."""
import pytest
from app.auth import AuthenticatedUser
from app.models import (
    AdapterType,
    AgentCreateRequest,
    AssessmentCreateRequest,
    FindingStatus,
    PricingPlan,
    ReportFormat,
    ReviewCreateRequest,
    ReviewDecision,
    Role,
    RunCreateRequest,
    Verdict,
)
from app.repository import InMemoryRepository
from app.services import (
    AgentService,
    AssessmentService,
    BillingService,
    FindingService,
    KillSwitchService,
    RegressionService,
    ReportService,
    RunService,
)


@pytest.fixture
def repo():
    return InMemoryRepository()


@pytest.fixture
def user():
    return AuthenticatedUser(
        user_id="user-123",
        email="test@assurance.local",
        tenant_id="tenant-alpha",
        role=Role.owner,
        display_name="Test Assessor",
    )


@pytest.fixture
def reviewer_user():
    return AuthenticatedUser(
        user_id="reviewer-456",
        email="reviewer@assurance.local",
        tenant_id="tenant-alpha",
        role=Role.reviewer,
        display_name="Senior Reviewer",
    )


@pytest.mark.asyncio
async def test_agent_registration_and_assessment_creation(repo, user):
    agent_svc = AgentService(repo)
    assessment_svc = AssessmentService(repo)

    # Register synthetic agent
    agent_req = AgentCreateRequest(
        name="Synthetic Demo Agent",
        description="Safe test agent",
        adapter_type=AdapterType.synthetic,
        authorised=True,
    )
    agent = await agent_svc.register_agent(user, agent_req)
    assert agent.name == "Synthetic Demo Agent"
    assert agent.agent_id is not None

    # Create assessment
    assess_req = AssessmentCreateRequest(
        title="Q4 Agent Security Audit",
        description="Assessing tool execution and boundary controls",
        scope="In-scope: synthetic FAQ search and canary inspection",
        agent_id=agent.agent_id,
    )
    assessment = await assessment_svc.create_assessment(user, assess_req)
    assert assessment.title == "Q4 Agent Security Audit"
    assert assessment.scope_hash != ""
    assert assessment.status.value == "configured"


@pytest.mark.asyncio
async def test_run_execution_generates_verdicts_and_findings(repo, user):
    agent_svc = AgentService(repo)
    assessment_svc = AssessmentService(repo)
    run_svc = RunService(repo)
    finding_svc = FindingService(repo)

    # Register agent and assessment
    agent = await agent_svc.register_agent(user, AgentCreateRequest(
        name="Test Agent",
        adapter_type=AdapterType.synthetic,
        authorised=True,
    ))
    assessment = await assessment_svc.create_assessment(user, AssessmentCreateRequest(
        title="Boundary Test",
        agent_id=agent.agent_id,
    ))

    # Execute run with pass and fail scenarios
    run_req = RunCreateRequest(
        scenario_pack="core-test",
        scenarios=["allowed_tool_smoke_v1", "prompt_injection_boundary_v1"],
        model_budget_tokens=4000,
    )
    run = await run_svc.start_run(user, assessment.assessment_id, run_req, idempotency_key="key-001")
    assert run.status.value == "completed"
    assert run.summary["PASS"] == 1
    assert run.summary["FAIL"] == 1

    # Findings should be auto-created for the FAIL scenario
    findings = await finding_svc.list_findings(user, run_id=run.run_id)
    assert len(findings) == 1
    assert findings[0].scenario_id == "prompt_injection_boundary_v1"
    assert findings[0].status == FindingStatus.open
    assert findings[0].automated_verdict == Verdict.FAIL


@pytest.mark.asyncio
async def test_idempotent_run_creation_prevents_duplicate_runs(repo, user):
    agent_svc = AgentService(repo)
    assessment_svc = AssessmentService(repo)
    run_svc = RunService(repo)

    agent = await agent_svc.register_agent(user, AgentCreateRequest(
        name="Idempotent Test Agent",
        adapter_type=AdapterType.synthetic,
        authorised=True,
    ))
    assessment = await assessment_svc.create_assessment(user, AssessmentCreateRequest(
        title="Idempotency Test",
        agent_id=agent.agent_id,
    ))

    run_req = RunCreateRequest(
        scenarios=["allowed_tool_smoke_v1"],
    )

    run1 = await run_svc.start_run(user, assessment.assessment_id, run_req, idempotency_key="idem-abc-123")
    run2 = await run_svc.start_run(user, assessment.assessment_id, run_req, idempotency_key="idem-abc-123")

    # Second call returns the existing run without re-executing
    assert run1.run_id == run2.run_id
    runs = await run_svc.list_runs(user)
    assert len(runs) == 1


@pytest.mark.asyncio
async def test_reviewer_override_workflow_preserves_automated_verdict(repo, user, reviewer_user):
    agent_svc = AgentService(repo)
    assessment_svc = AssessmentService(repo)
    run_svc = RunService(repo)
    finding_svc = FindingService(repo)

    agent = await agent_svc.register_agent(user, AgentCreateRequest(
        name="Review Test Agent",
        adapter_type=AdapterType.synthetic,
        authorised=True,
    ))
    assessment = await assessment_svc.create_assessment(user, AssessmentCreateRequest(
        title="Review Audit",
        agent_id=agent.agent_id,
    ))
    run = await run_svc.start_run(
        user,
        assessment.assessment_id,
        RunCreateRequest(scenarios=["prompt_injection_boundary_v1"]),
        idempotency_key="review-test-1",
    )

    findings = await finding_svc.list_findings(user, run_id=run.run_id)
    assert len(findings) == 1
    finding_id = findings[0].finding_id

    # Reviewer marks false positive with justification
    review_req = ReviewCreateRequest(
        decision=ReviewDecision.false_positive,
        reason="Demonstration canary payload deliberately induced by evaluation design for sandbox test.",
    )
    review = await finding_svc.create_review(reviewer_user, finding_id, review_req)
    assert review.decision == ReviewDecision.false_positive
    assert review.reviewer_id == reviewer_user.user_id

    # Refetch finding: status updated, but original automated verdict preserved
    updated_finding = await finding_svc.get_finding(user, finding_id)
    assert updated_finding.status == FindingStatus.false_positive
    assert updated_finding.automated_verdict == Verdict.FAIL


@pytest.mark.asyncio
async def test_report_generation_and_export(repo, user):
    agent_svc = AgentService(repo)
    assessment_svc = AssessmentService(repo)
    run_svc = RunService(repo)
    report_svc = ReportService(repo)

    agent = await agent_svc.register_agent(user, AgentCreateRequest(
        name="Report Agent",
        adapter_type=AdapterType.synthetic,
        authorised=True,
    ))
    assessment = await assessment_svc.create_assessment(user, AssessmentCreateRequest(
        title="Report Generation Test",
        agent_id=agent.agent_id,
    ))
    run = await run_svc.start_run(
        user,
        assessment.assessment_id,
        RunCreateRequest(scenarios=["allowed_tool_smoke_v1"]),
        idempotency_key="report-test-1",
    )

    artifact = await report_svc.generate_report(user, run.run_id, format=ReportFormat.json)
    assert artifact.status == "completed"
    assert artifact.format == ReportFormat.json

    data = report_svc.get_report_data(artifact)
    assert data["report_type"] == "agent_assurance_report"
    assert "known_limitations" in data
    assert len(data["known_limitations"]) > 0


@pytest.mark.asyncio
async def test_regression_comparison_identifies_fixed_and_new_issues(repo, user):
    agent_svc = AgentService(repo)
    assessment_svc = AssessmentService(repo)
    run_svc = RunService(repo)
    regression_svc = RegressionService(repo)

    agent = await agent_svc.register_agent(user, AgentCreateRequest(
        name="Regression Agent",
        adapter_type=AdapterType.synthetic,
        authorised=True,
    ))
    assessment = await assessment_svc.create_assessment(user, AssessmentCreateRequest(
        title="Regression Test Project",
        agent_id=agent.agent_id,
    ))

    # Baseline run with FAIL on injection
    run1 = await run_svc.start_run(
        user,
        assessment.assessment_id,
        RunCreateRequest(scenarios=["allowed_tool_smoke_v1", "prompt_injection_boundary_v1"]),
        idempotency_key="run-baseline",
    )

    # Current run with only PASS
    run2 = await run_svc.start_run(
        user,
        assessment.assessment_id,
        RunCreateRequest(scenarios=["allowed_tool_smoke_v1"]),
        idempotency_key="run-current",
    )

    comparison = await regression_svc.compare_runs(user, run1.run_id, run2.run_id)
    assert comparison.baseline_run_id == run1.run_id
    assert comparison.current_run_id == run2.run_id
    assert len(comparison.scenario_deltas) == 2


@pytest.mark.asyncio
async def test_kill_switch_suspends_run_creation(repo, user):
    kill_switch = KillSwitchService(repo)
    run_svc = RunService(repo, kill_switch=kill_switch)
    agent_svc = AgentService(repo)
    assessment_svc = AssessmentService(repo)

    agent = await agent_svc.register_agent(user, AgentCreateRequest(
        name="Kill Switch Agent",
        adapter_type=AdapterType.synthetic,
        authorised=True,
    ))
    assessment = await assessment_svc.create_assessment(user, AssessmentCreateRequest(
        title="Kill Switch Project",
        agent_id=agent.agent_id,
    ))

    # Activate kill switch
    await kill_switch.set_kill_switch(user, enabled=True, reason="Emergency drill")
    assert kill_switch.is_disabled(user.tenant_id) is True

    # Attempt to start run should raise error
    with pytest.raises(ValueError, match="operational kill switch is active"):
        await run_svc.start_run(
            user,
            assessment.assessment_id,
            RunCreateRequest(scenarios=["allowed_tool_smoke_v1"]),
            idempotency_key="kill-switch-run",
        )

    # Deactivate kill switch
    await kill_switch.set_kill_switch(user, enabled=False, reason="Drill concluded")
    run = await run_svc.start_run(
        user,
        assessment.assessment_id,
        RunCreateRequest(scenarios=["allowed_tool_smoke_v1"]),
        idempotency_key="kill-switch-run-2",
    )
    assert run.status.value == "completed"
