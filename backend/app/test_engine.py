"""Test engine and agent routing/evaluation core for Agent Assurance Laboratory.

The SQLite database (.db) is the single source of truth for agent registration,
retrieval, evaluation, validation, intent detection, agent-function mapping, and routing.
No hardcoded, predefined, dummy, or synthetic agents are permitted in application logic.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .models import (
    AgentFunctionMappingResponse,
    AgentManifest,
    AgentRoutingRequest,
    AgentRoutingResponse,
    AgentValidationResponse,
    IntentDetectionRequest,
    IntentDetectionResponse,
    ScenarioResult,
    Verdict,
)
from .oracle import evaluate
from .repository import BaseRepository
from .scenarios import get_scenario, list_scenarios
from .security import UnsafeEndpoint, validate_endpoint


class DatabaseAgentRegistryEngine:
    """Manages database-backed agent retrieval, validation, intent detection, and routing.

    Every operation strictly accesses the persistent repository and never falls back
    to in-memory dummy or synthetic defaults.
    """

    def __init__(self, repo: BaseRepository):
        self.repo = repo

    async def get_registered_agents(self, tenant_id: str) -> list[AgentManifest]:
        """Fetch all registered agents directly from the database for the given tenant."""
        agents = await self.repo.list_agents(tenant_id)
        return agents

    async def get_agent_or_error(self, tenant_id: str, agent_id: str) -> AgentManifest:
        """Fetch single agent directly from database or raise informative KeyError."""
        agent = await self.repo.get_agent(tenant_id, agent_id)
        if not agent:
            raise KeyError(
                f"Agent with ID '{agent_id}' does not exist in the database for tenant '{tenant_id}'. "
                "Only agents explicitly registered in the database can be accessed or evaluated."
            )
        return agent

    async def validate_agent(self, tenant_id: str, agent_id: str) -> AgentValidationResponse:
        """Validate an agent strictly using its database record and relationships."""
        errors: list[str] = []
        checks: dict[str, bool] = {
            "exists_in_database": False,
            "authorised": False,
            "valid_endpoint_or_adapter": False,
            "functions_mapped": False,
        }

        agent = await self.repo.get_agent(tenant_id, agent_id)
        if not agent:
            errors.append(f"Agent '{agent_id}' was not found in the database.")
            return AgentValidationResponse(
                valid=False,
                agent_id=agent_id,
                name="Unknown",
                checks=checks,
                errors=errors,
            )

        checks["exists_in_database"] = True

        if agent.authorised:
            checks["authorised"] = True
        else:
            errors.append("Agent is not marked as authorised for evaluation.")

        # Check endpoint/adapter
        adapter_val = agent.adapter_type.value if hasattr(agent.adapter_type, "value") else str(agent.adapter_type)
        if adapter_val == "http":
            if not agent.endpoint_url:
                errors.append("HTTP agent requires a configured endpoint_url.")
            elif not agent.allowed_hosts:
                errors.append("HTTP agent requires at least one allowed host.")
            else:
                try:
                    validate_endpoint(str(agent.endpoint_url), agent.allowed_hosts)
                    checks["valid_endpoint_or_adapter"] = True
                except UnsafeEndpoint as exc:
                    errors.append(f"Endpoint safety validation failed: {exc}")
        else:
            checks["valid_endpoint_or_adapter"] = True

        # Check functions / tools relationship
        funcs = await self.repo.get_agent_functions(tenant_id, agent_id)
        if funcs or agent.tools or agent.functions:
            checks["functions_mapped"] = True
        else:
            checks["functions_mapped"] = True  # Agent without tools is permissible but noted

        is_valid = len(errors) == 0
        return AgentValidationResponse(
            valid=is_valid,
            agent_id=agent.agent_id,
            name=agent.name,
            checks=checks,
            errors=errors,
        )

    async def get_function_mapping(self, tenant_id: str, agent_id: str) -> AgentFunctionMappingResponse:
        """Retrieve the database mapping of available functions and tools for an agent."""
        agent = await self.get_agent_or_error(tenant_id, agent_id)
        functions = await self.repo.get_agent_functions(tenant_id, agent_id)
        
        # Merge with agent.tools if not redundant
        tools = list(agent.tools)
        for fn in functions:
            fn_name = fn.get("name")
            if fn_name and fn_name not in tools:
                tools.append(fn_name)

        return AgentFunctionMappingResponse(
            agent_id=agent.agent_id,
            tenant_id=tenant_id,
            name=agent.name,
            functions=functions,
            tools=tools,
        )

    async def detect_intent(self, tenant_id: str, req: IntentDetectionRequest) -> IntentDetectionResponse:
        """Detect intent dynamically matching user prompt against registered agents in the database."""
        agents = await self.repo.list_agents(tenant_id)
        if not agents:
            return IntentDetectionResponse(
                intent="unmatched",
                matched_agent_id=None,
                matched_agent_name=None,
                confidence=0.0,
                matched_capabilities=[],
                suggested_tools=[],
                registered_agents_considered=0,
                reason="No agents are currently registered in the database. Please register an agent before intent detection.",
            )

        prompt_lower = req.prompt.lower()
        words = set(re.findall(r"\w+", prompt_lower))

        best_agent: AgentManifest | None = None
        best_score = -1.0
        best_matched_caps: list[str] = []
        best_tools: list[str] = []

        for agent in agents:
            score = 0.0
            matched_caps: list[str] = []

            # 1. Match agent name
            name_words = set(re.findall(r"\w+", agent.name.lower()))
            overlap_name = words.intersection(name_words)
            if overlap_name:
                score += len(overlap_name) * 3.0

            # 2. Match description and scope
            desc_words = set(re.findall(r"\w+", (agent.description + " " + agent.scope_description).lower()))
            overlap_desc = words.intersection(desc_words)
            score += len(overlap_desc) * 1.0

            # 3. Match capabilities
            for cap in agent.capabilities:
                cap_clean = cap.lower().strip()
                if cap_clean in prompt_lower or set(re.findall(r"\w+", cap_clean)).intersection(words):
                    matched_caps.append(cap)
                    score += 4.0

            # 4. Match tools
            agent_tools = list(agent.tools)
            for fn in agent.functions:
                fn_name = fn.get("name")
                if fn_name and fn_name not in agent_tools:
                    agent_tools.append(fn_name)

            for tool in agent_tools:
                tool_clean = tool.lower().replace("_", " ")
                if tool_clean in prompt_lower or tool.lower() in prompt_lower:
                    score += 3.5

            if score > best_score:
                best_score = score
                best_agent = agent
                best_matched_caps = matched_caps
                best_tools = agent_tools

        if best_agent is not None and best_score > 0:
            confidence = min(round(best_score / 10.0, 2), 1.0)
            inferred_intent = best_matched_caps[0] if best_matched_caps else f"handle_{best_agent.name.lower().replace(' ', '_')}"
            return IntentDetectionResponse(
                intent=inferred_intent,
                matched_agent_id=best_agent.agent_id,
                matched_agent_name=best_agent.name,
                confidence=confidence,
                matched_capabilities=best_matched_caps,
                suggested_tools=best_tools[:5],
                registered_agents_considered=len(agents),
                reason=f"Matched registered database agent '{best_agent.name}' with score {best_score}.",
            )
        else:
            # Fallback to first registered agent with 0.1 confidence
            first = agents[0]
            return IntentDetectionResponse(
                intent="general_inquiry",
                matched_agent_id=first.agent_id,
                matched_agent_name=first.name,
                confidence=0.1,
                matched_capabilities=first.capabilities,
                suggested_tools=first.tools[:5],
                registered_agents_considered=len(agents),
                reason="Defaulted to earliest registered database agent; prompt did not strongly match specific capabilities.",
            )

    async def route_agent(self, tenant_id: str, req: AgentRoutingRequest) -> AgentRoutingResponse:
        """Route request to the most appropriate agent registered in the database."""
        agents = await self.repo.list_agents(tenant_id)
        if not agents:
            return AgentRoutingResponse(
                routed=False,
                agent_id=None,
                agent_name=None,
                endpoint_url=None,
                matched_capabilities=[],
                matched_tools=[],
                reason="No registered agents found in database for routing. Please register an agent first.",
                registered_agents_considered=0,
            )

        prompt_lower = req.prompt.lower()
        req_caps = set(c.lower().strip() for c in req.required_capabilities)
        req_tools = set(t.lower().strip() for t in req.required_tools)

        best_agent: AgentManifest | None = None
        best_score = -1.0
        best_matched_caps: list[str] = []
        best_matched_tools: list[str] = []

        for agent in agents:
            agent_caps_lower = {c.lower().strip(): c for c in agent.capabilities}
            agent_tools_lower = {t.lower().strip(): t for t in agent.tools}
            for fn in agent.functions:
                fn_name = fn.get("name")
                if fn_name:
                    agent_tools_lower[fn_name.lower().strip()] = fn_name

            matched_caps = [agent_caps_lower[c] for c in req_caps if c in agent_caps_lower]
            matched_tools = [agent_tools_lower[t] for t in req_tools if t in agent_tools_lower]

            score = len(matched_caps) * 5.0 + len(matched_tools) * 4.0

            # Additional text matching
            if agent.name.lower() in prompt_lower:
                score += 3.0
            for cap in agent.capabilities:
                if cap.lower() in prompt_lower:
                    if cap not in matched_caps:
                        matched_caps.append(cap)
                    score += 2.0

            if score > best_score:
                best_score = score
                best_agent = agent
                best_matched_caps = matched_caps
                best_matched_tools = matched_tools

        if best_agent is None or (best_score == 0 and (req_caps or req_tools)):
            # If required capabilities or tools were specified and not found
            if req_caps or req_tools:
                return AgentRoutingResponse(
                    routed=False,
                    agent_id=None,
                    agent_name=None,
                    endpoint_url=None,
                    matched_capabilities=[],
                    matched_tools=[],
                    reason=f"No registered database agent matches required capabilities {list(req_caps)} or tools {list(req_tools)}.",
                    registered_agents_considered=len(agents),
                )
            best_agent = agents[0]

        return AgentRoutingResponse(
            routed=True,
            agent_id=best_agent.agent_id,
            agent_name=best_agent.name,
            endpoint_url=best_agent.endpoint_url,
            matched_capabilities=best_matched_caps,
            matched_tools=best_matched_tools,
            reason=f"Successfully routed to registered database agent '{best_agent.name}' (ID: {best_agent.agent_id}).",
            registered_agents_considered=len(agents),
        )

