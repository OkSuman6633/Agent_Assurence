import pytest
from httpx import ASGITransport, AsyncClient
import respx

from app.main import app, REPO
from app.models import AgentManifest


@pytest.mark.asyncio
async def test_evaluate_with_new_endpoint_url_auto_registers_in_db():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Provide a brand new endpoint_url "http://127.0.0.1:8099" that is not in DB
        with respx.mock(assert_all_called=False) as mock:
            mock.get("http://127.0.0.1:8099/list-apps").respond(200, json=["new_concierge"])
            mock.post("http://127.0.0.1:8099/apps/new_concierge/users/assurance-evaluator/sessions").respond(
                200, json={"id": "mock-sess-8099"}
            )
            mock.post("http://127.0.0.1:8099/run").respond(
                200,
                json=[
                    {
                        "content": {
                            "parts": [
                                {"text": "I am the New Concierge. Safe response."}
                            ]
                        }
                    }
                ],
            )

            res = await client.post(
                "/v1/evaluate",
                headers={"X-User-Role": "assessor"},
                json={
                    "endpoint_url": "http://127.0.0.1:8099",
                    "scenarios": ["allowed_tool_smoke_v1", "prompt_injection_boundary_v1"],
                },
            )

            assert res.status_code == 200, f"Expected 200 but got {res.status_code}: {res.text}"
            data = res.json()

            # Verify evaluation results returned
            assert "rules" in data
            assert len(data["rules"]) == 2
            assert data["target"]["is_saved"] is True
            assert "New Concierge" in data["target"]["name"] or "8099" in data["target"]["name"]

            # Verify it is persistently stored in SQLite .db
            db_agents = await REPO.list_agents("dev-tenant-001")
            registered = next((a for a in db_agents if a.endpoint_url == "http://127.0.0.1:8099"), None)
            assert registered is not None
            assert registered.endpoint_url == "http://127.0.0.1:8099"
            assert "127.0.0.1" in registered.allowed_hosts


@pytest.mark.asyncio
async def test_evaluate_agent_server_error_does_not_crash_uvicorn():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Mock 8002 returning 500 error from ADK run
        with respx.mock(assert_all_called=False) as mock:
            mock.get("http://127.0.0.1:8002/list-apps").respond(200, json=["travel_concierge"])
            mock.post("http://127.0.0.1:8002/apps/travel_concierge/users/assurance-evaluator/sessions").respond(
                200, json={"id": "mock-sess-500"}
            )
            mock.post("http://127.0.0.1:8002/run").respond(500, text="Internal Server Error")

            res = await client.post(
                "/v1/evaluate",
                headers={"X-User-Role": "assessor"},
                json={
                    "endpoint_url": "http://127.0.0.1:8002",
                    "scenarios": ["allowed_tool_smoke_v1"],
                },
            )

            # The uvicorn endpoint must return 200 with completed evaluation showing all checks FAILED, NOT passed
            assert res.status_code == 200, f"Expected 200 but got {res.status_code}: {res.text}"
            data = res.json()
            assert "rules" in data
            assert len(data["rules"]) == 1
            rule = data["rules"][0]
            assert data["overall_verdict"] == "NEEDS ATTENTION"
            assert rule["status"] == "NEEDS ATTENTION"
            assert rule["violation_detected"] is True
            assert "500" in rule["violation_location"]
            assert any("server_error" in c for c in rule["checks_failed"])
            assert len(rule["checks_passed"]) == 0


@pytest.mark.asyncio
async def test_all_rules_fail_when_agent_server_returns_500():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with respx.mock(assert_all_called=False) as mock:
            mock.get("http://127.0.0.1:8002/list-apps").respond(200, json=["travel_concierge"])
            mock.post("http://127.0.0.1:8002/apps/travel_concierge/users/assurance-evaluator/sessions").respond(
                200, json={"id": "mock-sess-all-500"}
            )
            mock.post("http://127.0.0.1:8002/run").respond(500, text="Internal Server Error: Vertex AI Quota Exceeded")

            res = await client.post(
                "/v1/evaluate",
                headers={"X-User-Role": "assessor"},
                json={
                    "endpoint_url": "http://127.0.0.1:8002",
                    "scenarios": [
                        "allowed_tool_smoke_v1",
                        "prompt_injection_boundary_v1",
                        "approval_gate_v1",
                    ],
                },
            )

            assert res.status_code == 200
            data = res.json()
            assert data["overall_verdict"] == "NEEDS ATTENTION"
            assert len(data["rules"]) == 3
            for r in data["rules"]:
                assert r["status"] == "NEEDS ATTENTION"
                assert r["violation_detected"] is True
                assert "500" in r["violation_location"]
                assert any("server_error" in c for c in r["checks_failed"])
                assert len(r["checks_passed"]) == 0


@pytest.mark.asyncio
async def test_evaluate_returns_clear_error_when_port_has_no_agent():
    import httpx

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with respx.mock(assert_all_called=False) as mock:
            mock.get("http://127.0.0.1:8097/list-apps").mock(side_effect=httpx.ConnectError("Connection refused"))
            mock.post("http://127.0.0.1:8097/v1/agent/run").mock(side_effect=httpx.ConnectError("Connection refused"))

            res = await client.post(
                "/v1/evaluate",
                headers={"X-User-Role": "assessor"},
                json={
                    "endpoint_url": "http://127.0.0.1:8097",
                    "scenarios": ["allowed_tool_smoke_v1"],
                },
            )

            assert res.status_code == 502
            data = res.json()
            assert data["code"] == "AGENT_UNREACHABLE"
            assert "No agent is running" in data["message"]
            assert "8097" in data["message"]


@pytest.mark.asyncio
async def test_evaluate_deployed_link_adapts_prompt_and_reports_rejection_reason():
    import json

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with respx.mock(assert_all_called=False) as mock:
            mock.get("http://127.0.0.1:8098/list-apps").respond(404)

            def chat_handler(request):
                body = json.loads(request.content.decode())
                # Reject full Assurance payload with 422, accept {"prompt": ...}
                if "prompt" not in body:
                    return respx.MockResponse(422, json={"detail": "Field 'prompt' required"})
                return respx.MockResponse(200, json={"response": "I cannot comply, but no tool telemetry is exposed."})

            mock.post("http://127.0.0.1:8098/chat").mock(side_effect=chat_handler)

            res = await client.post(
                "/v1/evaluate",
                headers={"X-User-Role": "assessor"},
                json={
                    "endpoint_url": "http://127.0.0.1:8098/chat",
                    "scenarios": ["allowed_tool_smoke_v1"],
                },
            )

            assert res.status_code == 200
            data = res.json()
            rule = data["rules"][0]
            assert "I cannot comply" in rule["agent_output"]


@pytest.mark.asyncio
async def test_evaluate_rejected_endpoint_reports_exact_rejection_reason():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with respx.mock(assert_all_called=False) as mock:
            mock.get("http://127.0.0.1:8096/list-apps").respond(404)
            mock.post("http://127.0.0.1:8096/chat").respond(
                401, json={"detail": "Invalid API token for agent"}
            )

            res = await client.post(
                "/v1/evaluate",
                headers={"X-User-Role": "assessor"},
                json={
                    "endpoint_url": "http://127.0.0.1:8096/chat",
                    "scenarios": ["allowed_tool_smoke_v1"],
                },
            )

            assert res.status_code == 200
            data = res.json()
            assert data["overall_verdict"] == "INCONCLUSIVE"
            rule = data["rules"][0]
            assert rule["status"] == "INCONCLUSIVE"
            assert "401" in rule["rejection_reason"]
            assert "Invalid API token" in rule["rejection_reason"]
