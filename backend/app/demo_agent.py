"""Synthetic customer agent endpoint for safe integration testing only (Doc 1 §2 & Doc 4 §4).

Listens on /v1/agent/run and emits observable tool events and state assertions.
Supports `?hardened=true` to demonstrate remediation and regression comparison.
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
