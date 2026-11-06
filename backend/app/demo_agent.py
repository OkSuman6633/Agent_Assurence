"""Standalone synthetic demo harness (DEPRECATED per Requirement 8: Database-Driven Agent Registry).

Per Requirement 8:
All agents evaluated, retrieved, validated, or routed by the Agent Assurance Laboratory
must be explicitly registered and stored in the SQLite database (.db).
This file is kept for isolated offline reference only and is not loaded or used by the application logic.
"""
from __future__ import annotations

from typing import Any
from fastapi import FastAPI, Query
from pydantic import BaseModel

from .adapter import synthetic_response

app = FastAPI(
    title="Synthetic Demo Agent — Safe Integration Testing",
    description="Deterministic mock agent endpoint for assurance testing without external side effects.",
    version="1.0.0",
)


class AgentRequest(BaseModel):
    run_id: str
    scenario_id: str
    input: str
    expected_behavior: str
    test_context: dict[str, Any] = {}


@app.post("/v1/agent/run")
def run_agent(body: AgentRequest, hardened: bool = Query(default=False)):
    """Simulate agent execution against synthetic test context."""
    sid = body.scenario_id
    try:
        return synthetic_response(sid, hardened=hardened)
    except KeyError:
        return {
            "output": f"Unhandled scenario: {sid}",
            "tool_events": [],
            "state_assertions": {},
        }
