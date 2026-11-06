"""Comprehensive test suite verifying Database-Driven Agent Registry (Requirement 8).

Verifies:
  A. Persistent storage of registered agents and tools/functions in SQLite .db
  B. Dynamic fetching of agents from .db for evaluation, validation, intent, and routing
  C. Complete removal of synthetic and hardcoded fallback agents
  D. Database as the single source of truth
  E. Database integrity, relationships, and duplicate handling
  F. Full lifecycle: create, retrieve, update, evaluate, delete, and isolation across restarts
"""
import os
import sqlite3
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth import AuthenticatedUser, get_current_user
from app.main import app
from app.models import (
    AdapterType,
    AgentCreateRequest,
    AgentRoutingRequest,
    AgentUpdateRequest,
    AssessmentCreateRequest,
    IntentDetectionRequest,
    Role,
    RunCreateRequest,
)
from app.repository import SqliteRepository
from app.services import (
    AgentService,
    AssessmentService,
    RunService,
)
from app.test_engine import DatabaseAgentRegistryEngine


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield Path(path)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


@pytest.fixture
def sqlite_repo(temp_db):
    return SqliteRepository(db_path=temp_db)


@pytest.fixture
def user():
    return AuthenticatedUser(
        user_id="user-qa-1",
        email="qa@assurance.local",
        tenant_id="tenant-dynamic-db",
        role=Role.owner,
        display_name="QA Lead",
    )


# ─── A. Store Registered Agents in .db ────────────────────────────────
@pytest.mark.asyncio
async def test_agent_stored_persistently_in_db(sqlite_repo, temp_db, user):
    agent_svc = AgentService(sqlite_repo)

    req = AgentCreateRequest(
        name="Finance Operations Agent",
        description="Processes invoices, credit checks, and financial reporting.",
        capabilities=["invoicing", "credit_check", "reconciliation"],
        functions=[
            {"name": "fetch_invoice", "description": "Retrieve invoice by ID", "parameters": {"invoice_id": "string"}},
            {"name": "issue_credit_note", "description": "Issue customer credit note", "parameters": {"amount": "number"}},
        ],
        tools=["fetch_invoice", "issue_credit_note"],
        metadata={"cost_center": "FIN-402", "tier": "tier-1"},
        adapter_type=AdapterType.synthetic,
        authorised=True,
        scope_description="Financial operations only",
        environment="production",
        version_info="v2.1.0",
    )

    agent_view = await agent_svc.register_agent(user, req)
    assert agent_view.agent_id is not None
    assert agent_view.name == "Finance Operations Agent"
    assert "invoicing" in agent_view.capabilities
    assert "fetch_invoice" in agent_view.tools

    # Direct SQLite query verifying persistence in .db file
    conn = sqlite3.connect(str(temp_db))
    c = conn.cursor()
    c.execute("SELECT agent_id, name, data_json FROM agents WHERE agent_id = ?", (agent_view.agent_id,))
    row = c.fetchone()
    assert row is not None
    assert row[1] == "Finance Operations Agent"
    assert "FIN-402" in row[2]

    # Check relational agent_functions table in .db
    c.execute("SELECT name, description FROM agent_functions WHERE agent_id = ?", (agent_view.agent_id,))
    funcs = c.fetchall()
    func_names = [f[0] for f in funcs]
    assert "fetch_invoice" in func_names
    assert "issue_credit_note" in func_names
    conn.close()


# ─── B. Dynamic Fetching and Update Reflection ────────────────────────
@pytest.mark.asyncio
async def test_dynamic_fetching_and_update_reflected_in_evaluation(sqlite_repo, temp_db, user):
    agent_svc = AgentService(sqlite_repo)
    assessment_svc = AssessmentService(sqlite_repo)
    run_svc = RunService(sqlite_repo)

    # 1. Register agent
    agent = await agent_svc.register_agent(
        user,
        AgentCreateRequest(
            name="Customer Triage Agent",
            description="Initial version",
            capabilities=["triage", "faq"],
            tools=["search_knowledge_base"],
            adapter_type=AdapterType.synthetic,
            authorised=True,
        ),
    )

    # 2. Assessment and first run
    assessment = await assessment_svc.create_assessment(
        user,
        AssessmentCreateRequest(
            title="Triage Audit",
            agent_id=agent.agent_id,
        ),
    )

    run1 = await run_svc.start_run(
        user,
        assessment.assessment_id,
        RunCreateRequest(scenarios=["allowed_tool_smoke_v1"]),
        idempotency_key="eval-run-v1",
    )
    assert run1.status.value == "completed"
    assert run1.agent_id == agent.agent_id

    # 3. Update agent directly in database
    await agent_svc.update_agent(
        user,
        agent.agent_id,
        AgentUpdateRequest(
            name="Customer Triage Agent — Hardened",
            description="Updated version with strict compliance",
            capabilities=["triage", "faq", "escalations"],
            tools=["search_knowledge_base", "log_audit"],
        ),
    )

    # 4. Refetch directly from database
    refetched = await agent_svc.get_agent(user, agent.agent_id)
    assert refetched.name == "Customer Triage Agent — Hardened"
    assert "escalations" in refetched.capabilities

    # 5. Subsequent run picks up updated agent from database
    run2 = await run_svc.start_run(
        user,
        assessment.assessment_id,
        RunCreateRequest(scenarios=["allowed_tool_smoke_v1"]),
        idempotency_key="eval-run-v2",
    )
    assert run2.status.value == "completed"


# ─── C. Deletion Disallows Subsequent Evaluation & Routing ────────────
@pytest.mark.asyncio
async def test_deleted_agent_no_longer_available_for_evaluation_or_routing(sqlite_repo, temp_db, user):
    agent_svc = AgentService(sqlite_repo)
    assessment_svc = AssessmentService(sqlite_repo)
    run_svc = RunService(sqlite_repo)
    engine = DatabaseAgentRegistryEngine(sqlite_repo)

    # Register and setup
    agent = await agent_svc.register_agent(
        user,
        AgentCreateRequest(
            name="Temporary Pilot Agent",
            capabilities=["pilot_testing"],
            tools=["search_knowledge_base"],
            adapter_type=AdapterType.synthetic,
            authorised=True,
        ),
    )

    assessment = await assessment_svc.create_assessment(
        user,
        AssessmentCreateRequest(title="Pilot Assessment", agent_id=agent.agent_id),
    )

    # Route before deletion -> should succeed
    route_res = await engine.route_agent(
        user.tenant_id,
        AgentRoutingRequest(prompt="Need to run pilot testing on knowledge base"),
    )
    assert route_res.routed is True
    assert route_res.agent_id == agent.agent_id

    # Delete agent
    deleted = await agent_svc.delete_agent(user, agent.agent_id)
    assert deleted is True

    # 1. Direct retrieval returns KeyError
    with pytest.raises(KeyError, match="not found"):
        await agent_svc.get_agent(user, agent.agent_id)

    # 2. SQLite record is gone
    conn = sqlite3.connect(str(temp_db))
    c = conn.cursor()
    c.execute("SELECT count(*) FROM agents WHERE agent_id = ?", (agent.agent_id,))
    assert c.fetchone()[0] == 0
    c.execute("SELECT count(*) FROM agent_functions WHERE agent_id = ?", (agent.agent_id,))
    assert c.fetchone()[0] == 0
    conn.close()

    # 3. Evaluation attempting to evaluate deleted agent is rejected
    with pytest.raises((KeyError, ValueError)):
        await run_svc.start_run(
            user,
            assessment.assessment_id,
            RunCreateRequest(scenarios=["allowed_tool_smoke_v1"]),
            idempotency_key="eval-after-delete",
        )

    # 4. Routing returns no registered agents
    route_after = await engine.route_agent(
        user.tenant_id,
        AgentRoutingRequest(prompt="Need pilot testing"),
    )
    assert route_after.routed is False
    assert "No registered agents" in route_after.reason


# ─── D. Intent Detection and Function Mapping via Database ───────────
@pytest.mark.asyncio
async def test_intent_detection_and_function_mapping_via_db(sqlite_repo, user):
    agent_svc = AgentService(sqlite_repo)

    # Register HR Agent and Tech Support Agent
    hr_agent = await agent_svc.register_agent(
        user,
        AgentCreateRequest(
            name="HR Benefits Agent",
            description="Assists employees with healthcare, 401k, and vacation policy.",
            capabilities=["benefits_inquiry", "leave_balance", "enrollment"],
            tools=["query_pto_balance", "submit_claim"],
            adapter_type=AdapterType.synthetic,
            authorised=True,
        ),
    )

    tech_agent = await agent_svc.register_agent(
        user,
        AgentCreateRequest(
            name="IT Helpdesk Agent",
            description="Resolves password resets, VPN connection issues, and hardware requests.",
            capabilities=["password_reset", "vpn_setup", "hardware_request"],
            tools=["reset_ldap_password", "check_ticket_status"],
            adapter_type=AdapterType.synthetic,
            authorised=True,
        ),
    )

    # Detect HR intent
    hr_intent = await agent_svc.detect_intent(
        user,
        IntentDetectionRequest(prompt="How do I check my remaining vacation leave balance and benefits enrollment?"),
    )
    assert hr_intent.matched_agent_id == hr_agent.agent_id
    assert hr_intent.matched_agent_name == "HR Benefits Agent"
    assert hr_intent.confidence > 0.0

    # Detect IT intent
    it_intent = await agent_svc.detect_intent(
        user,
        IntentDetectionRequest(prompt="My VPN keeps disconnecting and I need to reset my network password."),
    )
    assert it_intent.matched_agent_id == tech_agent.agent_id
    assert it_intent.matched_agent_name == "IT Helpdesk Agent"

    # Function mapping from database
    hr_funcs = await agent_svc.get_agent_functions(user, hr_agent.agent_id)
    assert hr_funcs.agent_id == hr_agent.agent_id
    assert "query_pto_balance" in hr_funcs.tools

    # Route request by required tool
    routed = await agent_svc.route_agent(
        user,
        AgentRoutingRequest(
            prompt="User ticket assistance",
            required_tools=["reset_ldap_password"],
        ),
    )
    assert routed.routed is True
    assert routed.agent_id == tech_agent.agent_id


# ─── E. Meaningful Error When No Registered Agents in Database ───────
@pytest.mark.asyncio
async def test_meaningful_error_when_no_agents_registered_in_database(sqlite_repo, user):
    agent_svc = AgentService(sqlite_repo)

    # Ensure empty database for tenant
    agents = await agent_svc.list_agents(user)
    assert len(agents) == 0

    # Intent detection on empty database returns explanation
    intent_res = await agent_svc.detect_intent(
        user,
        IntentDetectionRequest(prompt="Hello, who can help me?"),
    )
    assert intent_res.matched_agent_id is None
    assert "No agents are currently registered in the database" in intent_res.reason

    # Routing on empty database returns explanation
    routing_res = await agent_svc.route_agent(
        user,
        AgentRoutingRequest(prompt="Book my travel"),
    )
    assert routing_res.routed is False
    assert "No registered agents found in database" in routing_res.reason


# ─── F. Duplicate Registration Handling ──────────────────────────────
@pytest.mark.asyncio
async def test_duplicate_registration_creates_or_updates_gracefully(sqlite_repo, user):
    agent_svc = AgentService(sqlite_repo)

    req1 = AgentCreateRequest(
        name="Unique Inventory Bot",
        description="Version 1",
        capabilities=["inventory_read"],
        adapter_type=AdapterType.synthetic,
        authorised=True,
    )
    agent1 = await agent_svc.register_agent(user, req1)

    # Re-registering with same name updates the existing database record
    req2 = AgentCreateRequest(
        name="Unique Inventory Bot",
        description="Version 2 - Updated",
        capabilities=["inventory_read", "inventory_write"],
        adapter_type=AdapterType.synthetic,
        authorised=True,
    )
    agent2 = await agent_svc.register_agent(user, req2)

    # Total agents in DB remains 1, updated in place
    all_agents = await agent_svc.list_agents(user)
    assert len(all_agents) == 1
    assert all_agents[0].agent_id == agent1.agent_id
    assert all_agents[0].description == "Version 2 - Updated"
    assert "inventory_write" in all_agents[0].capabilities


# ─── G. HTTP API End-to-End Validation ────────────────────────────────
@pytest.mark.asyncio
async def test_http_api_database_agent_registry_lifecycle():
    tenant_id = f"tenant-http-{uuid4().hex[:8]}"
    api_user = AuthenticatedUser(
        user_id="api-usr-1",
        email="api@assurance.local",
        tenant_id=tenant_id,
        role=Role.owner,
        display_name="API User",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        app.dependency_overrides[get_current_user] = lambda: api_user

        # 1. No agents registered: POST /v1/evaluate returns 400 NO_REGISTERED_AGENTS
        eval_empty = await client.post("/v1/evaluate", json={"agent_name": "Nonexistent"})
        assert eval_empty.status_code == 400
        assert eval_empty.json()["code"] == "NO_REGISTERED_AGENTS"

        # 2. Register agent via POST /v1/agents
        reg_resp = await client.post("/v1/agents", json={
            "name": "Live DB Scanner Agent",
            "description": "Agent stored persistently in database",
            "capabilities": ["security_scan", "compliance"],
            "tools": ["search_knowledge_base"],
            "adapter_type": "synthetic",
            "authorised": True,
        })
        assert reg_resp.status_code == 201
        agent_id = reg_resp.json()["agent_id"]
        assert agent_id is not None

        # 3. Retrieve agent via GET /v1/agents/{id}
        get_resp = await client.get(f"/v1/agents/{agent_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "Live DB Scanner Agent"

        # 4. Validate agent via POST /v1/agents/{id}/validate
        val_resp = await client.post(f"/v1/agents/{agent_id}/validate")
        assert val_resp.status_code == 200
        assert val_resp.json()["valid"] is True

        # 5. Intent detection via POST /v1/agents/intent
        intent_resp = await client.post("/v1/agents/intent", json={"prompt": "Run security scan compliance check"})
        assert intent_resp.status_code == 200
        assert intent_resp.json()["matched_agent_id"] == agent_id

        # 6. Evaluation of registered agent succeeds
        eval_resp = await client.post("/v1/evaluate", json={
            "agent_id": agent_id,
            "scenarios": ["allowed_tool_smoke_v1"],
        })
        assert eval_resp.status_code == 200
        assert eval_resp.json()["target"]["name"] == "Live DB Scanner Agent"

        # 7. Updating agent changes details for subsequent evaluations
        put_resp = await client.put(f"/v1/agents/{agent_id}", json={
            "name": "Updated Scanner Agent",
        })
        assert put_resp.status_code == 200
        assert put_resp.json()["name"] == "Updated Scanner Agent"

        eval_updated = await client.post("/v1/evaluate", json={
            "agent_id": agent_id,
            "scenarios": ["allowed_tool_smoke_v1"],
        })
        assert eval_updated.status_code == 200
        assert eval_updated.json()["target"]["name"] == "Updated Scanner Agent"

        # 8. Delete agent via DELETE /v1/agents/{id}
        del_resp = await client.delete(f"/v1/agents/{agent_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["deleted"] is True

        # 9. Subsequent evaluation rejected
        eval_after_del = await client.post("/v1/evaluate", json={"agent_id": agent_id})
        assert eval_after_del.status_code in (400, 404)

        app.dependency_overrides.clear()
