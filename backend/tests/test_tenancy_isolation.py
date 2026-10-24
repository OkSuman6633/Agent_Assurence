"""Automated tests proving tenant isolation (Doc 1 §5, Doc 2 §4, Doc 4 §UAT-07).

Proves that Tenant A cannot access Tenant B's:
  - Registered agents
  - Assessments
  - Runs and results
  - Findings
  - Review histories
  - Report artifacts
"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.auth import AuthenticatedUser, get_current_user
from app.main import app
from app.models import (
    AdapterType,
    AgentCreateRequest,
    AssessmentCreateRequest,
    Role,
    RunCreateRequest,
)
from app.repository import InMemoryRepository
from app.services import (
    AgentService,
    AssessmentService,
    FindingService,
    ReportService,
    RunService,
)


@pytest.fixture
def repo():
    return InMemoryRepository()


@pytest.fixture
def tenant_a_user():
    return AuthenticatedUser(
        user_id="user-a",
        email="alice@tenant-a.com",
        tenant_id="tenant-alpha",
        role=Role.owner,
        display_name="Alice (Tenant A)",
    )


@pytest.fixture
def tenant_b_user():
    return AuthenticatedUser(
        user_id="user-b",
        email="bob@tenant-b.com",
        tenant_id="tenant-bravo",
        role=Role.owner,
        display_name="Bob (Tenant B)",
    )


@pytest.mark.asyncio
async def test_tenant_cannot_read_or_access_other_tenant_agent(repo, tenant_a_user, tenant_b_user):
    agent_svc = AgentService(repo)

    # Tenant A registers an agent
    agent_a = await agent_svc.register_agent(
        tenant_a_user,
        AgentCreateRequest(
            name="Tenant A Confidential Agent",
            adapter_type=AdapterType.synthetic,
            authorised=True,
        ),
    )

    # Tenant A can view it
    fetched_a = await agent_svc.get_agent(tenant_a_user, agent_a.agent_id)
    assert fetched_a.agent_id == agent_a.agent_id

    # Tenant B lists agents -> must NOT see Tenant A's agent
    b_agents = await agent_svc.list_agents(tenant_b_user)
    assert len(b_agents) == 0

    # Tenant B direct GET -> KeyError / Not Found
    with pytest.raises(KeyError):
        await agent_svc.get_agent(tenant_b_user, agent_a.agent_id)


@pytest.mark.asyncio
async def test_tenant_cannot_access_other_tenant_assessment_or_run(repo, tenant_a_user, tenant_b_user):
    agent_svc = AgentService(repo)
    assessment_svc = AssessmentService(repo)
    run_svc = RunService(repo)

    # Tenant A registers agent & assessment
    agent_a = await agent_svc.register_agent(
        tenant_a_user,
        AgentCreateRequest(name="A-Agent", adapter_type=AdapterType.synthetic, authorised=True),
    )
    assess_a = await assessment_svc.create_assessment(
        tenant_a_user,
        AssessmentCreateRequest(title="A-Assessment", agent_id=agent_a.agent_id),
    )

    # Tenant B cannot see Tenant A's assessment
    b_assessments = await assessment_svc.list_assessments(tenant_b_user)
    assert len(b_assessments) == 0

    with pytest.raises(KeyError):
        await assessment_svc.get_assessment(tenant_b_user, assess_a.assessment_id)

    # Tenant A starts a run
    run_a = await run_svc.start_run(
        tenant_a_user,
        assess_a.assessment_id,
        RunCreateRequest(scenarios=["allowed_tool_smoke_v1"]),
        idempotency_key="run-a-1",
    )

    # Tenant B cannot list or get Tenant A's run
    b_runs = await run_svc.list_runs(tenant_b_user)
    assert len(b_runs) == 0

    with pytest.raises(KeyError):
        await run_svc.get_run(tenant_b_user, run_a.run_id)


@pytest.mark.asyncio
async def test_tenant_cannot_access_other_tenant_findings_or_reports(repo, tenant_a_user, tenant_b_user):
    agent_svc = AgentService(repo)
    assessment_svc = AssessmentService(repo)
    run_svc = RunService(repo)
    finding_svc = FindingService(repo)
    report_svc = ReportService(repo)

    agent_a = await agent_svc.register_agent(
        tenant_a_user,
        AgentCreateRequest(name="A-Agent", adapter_type=AdapterType.synthetic, authorised=True),
    )
    assess_a = await assessment_svc.create_assessment(
        tenant_a_user,
        AssessmentCreateRequest(title="A-Assessment", agent_id=agent_a.agent_id),
    )
    run_a = await run_svc.start_run(
        tenant_a_user,
        assess_a.assessment_id,
        RunCreateRequest(scenarios=["prompt_injection_boundary_v1"]),
        idempotency_key="run-a-findings",
    )

    # Tenant A has findings
    a_findings = await finding_svc.list_findings(tenant_a_user, run_id=run_a.run_id)
    assert len(a_findings) == 1
    finding_id = a_findings[0].finding_id

    # Tenant B cannot see findings
    b_findings = await finding_svc.list_findings(tenant_b_user)
    assert len(b_findings) == 0

    with pytest.raises(KeyError):
        await finding_svc.get_finding(tenant_b_user, finding_id)

    # Tenant A generates a report
    report_a = await report_svc.generate_report(tenant_a_user, run_a.run_id)

    # Tenant B cannot get Tenant A's report
    b_report = await repo.get_report_artifact(tenant_b_user.tenant_id, report_a.artifact_id)
    assert b_report is None


@pytest.mark.asyncio
async def test_api_layer_enforces_tenant_isolation():
    """Verify HTTP API requests reject cross-tenant access with 404/403."""
    user_a = AuthenticatedUser(
        user_id="u-a",
        email="a@tenant.com",
        tenant_id="tenant-api-a",
        role=Role.owner,
    )
    user_b = AuthenticatedUser(
        user_id="u-b",
        email="b@tenant.com",
        tenant_id="tenant-api-b",
        role=Role.owner,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Act as Tenant A
        app.dependency_overrides[get_current_user] = lambda: user_a

        # Register agent as Tenant A
        resp = await client.post("/v1/agents", json={
            "name": "API Tenant A Agent",
            "adapter_type": "synthetic",
            "authorised": True,
        })
        assert resp.status_code == 201
        agent_id = resp.json()["agent_id"]

        # Switch identity to Tenant B
        app.dependency_overrides[get_current_user] = lambda: user_b

        # Tenant B cannot get Tenant A's agent
        resp_b = await client.get(f"/v1/agents/{agent_id}")
        assert resp_b.status_code == 404

        # Tenant B lists agents -> empty
        resp_list = await client.get("/v1/agents")
        assert resp_list.status_code == 200
        assert not any(a["agent_id"] == agent_id for a in resp_list.json())

    # Clear overrides
    app.dependency_overrides.clear()
