"""Repository layer for Agent Assurance Laboratory.

Provides abstract base, in-memory implementation for testing,
and persistent SQLite implementation storing state in a .db file.
"""
from __future__ import annotations

import copy
import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

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
    async def get_agent_by_name(self, tenant_id: str, name: str) -> AgentManifest | None: ...
    @abstractmethod
    async def list_agents(self, tenant_id: str) -> list[AgentManifest]: ...
    @abstractmethod
    async def delete_agent(self, tenant_id: str, agent_id: str) -> bool: ...
    @abstractmethod
    async def get_agent_functions(self, tenant_id: str, agent_id: str) -> list[dict[str, Any]]: ...
    @abstractmethod
    async def save_agent_functions(self, tenant_id: str, agent_id: str, functions: list[dict[str, Any]]) -> None: ...

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
    """In-memory implementation for isolated tests."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentManifest] = {}
        self._agent_functions: dict[str, list[dict[str, Any]]] = defaultdict(list)
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
        # Check for duplicate registration by name within same tenant
        for existing_id, existing_agent in list(self._agents.items()):
            if (
                existing_agent.tenant_id == agent.tenant_id
                and existing_agent.name.strip().lower() == agent.name.strip().lower()
                and existing_id != agent.agent_id
            ):
                # Update existing record preserving its ID if none provided
                agent.agent_id = existing_id
                break

        self._agents[agent.agent_id] = copy.deepcopy(agent)
        
        # Sync functions / tools
        funcs: list[dict[str, Any]] = copy.deepcopy(agent.functions)
        for t in agent.tools:
            if not any(f.get("name") == t for f in funcs):
                funcs.append({"name": t, "description": f"Tool: {t}", "parameters": {}})
        self._agent_functions[agent.agent_id] = funcs
        return agent

    async def get_agent(self, tenant_id: str, agent_id: str) -> AgentManifest | None:
        agent = self._agents.get(agent_id)
        if agent and agent.tenant_id == tenant_id:
            return copy.deepcopy(agent)
        return None

    async def get_agent_by_name(self, tenant_id: str, name: str) -> AgentManifest | None:
        clean_name = name.strip().lower()
        for a in self._agents.values():
            if a.tenant_id == tenant_id and a.name.strip().lower() == clean_name:
                return copy.deepcopy(a)
        return None

    async def list_agents(self, tenant_id: str) -> list[AgentManifest]:
        return [copy.deepcopy(a) for a in self._agents.values() if a.tenant_id == tenant_id]

    async def delete_agent(self, tenant_id: str, agent_id: str) -> bool:
        agent = self._agents.get(agent_id)
        if agent and agent.tenant_id == tenant_id:
            del self._agents[agent_id]
            self._agent_functions.pop(agent_id, None)
            return True
        return False

    async def get_agent_functions(self, tenant_id: str, agent_id: str) -> list[dict[str, Any]]:
        agent = await self.get_agent(tenant_id, agent_id)
        if not agent:
            return []
        return copy.deepcopy(self._agent_functions.get(agent_id, []))

    async def save_agent_functions(self, tenant_id: str, agent_id: str, functions: list[dict[str, Any]]) -> None:
        agent = await self.get_agent(tenant_id, agent_id)
        if agent:
            self._agent_functions[agent_id] = copy.deepcopy(functions)
            agent.functions = copy.deepcopy(functions)
            agent.tools = [f.get("name") for f in functions if f.get("name")]
            self._agents[agent_id] = agent

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


class SqliteRepository(BaseRepository):
    """Persistent SQLite database repository.

    Stores all registered agents, assessments, runs, findings, reviews, and logs
    in a local .db file for reliable persistence across server restarts.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = Path(__file__).resolve().parent.parent / "agent_assurance.db"
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS agents (
                        agent_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        data_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_agents_tenant ON agents(tenant_id);

                    CREATE TABLE IF NOT EXISTS agent_functions (
                        id TEXT PRIMARY KEY,
                        agent_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        description TEXT,
                        parameters_json TEXT,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS idx_agent_functions_tenant_agent ON agent_functions(tenant_id, agent_id);

                    CREATE TABLE IF NOT EXISTS assessments (
                        assessment_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        agent_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        data_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_assessments_tenant ON assessments(tenant_id);

                    CREATE TABLE IF NOT EXISTS runs (
                        run_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        assessment_id TEXT NOT NULL,
                        idempotency_key TEXT,
                        status TEXT NOT NULL,
                        data_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_runs_tenant ON runs(tenant_id);
                    CREATE INDEX IF NOT EXISTS idx_runs_assessment ON runs(tenant_id, assessment_id);
                    CREATE INDEX IF NOT EXISTS idx_runs_idempotency ON runs(tenant_id, assessment_id, idempotency_key);

                    CREATE TABLE IF NOT EXISTS findings (
                        finding_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        run_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        severity TEXT NOT NULL,
                        data_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_findings_tenant ON findings(tenant_id);
                    CREATE INDEX IF NOT EXISTS idx_findings_run ON findings(tenant_id, run_id);

                    CREATE TABLE IF NOT EXISTS reviews (
                        review_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        finding_id TEXT NOT NULL,
                        data_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_reviews_finding ON reviews(tenant_id, finding_id);

                    CREATE TABLE IF NOT EXISTS audit_events (
                        event_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        data_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_audit_events_tenant ON audit_events(tenant_id, timestamp);

                    CREATE TABLE IF NOT EXISTS entitlements (
                        tenant_id TEXT PRIMARY KEY,
                        data_json TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS usage_events (
                        event_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        event_time TEXT NOT NULL,
                        data_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_usage_events_tenant ON usage_events(tenant_id, event_time);

                    CREATE TABLE IF NOT EXISTS plans (
                        plan_id TEXT PRIMARY KEY,
                        active INTEGER NOT NULL DEFAULT 1,
                        data_json TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS report_artifacts (
                        artifact_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        run_id TEXT NOT NULL,
                        data_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_reports_tenant ON report_artifacts(tenant_id, artifact_id);
                """)
                conn.commit()
            finally:
                conn.close()

    # ─── Agents ───────────────────────────────────────────────────────
    async def save_agent(self, agent: AgentManifest) -> AgentManifest:
        with self._lock:
            conn = self._get_connection()
            try:
                # Handle duplicate registrations: check if agent with same name exists under this tenant
                cursor = conn.execute(
                    "SELECT agent_id, data_json FROM agents WHERE tenant_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?))",
                    (agent.tenant_id, agent.name),
                )
                existing = cursor.fetchone()
                if existing and existing["agent_id"] != agent.agent_id:
                    # Update existing record under its registered ID
                    agent.agent_id = existing["agent_id"]

                raw_json = agent.model_dump_json()
                conn.execute(
                    "INSERT OR REPLACE INTO agents (agent_id, tenant_id, name, data_json, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (agent.agent_id, agent.tenant_id, agent.name, raw_json, agent.updated_at),
                )

                # Sync agent functions / tools to agent_functions table
                conn.execute("DELETE FROM agent_functions WHERE tenant_id = ? AND agent_id = ?", (agent.tenant_id, agent.agent_id))
                
                funcs: list[dict[str, Any]] = copy.deepcopy(agent.functions)
                for t in agent.tools:
                    if not any(f.get("name") == t for f in funcs):
                        funcs.append({"name": t, "description": f"Tool: {t}", "parameters": {}})

                for f in funcs:
                    fn_id = str(uuid4())
                    fn_name = f.get("name", "unnamed_function")
                    fn_desc = f.get("description", "")
                    params_json = json.dumps(f.get("parameters", {}))
                    conn.execute(
                        "INSERT INTO agent_functions (id, agent_id, tenant_id, name, description, parameters_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (fn_id, agent.agent_id, agent.tenant_id, fn_name, fn_desc, params_json, datetime.now(timezone.utc).isoformat()),
                    )

                conn.commit()
            finally:
                conn.close()
        return copy.deepcopy(agent)

    async def get_agent(self, tenant_id: str, agent_id: str) -> AgentManifest | None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT data_json FROM agents WHERE tenant_id = ? AND agent_id = ?",
                    (tenant_id, agent_id),
                )
                row = cursor.fetchone()
                if row:
                    return AgentManifest.model_validate_json(row["data_json"])
                return None
            finally:
                conn.close()

    async def get_agent_by_name(self, tenant_id: str, name: str) -> AgentManifest | None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT data_json FROM agents WHERE tenant_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?)) LIMIT 1",
                    (tenant_id, name),
                )
                row = cursor.fetchone()
                if row:
                    return AgentManifest.model_validate_json(row["data_json"])
                return None
            finally:
                conn.close()

    async def list_agents(self, tenant_id: str) -> list[AgentManifest]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT data_json FROM agents WHERE tenant_id = ? ORDER BY rowid ASC",
                    (tenant_id,),
                )
                return [AgentManifest.model_validate_json(row["data_json"]) for row in cursor.fetchall()]
            finally:
                conn.close()

    async def delete_agent(self, tenant_id: str, agent_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "DELETE FROM agent_functions WHERE tenant_id = ? AND agent_id = ?",
                    (tenant_id, agent_id),
                )
                cursor = conn.execute(
                    "DELETE FROM agents WHERE tenant_id = ? AND agent_id = ?",
                    (tenant_id, agent_id),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    async def get_agent_functions(self, tenant_id: str, agent_id: str) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT name, description, parameters_json FROM agent_functions WHERE tenant_id = ? AND agent_id = ? ORDER BY rowid ASC",
                    (tenant_id, agent_id),
                )
                rows = cursor.fetchall()
                if rows:
                    result = []
                    for r in rows:
                        try:
                            params = json.loads(r["parameters_json"])
                        except Exception:
                            params = {}
                        result.append({
                            "name": r["name"],
                            "description": r["description"] or "",
                            "parameters": params,
                        })
                    return result
            finally:
                conn.close()

        # Fallback to agent data_json
        agent = await self.get_agent(tenant_id, agent_id)
        if agent:
            funcs = copy.deepcopy(agent.functions)
            for t in agent.tools:
                if not any(f.get("name") == t for f in funcs):
                    funcs.append({"name": t, "description": f"Tool: {t}", "parameters": {}})
            return funcs
        return []

    async def save_agent_functions(self, tenant_id: str, agent_id: str, functions: list[dict[str, Any]]) -> None:
        agent = await self.get_agent(tenant_id, agent_id)
        if not agent:
            raise KeyError("Agent not found.")
        agent.functions = copy.deepcopy(functions)
        agent.tools = [f.get("name") for f in functions if f.get("name")]
        agent.updated_at = datetime.now(timezone.utc).isoformat()
        await self.save_agent(agent)

    # ─── Assessments ──────────────────────────────────────────────────
    async def save_assessment(self, assessment: Assessment) -> Assessment:
        raw_json = assessment.model_dump_json()
        with self._lock:
            conn = self._get_connection()
            try:
                status_str = assessment.status.value if hasattr(assessment.status, "value") else str(assessment.status)
                conn.execute(
                    "INSERT OR REPLACE INTO assessments (assessment_id, tenant_id, agent_id, status, data_json, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (assessment.assessment_id, assessment.tenant_id, assessment.agent_id, status_str, raw_json, assessment.updated_at),
                )
                conn.commit()
            finally:
                conn.close()
        return copy.deepcopy(assessment)

    async def get_assessment(self, tenant_id: str, assessment_id: str) -> Assessment | None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT data_json FROM assessments WHERE tenant_id = ? AND assessment_id = ?",
                    (tenant_id, assessment_id),
                )
                row = cursor.fetchone()
                if row:
                    return Assessment.model_validate_json(row["data_json"])
                return None
            finally:
                conn.close()

    async def list_assessments(self, tenant_id: str) -> list[Assessment]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT data_json FROM assessments WHERE tenant_id = ? ORDER BY rowid ASC",
                    (tenant_id,),
                )
                return [Assessment.model_validate_json(row["data_json"]) for row in cursor.fetchall()]
            finally:
                conn.close()

    async def update_assessment_status(self, tenant_id: str, assessment_id: str, status: str) -> None:
        a = await self.get_assessment(tenant_id, assessment_id)
        if a:
            a.status = status
            await self.save_assessment(a)

    # ─── Runs ─────────────────────────────────────────────────────────
    async def save_run(self, run: Run) -> Run:
        raw_json = run.model_dump_json()
        with self._lock:
            conn = self._get_connection()
            try:
                status_str = run.status.value if hasattr(run.status, "value") else str(run.status)
                conn.execute(
                    "INSERT OR REPLACE INTO runs (run_id, tenant_id, assessment_id, idempotency_key, status, data_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (run.run_id, run.tenant_id, run.assessment_id, run.idempotency_key or None, status_str, raw_json, run.created_at),
                )
                conn.commit()
            finally:
                conn.close()
        return copy.deepcopy(run)

    async def get_run(self, tenant_id: str, run_id: str) -> Run | None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT data_json FROM runs WHERE tenant_id = ? AND run_id = ?",
                    (tenant_id, run_id),
                )
                row = cursor.fetchone()
                if row:
                    return Run.model_validate_json(row["data_json"])
                return None
            finally:
                conn.close()

    async def list_runs(self, tenant_id: str, assessment_id: str | None = None) -> list[Run]:
        with self._lock:
            conn = self._get_connection()
            try:
                if assessment_id:
                    cursor = conn.execute(
                        "SELECT data_json FROM runs WHERE tenant_id = ? AND assessment_id = ? ORDER BY rowid ASC",
                        (tenant_id, assessment_id),
                    )
                else:
                    cursor = conn.execute(
                        "SELECT data_json FROM runs WHERE tenant_id = ? ORDER BY rowid ASC",
                        (tenant_id,),
                    )
                return [Run.model_validate_json(row["data_json"]) for row in cursor.fetchall()]
            finally:
                conn.close()

    async def update_run(self, run: Run) -> Run:
        return await self.save_run(run)

    async def get_run_by_idempotency_key(self, tenant_id: str, assessment_id: str, key: str) -> Run | None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT data_json FROM runs WHERE tenant_id = ? AND assessment_id = ? AND idempotency_key = ?",
                    (tenant_id, assessment_id, key),
                )
                row = cursor.fetchone()
                if row:
                    return Run.model_validate_json(row["data_json"])
                return None
            finally:
                conn.close()

    # ─── Findings ─────────────────────────────────────────────────────
    async def save_finding(self, finding: Finding) -> Finding:
        raw_json = finding.model_dump_json()
        with self._lock:
            conn = self._get_connection()
            try:
                status_str = finding.status.value if hasattr(finding.status, "value") else str(finding.status)
                sev_str = finding.severity.value if hasattr(finding.severity, "value") else str(finding.severity)
                conn.execute(
                    "INSERT OR REPLACE INTO findings (finding_id, tenant_id, run_id, status, severity, data_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (finding.finding_id, finding.tenant_id, finding.run_id, status_str, sev_str, raw_json, finding.created_at),
                )
                conn.commit()
            finally:
                conn.close()
        return copy.deepcopy(finding)

    async def get_finding(self, tenant_id: str, finding_id: str) -> Finding | None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT data_json FROM findings WHERE tenant_id = ? AND finding_id = ?",
                    (tenant_id, finding_id),
                )
                row = cursor.fetchone()
                if row:
                    return Finding.model_validate_json(row["data_json"])
                return None
            finally:
                conn.close()

    async def list_findings(self, tenant_id: str, run_id: str | None = None) -> list[Finding]:
        with self._lock:
            conn = self._get_connection()
            try:
                if run_id:
                    cursor = conn.execute(
                        "SELECT data_json FROM findings WHERE tenant_id = ? AND run_id = ? ORDER BY rowid ASC",
                        (tenant_id, run_id),
                    )
                else:
                    cursor = conn.execute(
                        "SELECT data_json FROM findings WHERE tenant_id = ? ORDER BY rowid ASC",
                        (tenant_id,),
                    )
                return [Finding.model_validate_json(row["data_json"]) for row in cursor.fetchall()]
            finally:
                conn.close()

    async def update_finding(self, finding: Finding) -> Finding:
        return await self.save_finding(finding)

    # ─── Reviews ──────────────────────────────────────────────────────
    async def save_review(self, review: Review) -> Review:
        raw_json = review.model_dump_json()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO reviews (review_id, tenant_id, finding_id, data_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    (review.review_id, review.tenant_id, review.finding_id, raw_json, review.created_at),
                )
                conn.commit()
            finally:
                conn.close()
        return copy.deepcopy(review)

    async def list_reviews(self, tenant_id: str, finding_id: str) -> list[Review]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT data_json FROM reviews WHERE tenant_id = ? AND finding_id = ? ORDER BY rowid ASC",
                    (tenant_id, finding_id),
                )
                return [Review.model_validate_json(row["data_json"]) for row in cursor.fetchall()]
            finally:
                conn.close()

    # ─── Audit Events ─────────────────────────────────────────────────
    async def save_audit_event(self, event: AuditEvent) -> None:
        raw_json = event.model_dump_json()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO audit_events (event_id, tenant_id, timestamp, data_json) VALUES (?, ?, ?, ?)",
                    (event.event_id, event.tenant_id, event.timestamp, raw_json),
                )
                conn.commit()
            finally:
                conn.close()

    async def list_audit_events(self, tenant_id: str, limit: int = 100) -> list[AuditEvent]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT data_json FROM audit_events WHERE tenant_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (tenant_id, limit),
                )
                rows = cursor.fetchall()
                # Return in chronological order
                return [AuditEvent.model_validate_json(r["data_json"]) for r in reversed(rows)]
            finally:
                conn.close()

    # ─── Pricing & Entitlements ───────────────────────────────────────
    async def get_entitlement(self, tenant_id: str) -> TenantEntitlement | None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT data_json FROM entitlements WHERE tenant_id = ?",
                    (tenant_id,),
                )
                row = cursor.fetchone()
                if row:
                    return TenantEntitlement.model_validate_json(row["data_json"])
                return None
            finally:
                conn.close()

    async def save_entitlement(self, entitlement: TenantEntitlement) -> None:
        raw_json = entitlement.model_dump_json()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO entitlements (tenant_id, data_json) VALUES (?, ?)",
                    (entitlement.tenant_id, raw_json),
                )
                conn.commit()
            finally:
                conn.close()

    async def save_usage_event(self, event: UsageEvent) -> None:
        raw_json = event.model_dump_json()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO usage_events (event_id, tenant_id, event_time, data_json) VALUES (?, ?, ?, ?)",
                    (event.event_id, event.tenant_id, event.event_time, raw_json),
                )
                conn.commit()
            finally:
                conn.close()

    async def list_usage_events(self, tenant_id: str, limit: int = 100) -> list[UsageEvent]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT data_json FROM usage_events WHERE tenant_id = ? ORDER BY event_time DESC LIMIT ?",
                    (tenant_id, limit),
                )
                rows = cursor.fetchall()
                return [UsageEvent.model_validate_json(r["data_json"]) for r in reversed(rows)]
            finally:
                conn.close()

    # ─── Plans ────────────────────────────────────────────────────────
    async def save_plan(self, plan: PricingPlan) -> PricingPlan:
        raw_json = plan.model_dump_json()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO plans (plan_id, active, data_json) VALUES (?, ?, ?)",
                    (plan.plan_id, 1 if plan.active else 0, raw_json),
                )
                conn.commit()
            finally:
                conn.close()
        return copy.deepcopy(plan)

    async def get_plan(self, plan_id: str) -> PricingPlan | None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT data_json FROM plans WHERE plan_id = ?",
                    (plan_id,),
                )
                row = cursor.fetchone()
                if row:
                    return PricingPlan.model_validate_json(row["data_json"])
                return None
            finally:
                conn.close()

    async def list_plans(self) -> list[PricingPlan]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT data_json FROM plans WHERE active = 1 ORDER BY rowid ASC"
                )
                return [PricingPlan.model_validate_json(row["data_json"]) for row in cursor.fetchall()]
            finally:
                conn.close()

    # ─── Reports ──────────────────────────────────────────────────────
    async def save_report_artifact(self, artifact: ReportArtifact) -> ReportArtifact:
        raw_json = artifact.model_dump_json()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO report_artifacts (artifact_id, tenant_id, run_id, data_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    (artifact.artifact_id, artifact.tenant_id, artifact.run_id, raw_json, artifact.created_at),
                )
                conn.commit()
            finally:
                conn.close()
        return copy.deepcopy(artifact)

    async def get_report_artifact(self, tenant_id: str, artifact_id: str) -> ReportArtifact | None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT data_json FROM report_artifacts WHERE tenant_id = ? AND artifact_id = ?",
                    (tenant_id, artifact_id),
                )
                row = cursor.fetchone()
                if row:
                    return ReportArtifact.model_validate_json(row["data_json"])
                return None
            finally:
                conn.close()
