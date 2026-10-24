"""Repository layer for Agent Assurance Laboratory.

Provides abstract base and in-memory implementation for local development.
Production implementations (GCS + BigQuery) can swap in via dependency injection.

Design: Doc 1 §4-5 — GCS for mutable state, BigQuery for append-only events.
In-memory implementation ONLY for development; production MUST use durable storage.
"""
from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any

from .models import (
    AgentManifest,
    AgentView,
    Assessment,
    AuditEvent,
    Finding,
    PricingPlan,
    RegressionComparison,
    ReportArtifact,
    Review,
    Run,
    TenantEntitlement,
    UsageEvent,
)


class BaseRepository(ABC):
    """Abstract repository interface."""

    # ─── Agents ───────────────────────────────────────────────────────
    @abstractmethod
    async def save_agent(self, agent: AgentManifest) -> AgentManifest: ...
    @abstractmethod
    async def get_agent(self, tenant_id: str, agent_id: str) -> AgentManifest | None: ...
    @abstractmethod
    async def list_agents(self, tenant_id: str) -> list[AgentManifest]: ...

    # ─── Assessments ──────────────────────────────────────────────────
    @abstractmethod
    async def save_assessment(self, assessment: Assessment) -> Assessment: ...
    @abstractmethod
    async def get_assessment(self, tenant_id: str, assessment_id: str) -> Assessment | None: ...
    @abstractmethod
    async def list_assessments(self, tenant_id: str) -> list[Assessment]: ...
    @abstractmethod
    async def update_assessment_status(self, tenant_id: str, assessment_id: str, status: str) -> None: ...

    # ─── Runs ─────────────────────────────────────────────────────────
    @abstractmethod
    async def save_run(self, run: Run) -> Run: ...
    @abstractmethod
    async def get_run(self, tenant_id: str, run_id: str) -> Run | None: ...
    @abstractmethod
    async def list_runs(self, tenant_id: str, assessment_id: str | None = None) -> list[Run]: ...
    @abstractmethod
    async def update_run(self, run: Run) -> Run: ...
    @abstractmethod
    async def get_run_by_idempotency_key(self, tenant_id: str, assessment_id: str, key: str) -> Run | None: ...

    # ─── Findings ─────────────────────────────────────────────────────
    @abstractmethod
    async def save_finding(self, finding: Finding) -> Finding: ...
    @abstractmethod
    async def get_finding(self, tenant_id: str, finding_id: str) -> Finding | None: ...
    @abstractmethod
    async def list_findings(self, tenant_id: str, run_id: str | None = None) -> list[Finding]: ...
    @abstractmethod
    async def update_finding(self, finding: Finding) -> Finding: ...

    # ─── Reviews ──────────────────────────────────────────────────────
    @abstractmethod
    async def save_review(self, review: Review) -> Review: ...
    @abstractmethod
    async def list_reviews(self, tenant_id: str, finding_id: str) -> list[Review]: ...

    # ─── Audit Events ─────────────────────────────────────────────────
    @abstractmethod
    async def save_audit_event(self, event: AuditEvent) -> None: ...
    @abstractmethod
    async def list_audit_events(self, tenant_id: str, limit: int = 100) -> list[AuditEvent]: ...

    # ─── Pricing & Entitlements ───────────────────────────────────────
    @abstractmethod
    async def get_entitlement(self, tenant_id: str) -> TenantEntitlement | None: ...
    @abstractmethod
    async def save_entitlement(self, entitlement: TenantEntitlement) -> None: ...
    @abstractmethod
    async def save_usage_event(self, event: UsageEvent) -> None: ...
    @abstractmethod
    async def list_usage_events(self, tenant_id: str, limit: int = 100) -> list[UsageEvent]: ...

    # ─── Plans ────────────────────────────────────────────────────────
    @abstractmethod
    async def save_plan(self, plan: PricingPlan) -> PricingPlan: ...
    @abstractmethod
    async def get_plan(self, plan_id: str) -> PricingPlan | None: ...
    @abstractmethod
    async def list_plans(self) -> list[PricingPlan]: ...

    # ─── Reports ──────────────────────────────────────────────────────
    @abstractmethod
    async def save_report_artifact(self, artifact: ReportArtifact) -> ReportArtifact: ...
    @abstractmethod
    async def get_report_artifact(self, tenant_id: str, artifact_id: str) -> ReportArtifact | None: ...


class InMemoryRepository(BaseRepository):
    """Development-only in-memory implementation. NOT for production.

    Thread-safety is NOT guaranteed. Use only for local dev/testing.
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentManifest] = {}
        self._assessments: dict[str, Assessment] = {}
        self._runs: dict[str, Run] = {}
        self._findings: dict[str, Finding] = {}
        self._reviews: dict[str, Review] = {}
        self._audit_events: list[AuditEvent] = []
        self._entitlements: dict[str, TenantEntitlement] = {}
        self._usage_events: list[UsageEvent] = []
        self._plans: dict[str, PricingPlan] = {}
        self._report_artifacts: dict[str, ReportArtifact] = {}
        self._idempotency_index: dict[str, str] = {}  # "tenant:assessment:key" -> run_id

    # ─── Agents ───────────────────────────────────────────────────────
    async def save_agent(self, agent: AgentManifest) -> AgentManifest:
        self._agents[agent.agent_id] = copy.deepcopy(agent)
        return agent

    async def get_agent(self, tenant_id: str, agent_id: str) -> AgentManifest | None:
        agent = self._agents.get(agent_id)
        if agent and agent.tenant_id == tenant_id:
            return copy.deepcopy(agent)
        return None

    async def list_agents(self, tenant_id: str) -> list[AgentManifest]:
        return [copy.deepcopy(a) for a in self._agents.values() if a.tenant_id == tenant_id]

    # ─── Assessments ──────────────────────────────────────────────────
    async def save_assessment(self, assessment: Assessment) -> Assessment:
        self._assessments[assessment.assessment_id] = copy.deepcopy(assessment)
        return assessment

    async def get_assessment(self, tenant_id: str, assessment_id: str) -> Assessment | None:
        a = self._assessments.get(assessment_id)
        if a and a.tenant_id == tenant_id:
            return copy.deepcopy(a)
        return None

    async def list_assessments(self, tenant_id: str) -> list[Assessment]:
        return [copy.deepcopy(a) for a in self._assessments.values() if a.tenant_id == tenant_id]

    async def update_assessment_status(self, tenant_id: str, assessment_id: str, status: str) -> None:
        a = self._assessments.get(assessment_id)
        if a and a.tenant_id == tenant_id:
            a.status = status

    # ─── Runs ─────────────────────────────────────────────────────────
    async def save_run(self, run: Run) -> Run:
        self._runs[run.run_id] = copy.deepcopy(run)
        if run.idempotency_key:
            idem_key = f"{run.tenant_id}:{run.assessment_id}:{run.idempotency_key}"
            self._idempotency_index[idem_key] = run.run_id
        return run

    async def get_run(self, tenant_id: str, run_id: str) -> Run | None:
        r = self._runs.get(run_id)
        if r and r.tenant_id == tenant_id:
            return copy.deepcopy(r)
        return None

    async def list_runs(self, tenant_id: str, assessment_id: str | None = None) -> list[Run]:
        result = [copy.deepcopy(r) for r in self._runs.values() if r.tenant_id == tenant_id]
        if assessment_id:
            result = [r for r in result if r.assessment_id == assessment_id]
        return result

    async def update_run(self, run: Run) -> Run:
        self._runs[run.run_id] = copy.deepcopy(run)
        return run

    async def get_run_by_idempotency_key(self, tenant_id: str, assessment_id: str, key: str) -> Run | None:
        idem_key = f"{tenant_id}:{assessment_id}:{key}"
        run_id = self._idempotency_index.get(idem_key)
        if run_id:
            return await self.get_run(tenant_id, run_id)
        return None

    # ─── Findings ─────────────────────────────────────────────────────
    async def save_finding(self, finding: Finding) -> Finding:
        self._findings[finding.finding_id] = copy.deepcopy(finding)
        return finding

    async def get_finding(self, tenant_id: str, finding_id: str) -> Finding | None:
        f = self._findings.get(finding_id)
        if f and f.tenant_id == tenant_id:
            return copy.deepcopy(f)
        return None

    async def list_findings(self, tenant_id: str, run_id: str | None = None) -> list[Finding]:
        result = [copy.deepcopy(f) for f in self._findings.values() if f.tenant_id == tenant_id]
        if run_id:
            result = [f for f in result if f.run_id == run_id]
        return result

    async def update_finding(self, finding: Finding) -> Finding:
        self._findings[finding.finding_id] = copy.deepcopy(finding)
        return finding

    # ─── Reviews ──────────────────────────────────────────────────────
    async def save_review(self, review: Review) -> Review:
        self._reviews[review.review_id] = copy.deepcopy(review)
        return review

    async def list_reviews(self, tenant_id: str, finding_id: str) -> list[Review]:
        return [
            copy.deepcopy(r) for r in self._reviews.values()
            if r.tenant_id == tenant_id and r.finding_id == finding_id
        ]

    # ─── Audit Events ─────────────────────────────────────────────────
    async def save_audit_event(self, event: AuditEvent) -> None:
        self._audit_events.append(copy.deepcopy(event))

    async def list_audit_events(self, tenant_id: str, limit: int = 100) -> list[AuditEvent]:
        events = [copy.deepcopy(e) for e in self._audit_events if e.tenant_id == tenant_id]
        return events[-limit:]

    # ─── Pricing & Entitlements ───────────────────────────────────────
    async def get_entitlement(self, tenant_id: str) -> TenantEntitlement | None:
        e = self._entitlements.get(tenant_id)
        return copy.deepcopy(e) if e else None

    async def save_entitlement(self, entitlement: TenantEntitlement) -> None:
        self._entitlements[entitlement.tenant_id] = copy.deepcopy(entitlement)

    async def save_usage_event(self, event: UsageEvent) -> None:
        self._usage_events.append(copy.deepcopy(event))

    async def list_usage_events(self, tenant_id: str, limit: int = 100) -> list[UsageEvent]:
        events = [copy.deepcopy(e) for e in self._usage_events if e.tenant_id == tenant_id]
        return events[-limit:]

    # ─── Plans ────────────────────────────────────────────────────────
    async def save_plan(self, plan: PricingPlan) -> PricingPlan:
        self._plans[plan.plan_id] = copy.deepcopy(plan)
        return plan

    async def get_plan(self, plan_id: str) -> PricingPlan | None:
        p = self._plans.get(plan_id)
        return copy.deepcopy(p) if p else None

    async def list_plans(self) -> list[PricingPlan]:
        return [copy.deepcopy(p) for p in self._plans.values() if p.active]

    # ─── Reports ──────────────────────────────────────────────────────
    async def save_report_artifact(self, artifact: ReportArtifact) -> ReportArtifact:
        self._report_artifacts[artifact.artifact_id] = copy.deepcopy(artifact)
        return artifact

    async def get_report_artifact(self, tenant_id: str, artifact_id: str) -> ReportArtifact | None:
        a = self._report_artifacts.get(artifact_id)
        if a and a.tenant_id == tenant_id:
            return copy.deepcopy(a)
        return None
