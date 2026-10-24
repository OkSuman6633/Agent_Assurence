from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field, HttpUrl, field_validator

class AdapterType(str, Enum):
    http = "http"
    synthetic = "synthetic"

class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    adapter_type: AdapterType = AdapterType.http
    endpoint_url: HttpUrl | None = None
    allowed_hosts: list[str] = Field(default_factory=list)
    # Name of an environment variable holding the token, never the token itself.
    auth_env_var: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{1,127}$")
    timeout_seconds: float = Field(default=15.0, ge=1.0, le=60.0)
    authorised: bool = False
    scope_description: str = Field(default="", max_length=2000)

    @field_validator("allowed_hosts")
    @classmethod
    def normalize_hosts(cls, values):
        return [v.strip().lower().rstrip(".") for v in values if v.strip()]

class AgentView(BaseModel):
    agent_id: str
    name: str
    adapter_type: AdapterType
    endpoint_url: str | None
    allowed_hosts: list[str]
    timeout_seconds: float
    authorised: bool
    scope_description: str

class RunRequest(BaseModel):
    scenario_pack: str = Field(default="core-v1", min_length=1, max_length=100)
    scenarios: list[str] = Field(default_factory=lambda: [
        "allowed_tool_smoke_v1",
        "prompt_injection_boundary_v1",
        "approval_gate_v1",
        "retry_idempotency_v1",
    ], min_length=1, max_length=30)
    idempotency_key: str = Field(min_length=8, max_length=200)
    model_budget_tokens: int = Field(default=5000, ge=1, le=100000)

class ScenarioResult(BaseModel):
    scenario_id: str
    verdict: Literal["PASS", "FAIL", "INCONCLUSIVE", "NOT RUN"]
    summary: str
    trace: dict[str, Any]
    evidence_complete: bool

class RunView(BaseModel):
    run_id: str
    agent_id: str
    status: str
    scenario_pack: str
    results: list[ScenarioResult]
    created_at: str
    summary: dict[str, int]
