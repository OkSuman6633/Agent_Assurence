from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from collections import Counter
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .schemas import AgentCreate, AgentView, RunRequest, RunView, ScenarioResult
from .adapter import invoke_agent, AdapterError
from .security import validate_endpoint, UnsafeEndpoint
from .scenarios import get_scenario
from .oracle import evaluate

app = FastAPI(title="Agent Assurance Lab — HTTP Adapter MVP", version="0.1.0",
              description="Bounded, synthetic-first evaluation of authorised HTTP agent endpoints.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

AGENTS: dict[str, dict] = {}
RUNS: dict[str, dict] = {}
IDEMPOTENCY: dict[tuple[str, str], str] = {}

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/agents", response_model=AgentView, status_code=201)
def register_agent(body: AgentCreate):
    if not body.authorised:
        raise HTTPException(400, "Explicit authorisation must be confirmed before registering an agent.")
    if body.adapter_type.value == "http":
        if not body.endpoint_url:
            raise HTTPException(400, "endpoint_url is required for HTTP adapter.")
        if not body.allowed_hosts:
            raise HTTPException(400, "At least one explicit allowed host is required.")
        try:
            validate_endpoint(str(body.endpoint_url), body.allowed_hosts)
        except UnsafeEndpoint as exc:
            raise HTTPException(400, str(exc)) from exc
    elif body.endpoint_url:
        raise HTTPException(400, "Synthetic adapter must not include a remote endpoint.")
    agent_id = str(uuid4())
    record = {
        "agent_id": agent_id, "name": body.name, "adapter_type": body.adapter_type.value,
        "endpoint_url": str(body.endpoint_url) if body.endpoint_url else None,
        "allowed_hosts": body.allowed_hosts, "auth_env_var": body.auth_env_var,
        "timeout_seconds": body.timeout_seconds, "authorised": body.authorised,
        "scope_description": body.scope_description,
    }
    AGENTS[agent_id] = record
    return AgentView(**{k:v for k,v in record.items() if k != "auth_env_var"})

@app.get("/v1/agents/{agent_id}", response_model=AgentView)
def get_agent(agent_id: str):
    agent = AGENTS.get(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found.")
    return AgentView(**{k:v for k,v in agent.items() if k != "auth_env_var"})

@app.post("/v1/agents/{agent_id}/runs", response_model=RunView, status_code=202)
async def start_run(agent_id: str, body: RunRequest, x_correlation_id: str | None = Header(default=None)):
    agent = AGENTS.get(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found.")
    if not agent["authorised"]:
        raise HTTPException(403, "Agent is not authorised for testing.")
    key = (agent_id, body.idempotency_key)
    if key in IDEMPOTENCY:
        return RUNS[IDEMPOTENCY[key]]
    for sid in body.scenarios:
        try:
            get_scenario(sid)
        except KeyError as exc:
            raise HTTPException(400, f"Unknown scenario_id: {sid}") from exc
    run_id = str(uuid4())
    results = []
    for sid in body.scenarios:
        try:
            observed = await invoke_agent(agent, run_id, sid, body.model_budget_tokens)
            verdict, summary, trace, complete = evaluate(sid, observed)
        except (AdapterError, UnsafeEndpoint, TimeoutError) as exc:
            verdict, summary, trace, complete = "INCONCLUSIVE", f"Adapter could not establish a result ({type(exc).__name__}).", {
                "scenario_id": sid, "error_type": type(exc).__name__, "correlation_id": x_correlation_id or run_id
            }, False
        results.append(ScenarioResult(scenario_id=sid, verdict=verdict, summary=summary,
                                      trace=trace, evidence_complete=complete))
    counts = Counter(r.verdict for r in results)
    run = RunView(run_id=run_id, agent_id=agent_id, status="completed", scenario_pack=body.scenario_pack,
                  results=results, created_at=datetime.now(timezone.utc).isoformat(),
                  summary={v: counts.get(v, 0) for v in ["PASS","FAIL","INCONCLUSIVE","NOT RUN"]})
    RUNS[run_id] = run
    IDEMPOTENCY[key] = run_id
    return run

@app.get("/v1/agents", response_model=list[AgentView])
def list_agents():
    return [AgentView(**{k: v for k, v in agent.items() if k != "auth_env_var"}) for agent in AGENTS.values()]

@app.get("/v1/runs", response_model=list[RunView])
def list_runs():
    return list(RUNS.values())

@app.get("/v1/runs/{run_id}", response_model=RunView)
def get_run(run_id: str):
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    return run

from fastapi.responses import FileResponse

frontend_path = Path(__file__).resolve().parent.parent.parent / "frontend"

@app.get("/")
def serve_index():
    index_file = frontend_path / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return {"message": "Agent Assurance Lab API is running. See /docs for Swagger UI."}

if frontend_path.is_dir():
    app.mount("/assets", StaticFiles(directory=str(frontend_path)), name="frontend_assets")
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")


