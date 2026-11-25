"""Service layer for Agent Assurance Laboratory.

Contains business logic for assessment lifecycle, run execution,
findings management, reviews, reports, and regression comparison.

The service layer uses the repository abstraction and does NOT
directly access in-memory dicts or cloud storage.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from .adapter import AdapterError, invoke_agent
from .auth import AuthenticatedUser
from .models import (
    AgentCreateRequest,
    AgentFunctionMappingResponse,
    AgentManifest,
    AgentRoutingRequest,
    AgentRoutingResponse,
    AgentUpdateRequest,
    AgentValidationResponse,
    AgentView,
    Assessment,
    AssessmentCreateRequest,
    AssessmentStatus,
    AuditEvent,
    Finding,
    FindingStatus,
    IntentDetectionRequest,
    IntentDetectionResponse,
    PricingPlan,
    RegressionComparison,
    ReportArtifact,
    ReportFormat,
    Review,
    ReviewCreateRequest,
    ReviewDecision,
    Run,
    RunCreateRequest,
    RunStatus,
    ScenarioDelta,
    ScenarioResult,
    TenantEntitlement,
    UsageEvent,
    Verdict,
)
from .oracle import evaluate, evaluate_not_run
from .repository import BaseRepository
from .scenarios import get_scenario, get_scenario_ids, list_scenarios
from .security import UnsafeEndpoint, validate_endpoint
from .test_engine import DatabaseAgentRegistryEngine


class AgentService:
    def __init__(self, repo: BaseRepository):
        self.repo = repo
        self.engine = DatabaseAgentRegistryEngine(repo)

    async def register_agent(self, user: AuthenticatedUser, req: AgentCreateRequest) -> AgentView:
        if not req.authorised:
            raise ValueError("Explicit authorisation must be confirmed before registering an agent.")

        if req.adapter_type.value == "http":
            if not req.endpoint_url:
                raise ValueError("endpoint_url is required for HTTP adapter.")
            if not req.allowed_hosts:
                parsed = urlparse(req.endpoint_url)
                host = (parsed.hostname or "127.0.0.1").lower()
                req.allowed_hosts = list(set([host, "127.0.0.1", "localhost", "0.0.0.0"]))
            validate_endpoint(req.endpoint_url, req.allowed_hosts)
        elif req.endpoint_url:
            raise ValueError("Synthetic adapter must not include a remote endpoint.")

        # Check agent quota
        entitlement = await self.repo.get_entitlement(user.tenant_id)
        if entitlement:
            agents = await self.repo.list_agents(user.tenant_id)
            if len(agents) >= entitlement.agents_limit:
                raise ValueError(f"Agent limit reached ({entitlement.agents_limit}). Upgrade your plan.")

        agent_id = req.agent_id or str(uuid4())
        agent = AgentManifest(
            agent_id=agent_id,
            tenant_id=user.tenant_id,
            name=req.name,
            description=req.description,
            capabilities=req.capabilities,
            functions=req.functions,
            tools=req.tools,
            metadata=req.metadata,
            adapter_type=req.adapter_type,
            endpoint_url=req.endpoint_url,
            allowed_hosts=req.allowed_hosts,
            auth_env_var=req.auth_env_var,
            timeout_seconds=req.timeout_seconds,
            authorised=req.authorised,
            scope_description=req.scope_description,
            environment=req.environment,
            version_info=req.version_info,
        )
        saved = await self.repo.save_agent(agent)

        await self.repo.save_audit_event(AuditEvent(
            tenant_id=user.tenant_id,
            actor_id=user.user_id,
            actor_email=user.email,
            action="agent.registered",
            resource_type="agent",
            resource_id=saved.agent_id,
        ))

        return self._to_view(saved)

    async def update_agent(self, user: AuthenticatedUser, agent_id: str, req: AgentUpdateRequest) -> AgentView:
        agent = await self.repo.get_agent(user.tenant_id, agent_id)
        if not agent:
            raise KeyError(f"Agent '{agent_id}' does not exist in the database.")

        if req.name is not None:
            agent.name = req.name
        if req.description is not None:
            agent.description = req.description
        if req.capabilities is not None:
            agent.capabilities = req.capabilities
        if req.functions is not None:
            agent.functions = req.functions
        if req.tools is not None:
            agent.tools = req.tools
        if req.metadata is not None:
            agent.metadata = req.metadata
        if req.adapter_type is not None:
            agent.adapter_type = req.adapter_type
        if req.endpoint_url is not None:
            agent.endpoint_url = req.endpoint_url
        if req.allowed_hosts is not None:
            agent.allowed_hosts = req.allowed_hosts
        if req.auth_env_var is not None:
            agent.auth_env_var = req.auth_env_var
        if req.timeout_seconds is not None:
            agent.timeout_seconds = req.timeout_seconds
        if req.authorised is not None:
            agent.authorised = req.authorised
        if req.scope_description is not None:
            agent.scope_description = req.scope_description
        if req.environment is not None:
            agent.environment = req.environment
        if req.version_info is not None:
            agent.version_info = req.version_info

        agent.updated_at = datetime.now(timezone.utc).isoformat()
        saved = await self.repo.save_agent(agent)

        await self.repo.save_audit_event(AuditEvent(
            tenant_id=user.tenant_id,
            actor_id=user.user_id,
            actor_email=user.email,
            action="agent.updated",
            resource_type="agent",
            resource_id=saved.agent_id,
        ))

        return self._to_view(saved)

    async def get_agent(self, user: AuthenticatedUser, agent_id: str) -> AgentView:
        agent = await self.repo.get_agent(user.tenant_id, agent_id)
        if not agent:
            raise KeyError("Agent not found.")
        return self._to_view(agent)

    async def list_agents(self, user: AuthenticatedUser) -> list[AgentView]:
        agents = await self.repo.list_agents(user.tenant_id)
        return [self._to_view(a) for a in agents]

    async def delete_agent(self, user: AuthenticatedUser, agent_id: str) -> bool:
        agent = await self.repo.get_agent(user.tenant_id, agent_id)
        if not agent:
            raise KeyError("Agent not found.")
        deleted = await self.repo.delete_agent(user.tenant_id, agent_id)
        if deleted:
            await self.repo.save_audit_event(AuditEvent(
                tenant_id=user.tenant_id,
                actor_id=user.user_id,
                actor_email=user.email,
                action="agent.deleted",
                resource_type="agent",
                resource_id=agent_id,
            ))
        return deleted

    async def validate_agent(self, user: AuthenticatedUser, agent_id: str) -> AgentValidationResponse:
        return await self.engine.validate_agent(user.tenant_id, agent_id)

    async def get_agent_functions(self, user: AuthenticatedUser, agent_id: str) -> AgentFunctionMappingResponse:
        return await self.engine.get_function_mapping(user.tenant_id, agent_id)

    async def detect_intent(self, user: AuthenticatedUser, req: IntentDetectionRequest) -> IntentDetectionResponse:
        return await self.engine.detect_intent(user.tenant_id, req)

    async def route_agent(self, user: AuthenticatedUser, req: AgentRoutingRequest) -> AgentRoutingResponse:
        return await self.engine.route_agent(user.tenant_id, req)

    def _to_view(self, agent: AgentManifest) -> AgentView:
        return AgentView(**{k: v for k, v in agent.model_dump().items() if k != "auth_env_var"})


class AssessmentService:
    def __init__(self, repo: BaseRepository):
        self.repo = repo

    async def create_assessment(self, user: AuthenticatedUser, req: AssessmentCreateRequest) -> Assessment:
        # Verify agent exists and belongs to tenant
        agent = await self.repo.get_agent(user.tenant_id, req.agent_id)
        if not agent:
            raise KeyError("Agent not found or not accessible.")
        if not agent.authorised:
            raise ValueError("Agent is not authorised for testing.")

        assessment = Assessment(
            tenant_id=user.tenant_id,
            title=req.title,
            description=req.description,
            scope=req.scope,
            agent_id=req.agent_id,
            owner_id=user.user_id,
            status=AssessmentStatus.configured,
        )
        assessment.compute_scope_hash()
        await self.repo.save_assessment(assessment)

        await self.repo.save_audit_event(AuditEvent(
            tenant_id=user.tenant_id,
            actor_id=user.user_id,
            actor_email=user.email,
            action="assessment.created",
            resource_type="assessment",
            resource_id=assessment.assessment_id,
            details={"title": assessment.title, "agent_id": assessment.agent_id},
        ))

        return assessment

    async def get_assessment(self, user: AuthenticatedUser, assessment_id: str) -> Assessment:
        assessment = await self.repo.get_assessment(user.tenant_id, assessment_id)
        if not assessment:
            raise KeyError("Assessment not found.")
        return assessment

    async def list_assessments(self, user: AuthenticatedUser) -> list[Assessment]:
        return await self.repo.list_assessments(user.tenant_id)


class RunService:
    def __init__(self, repo: BaseRepository, kill_switch: KillSwitchService | None = None):
        self.repo = repo
        self.kill_switch = kill_switch

    async def start_run(
        self,
        user: AuthenticatedUser,
        assessment_id: str,
        req: RunCreateRequest,
        idempotency_key: str,
        correlation_id: str = "",
    ) -> Run:
        # Operational Kill Switch check (Doc 2 §5, Doc 3 §8)
        if self.kill_switch and self.kill_switch.is_disabled(user.tenant_id):
            raise ValueError("Execution suspended: operational kill switch is active for this tenant.")

        # Validate assessment
        assessment = await self.repo.get_assessment(user.tenant_id, assessment_id)
        if not assessment:
            raise KeyError("Assessment not found.")

        # Ensure registered agents exist in database
        registered_agents = await self.repo.list_agents(user.tenant_id)
        if not registered_agents:
            raise ValueError("No registered agents are available in the database. Please register an agent before running evaluations.")

        # Idempotency check
        if idempotency_key:
            existing = await self.repo.get_run_by_idempotency_key(
                user.tenant_id, assessment_id, idempotency_key
            )
            if existing:
                return existing

        # Validate agent directly from the database
        agent = await self.repo.get_agent(user.tenant_id, assessment.agent_id)
        if not agent:
            raise KeyError(f"Agent '{assessment.agent_id}' does not exist in the database. Only agents explicitly registered in the database can be evaluated.")
        if not agent.authorised:
            raise ValueError("Agent is not authorised for testing.")

        # Quota check
        entitlement = await self.repo.get_entitlement(user.tenant_id)
        if entitlement:
            runs = await self.repo.list_runs(user.tenant_id)
            if len(runs) >= entitlement.runs_limit:
                raise ValueError(f"Run limit reached ({entitlement.runs_limit}). Upgrade your plan.")
            scenario_count = len(req.scenarios)
            if entitlement.scenarios_used + scenario_count > entitlement.scenarios_limit:
                raise ValueError(f"Scenario limit would be exceeded. Remaining: {entitlement.scenarios_limit - entitlement.scenarios_used}.")

        # Validate all scenario IDs
        for sid in req.scenarios:
            get_scenario(sid)  # raises KeyError if unknown

        # Create run record
        run = Run(
            assessment_id=assessment_id,
            agent_id=assessment.agent_id,
            tenant_id=user.tenant_id,
            status=RunStatus.running,
            scenario_pack=req.scenario_pack,
            scenarios_requested=req.scenarios,
            model_budget_tokens=req.model_budget_tokens,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id or str(uuid4()),
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        await self.repo.save_run(run)

        # Update assessment status
        await self.repo.update_assessment_status(user.tenant_id, assessment_id, AssessmentStatus.running.value)

        # Execute scenarios (synchronous for MVP; async Cloud Tasks for production)
        results: list[ScenarioResult] = []
        findings_created: list[Finding] = []

        agent_dict = agent.model_dump()

        for sid in req.scenarios:
            try:
                observed = await invoke_agent(agent_dict, run.run_id, sid, req.model_budget_tokens, hardened=req.hardened)
                verdict, summary, trace, evidence_complete = evaluate(sid, observed)
            except (AdapterError, UnsafeEndpoint, TimeoutError) as exc:
                verdict = Verdict.INCONCLUSIVE.value
                summary = f"Adapter could not establish a result ({type(exc).__name__})."
                trace = {
                    "scenario_id": sid,
                    "error_type": type(exc).__name__,
                    "correlation_id": run.correlation_id,
                }
                evidence_complete = False

            scenario_result = ScenarioResult(
                scenario_id=sid,
                verdict=verdict,
                summary=summary,
                trace=trace,
                evidence_complete=evidence_complete,
                checks_passed=trace.get("checks_passed", []),
                checks_failed=trace.get("checks_failed", []),
                checks_inconclusive=trace.get("checks_inconclusive", []),
            )
            results.append(scenario_result)

            # Auto-create findings for FAIL verdicts
            if verdict == Verdict.FAIL.value:
                scenario_def = get_scenario(sid)
                finding = Finding(
                    run_id=run.run_id,
                    assessment_id=assessment_id,
                    tenant_id=user.tenant_id,
                    scenario_id=sid,
                    category=scenario_def.category.value,
                    severity=scenario_def.severity,
                    title=f"Failed: {sid}",
                    description=summary,
                    impact=f"Scenario '{sid}' failed with prohibited actions or failed assertions.",
                    remediation=f"Review trace for {sid} and address the identified violation.",
                    evidence_refs=[f"trace:{run.run_id}:{sid}"],
                    assertion_results=trace.get("state_assertions", {}),
                    automated_verdict=Verdict.FAIL,
                )
                await self.repo.save_finding(finding)
                findings_created.append(finding)

        # Finalise run
        counts = Counter(r.verdict for r in results)
        run.results = results
        run.status = RunStatus.completed
        run.ended_at = datetime.now(timezone.utc).isoformat()
        run.summary = {v: counts.get(v, 0) for v in ["PASS", "FAIL", "INCONCLUSIVE", "NOT RUN"]}
        await self.repo.update_run(run)

        # Update assessment status
        await self.repo.update_assessment_status(user.tenant_id, assessment_id, AssessmentStatus.completed.value)

        # Record usage
        await self.repo.save_usage_event(UsageEvent(
            tenant_id=user.tenant_id,
            run_id=run.run_id,
            scenario_count=len(req.scenarios),
            compute_tokens=req.model_budget_tokens,
            billable_units=len(req.scenarios),
        ))

        # Audit event
        await self.repo.save_audit_event(AuditEvent(
            tenant_id=user.tenant_id,
            actor_id=user.user_id,
            actor_email=user.email,
            action="run.completed",
            resource_type="run",
            resource_id=run.run_id,
            correlation_id=run.correlation_id,
            details={"summary": run.summary, "findings_count": len(findings_created)},
        ))

        return run

    async def get_run(self, user: AuthenticatedUser, run_id: str) -> Run:
        run = await self.repo.get_run(user.tenant_id, run_id)
        if not run:
            raise KeyError("Run not found.")
        return run

    async def list_runs(self, user: AuthenticatedUser, assessment_id: str | None = None) -> list[Run]:
        return await self.repo.list_runs(user.tenant_id, assessment_id)


class FindingService:
    def __init__(self, repo: BaseRepository):
        self.repo = repo

    async def list_findings(self, user: AuthenticatedUser, run_id: str | None = None) -> list[Finding]:
        return await self.repo.list_findings(user.tenant_id, run_id)

    async def get_finding(self, user: AuthenticatedUser, finding_id: str) -> Finding:
        finding = await self.repo.get_finding(user.tenant_id, finding_id)
        if not finding:
            raise KeyError("Finding not found.")
        return finding

    async def create_review(
        self,
        user: AuthenticatedUser,
        finding_id: str,
        req: ReviewCreateRequest,
    ) -> Review:
        finding = await self.repo.get_finding(user.tenant_id, finding_id)
        if not finding:
            raise KeyError("Finding not found.")

        decision_to_status = {
            ReviewDecision.confirmed: FindingStatus.confirmed,
            ReviewDecision.false_positive: FindingStatus.false_positive,
            ReviewDecision.mitigated: FindingStatus.mitigated,
            ReviewDecision.accepted_risk: FindingStatus.accepted_risk,
            ReviewDecision.needs_investigation: FindingStatus.open,
        }

        new_status = decision_to_status[req.decision]

        review = Review(
            finding_id=finding_id,
            tenant_id=user.tenant_id,
            reviewer_id=user.user_id,
            reviewer_email=user.email,
            decision=req.decision,
            reason=req.reason,
            previous_status=finding.status,
            new_status=new_status,
        )
        await self.repo.save_review(review)

        # Update finding but preserve automated verdict
        finding.status = new_status
        finding.reviewer_verdict = Verdict(req.decision.value) if req.decision.value in [v.value for v in Verdict] else None
        finding.updated_at = datetime.now(timezone.utc).isoformat()
        await self.repo.update_finding(finding)

        # Audit
        await self.repo.save_audit_event(AuditEvent(
            tenant_id=user.tenant_id,
            actor_id=user.user_id,
            actor_email=user.email,
            action="finding.reviewed",
            resource_type="finding",
            resource_id=finding_id,
            details={
                "decision": req.decision.value,
                "reason": req.reason[:500],
                "previous_status": review.previous_status.value,
                "new_status": new_status.value,
            },
        ))

        return review

    async def list_reviews(self, user: AuthenticatedUser, finding_id: str) -> list[Review]:
        return await self.repo.list_reviews(user.tenant_id, finding_id)


class ReportService:
    def __init__(self, repo: BaseRepository):
        self.repo = repo

    async def generate_report(
        self,
        user: AuthenticatedUser,
        run_id: str,
        format: ReportFormat = ReportFormat.json,
    ) -> ReportArtifact:
        run = await self.repo.get_run(user.tenant_id, run_id)
        if not run:
            raise KeyError("Run not found.")

        # Generate JSON report content
        assessment = await self.repo.get_assessment(user.tenant_id, run.assessment_id)
        findings = await self.repo.list_findings(user.tenant_id, run_id)

        report_data = {
            "report_type": "agent_assurance_report",
            "report_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "assessment": {
                "assessment_id": run.assessment_id,
                "title": assessment.title if assessment else "",
                "scope": assessment.scope if assessment else "",
                "scope_hash": assessment.scope_hash if assessment else "",
            },
            "run": {
                "run_id": run.run_id,
                "status": run.status.value if isinstance(run.status, RunStatus) else run.status,
                "scenario_pack": run.scenario_pack,
                "started_at": run.started_at,
                "ended_at": run.ended_at,
                "summary": run.summary,
                "correlation_id": run.correlation_id,
            },
            "results": [r.model_dump() for r in run.results],
            "findings": [f.model_dump() for f in findings],
            "known_limitations": [
                "This assessment uses synthetic test scenarios and bounded evaluation.",
                "Results do not constitute a certification or regulatory compliance guarantee.",
                "INCONCLUSIVE results indicate missing evidence, not confirmed safety.",
            ],
        }

        artifact = ReportArtifact(
            run_id=run_id,
            tenant_id=user.tenant_id,
            format=format,
            status="completed",
            storage_path=f"reports/{user.tenant_id}/{run_id}/report.{format.value}",
            report_data=report_data,
        )
        await self.repo.save_report_artifact(artifact)

        await self.repo.save_audit_event(AuditEvent(
            tenant_id=user.tenant_id,
            actor_id=user.user_id,
            actor_email=user.email,
            action="report.generated",
            resource_type="report",
            resource_id=artifact.artifact_id,
            details={"run_id": run_id, "format": format.value},
        ))

        return artifact

    def get_report_data(self, artifact: ReportArtifact) -> dict[str, Any]:
        return artifact.report_data or getattr(artifact, "_report_data", {})


class RegressionService:
    def __init__(self, repo: BaseRepository):
        self.repo = repo

    async def compare_runs(
        self,
        user: AuthenticatedUser,
        baseline_run_id: str,
        current_run_id: str,
    ) -> RegressionComparison:
        baseline = await self.repo.get_run(user.tenant_id, baseline_run_id)
        current = await self.repo.get_run(user.tenant_id, current_run_id)

        if not baseline:
            raise KeyError("Baseline run not found.")
        if not current:
            raise KeyError("Current run not found.")

        # Build scenario verdict maps
        baseline_verdicts = {r.scenario_id: r.verdict for r in baseline.results}
        current_verdicts = {r.scenario_id: r.verdict for r in current.results}

        all_scenarios = set(baseline_verdicts.keys()) | set(current_verdicts.keys())
        deltas: list[ScenarioDelta] = []
        new_failures = 0
        resolved_failures = 0
        new_passes = 0

        for sid in sorted(all_scenarios):
            bv = baseline_verdicts.get(sid)
            cv = current_verdicts.get(sid)
            changed = bv != cv

            if changed:
                if cv == Verdict.FAIL.value and bv != Verdict.FAIL.value:
                    new_failures += 1
                if bv == Verdict.FAIL.value and cv != Verdict.FAIL.value:
                    resolved_failures += 1
                if cv == Verdict.PASS.value and bv != Verdict.PASS.value:
                    new_passes += 1

            notes = ""
            if bv is None:
                notes = "New scenario in current run"
            elif cv is None:
                notes = "Scenario removed from current run"
            elif changed:
                notes = f"Changed: {bv} → {cv}"

            deltas.append(ScenarioDelta(
                scenario_id=sid,
                baseline_verdict=Verdict(bv) if bv else None,
                current_verdict=Verdict(cv) if cv else None,
                changed=changed,
                notes=notes,
            ))

        comparison = RegressionComparison(
            baseline_run_id=baseline_run_id,
            current_run_id=current_run_id,
            tenant_id=user.tenant_id,
            overall_changed=any(d.changed for d in deltas),
            new_failures=new_failures,
            resolved_failures=resolved_failures,
            new_passes=new_passes,
            total_baseline=len(baseline.results),
            total_current=len(current.results),
            scenario_deltas=deltas,
        )

        return comparison


class BillingService:
    """Manages configurable commercial plans and usage entitlements (Doc 3 §3-4)."""

    def __init__(self, repo: BaseRepository):
        self.repo = repo

    async def seed_default_plans(self) -> None:
        """Seed or update the 4 proposed pricing plans from Doc 3 §3."""
        default_plans = [
            PricingPlan(
                plan_id="starter_assessment_v1",
                name="Starter assessment",
                description="One-off baseline evaluation for a single agent.",
                base_amount_minor=150000,  # £1,500 in minor units
                currency="GBP",
                billing_interval="one_off",
                included_agents=1,
                included_scenarios=50,
                maximum_runs=10,
                retention_days=14,
                reviewer_seats=1,
                active=True,
            ),
            PricingPlan(
                plan_id="professional_assessment_v1",
                name="Professional",
                description="Comprehensive evaluation with reviewer workshop and remediation backlog.",
                base_amount_minor=350000,  # £3,500 in minor units
                currency="GBP",
                billing_interval="one_off",
                included_agents=3,
                included_scenarios=200,
                maximum_runs=50,
                retention_days=30,
                reviewer_seats=3,
                active=True,
            ),
            PricingPlan(
                plan_id="team_regression_v1",
                name="Team regression",
                description="Monthly recurring assurance with automated regression comparisons.",
                base_amount_minor=65000,  # £650 / month in minor units
                currency="GBP",
                billing_interval="monthly",
                included_agents=1,
                included_scenarios=100,
                maximum_runs=100,
                retention_days=60,
                reviewer_seats=2,
                active=True,
            ),
            PricingPlan(
                plan_id="growth_regression_v1",
                name="Growth regression",
                description="High-cadence multi-agent assurance with scheduled execution and API access.",
                base_amount_minor=175000,  # £1,750 / month in minor units
                currency="GBP",
                billing_interval="monthly",
                included_agents=5,
                included_scenarios=800,
                maximum_runs=500,
                retention_days=90,
                reviewer_seats=5,
                active=True,
            ),
        ]
        for plan in default_plans:
            existing = await self.repo.get_plan(plan.plan_id)
            if not existing or existing.base_amount_minor == 0:
                await self.repo.save_plan(plan)

    async def list_plans(self) -> list[PricingPlan]:
        await self.seed_default_plans()
        return await self.repo.list_plans()

    async def get_plan(self, plan_id: str) -> PricingPlan:
        plan = await self.repo.get_plan(plan_id)
        if not plan:
            raise KeyError(f"Plan not found: {plan_id}")
        return plan

    async def create_or_update_plan(self, user: AuthenticatedUser, plan: PricingPlan) -> PricingPlan:
        saved = await self.repo.save_plan(plan)
        await self.repo.save_audit_event(AuditEvent(
            tenant_id=user.tenant_id,
            actor_id=user.user_id,
            actor_email=user.email,
            action="plan.updated",
            resource_type="plan",
            resource_id=plan.plan_id,
            details={"name": plan.name, "price_amount": plan.price_amount, "currency": plan.currency},
        ))
        return saved

    async def get_usage_summary(self, user: AuthenticatedUser) -> dict[str, Any]:
        entitlement = await self.repo.get_entitlement(user.tenant_id)
        if not entitlement:
            # Seed default starter entitlement for tenant
            plan = await self.repo.get_plan("starter_assessment_v1")
            entitlement = TenantEntitlement(
                tenant_id=user.tenant_id,
                plan_id="starter_assessment_v1",
                plan_name=plan.name if plan else "Starter assessment",
                agents_limit=plan.included_agents if plan else 1,
                runs_limit=plan.maximum_runs if plan else 10,
                scenarios_limit=plan.included_scenarios if plan else 50,
                retention_days=plan.retention_days if plan else 14,
            )
            await self.repo.save_entitlement(entitlement)

        plan = await self.repo.get_plan(entitlement.plan_id)
        plan_name = getattr(entitlement, "plan_name", "") or (plan.name if plan else entitlement.plan_id)
        billing_interval = plan.billing_interval if plan else "monthly"
        base_amount_minor = plan.base_amount_minor if plan else 0
        currency = plan.currency if plan else "GBP"

        runs = await self.repo.list_runs(user.tenant_id)
        agents = await self.repo.list_agents(user.tenant_id)
        events = await self.repo.list_usage_events(user.tenant_id, limit=100)

        total_scenarios_used = sum(e.scenario_count for e in events)
        total_tokens_used = sum(e.compute_tokens for e in events)

        return {
            "tenant_id": user.tenant_id,
            "plan_id": entitlement.plan_id,
            "plan_name": plan_name,
            "currency": currency,
            "base_amount_minor": base_amount_minor,
            "billing_interval": billing_interval,
            "agents_count": len(agents),
            "agents_limit": entitlement.agents_limit,
            "runs_count": len(runs),
            "runs_limit": entitlement.runs_limit,
            "scenarios_used": total_scenarios_used,
            "scenarios_limit": entitlement.scenarios_limit,
            "total_tokens_used": total_tokens_used,
            "recent_events": [e.model_dump() for e in events[-10:]],
        }


class KillSwitchService:
    """Operational emergency kill switch (Doc 2 §5, Doc 3 §8)."""

    def __init__(self, repo: BaseRepository):
        self.repo = repo
        self._global_kill_switch = False
        self._disabled_tenants: set[str] = set()

    def is_disabled(self, tenant_id: str) -> bool:
        return self._global_kill_switch or tenant_id in self._disabled_tenants

    async def set_kill_switch(
        self,
        user: AuthenticatedUser,
        enabled: bool,
        tenant_id: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        if tenant_id:
            if enabled:
                self._disabled_tenants.add(tenant_id)
            else:
                self._disabled_tenants.discard(tenant_id)
        else:
            self._global_kill_switch = enabled

        await self.repo.save_audit_event(AuditEvent(
            tenant_id=user.tenant_id,
            actor_id=user.user_id,
            actor_email=user.email,
            action="kill_switch.toggled",
            resource_type="system",
            resource_id="kill_switch",
            details={
                "enabled": enabled,
                "target_tenant": tenant_id or "global",
                "reason": reason,
            },
        ))

        return {
            "global_kill_switch": self._global_kill_switch,
            "disabled_tenants": list(self._disabled_tenants),
            "reason": reason,
        }

    def get_status(self) -> dict[str, Any]:
        return {
            "global_kill_switch": self._global_kill_switch,
            "disabled_tenants": list(self._disabled_tenants),
        }
