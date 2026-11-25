"""Repository layer for Agent Assurance Laboratory.

Provides abstract base, in-memory implementation for testing,
and persistent SQLite implementation storing state in a .db file.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import secrets
import sqlite3
import threading
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime, timedelta, timezone
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


# ─── RBAC & Authentication Helpers ────────────────────────────────────
DEFAULT_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "platform_admin": [
        "agents:write", "agents:read", "agents:delete",
        "assessments:write", "assessments:read",
        "runs:execute", "runs:read",
        "findings:read", "reviews:write",
        "reports:generate", "reports:read",
        "users:manage",
        "plans:manage", "plans:read",
        "kill_switch:manage",
    ],
    "owner": [
        "agents:write", "agents:read", "agents:delete",
        "assessments:write", "assessments:read",
        "runs:execute", "runs:read",
        "findings:read", "reviews:write",
        "reports:generate", "reports:read",
        "users:manage",
        "plans:manage", "plans:read",
        "kill_switch:manage",
    ],
    "assessor": [
        "agents:write", "agents:read",
        "assessments:write", "assessments:read",
        "runs:execute", "runs:read",
        "findings:read",
        "reports:read",
        "plans:read",
    ],
    "reviewer": [
        "agents:read",
        "assessments:read",
        "runs:read",
        "findings:read", "reviews:write",
        "reports:generate", "reports:read",
        "plans:read",
    ],
    "viewer": [
        "agents:read",
        "assessments:read",
        "runs:read",
        "findings:read",
        "reports:read",
        "plans:read",
    ],
}

DEFAULT_USERS: list[dict[str, Any]] = [
    {
        "user_id": "usr-owner-001",
        "email": "dev@assurance.local",
        "password": "Password123!",
        "display_name": "Development Owner",
        "tenant_id": "dev-tenant-001",
        "role": "owner",
    },
    {
        "user_id": "usr-admin-001",
        "email": "admin@assurance.local",
        "password": "Admin123!",
        "display_name": "Platform Administrator",
        "tenant_id": "dev-tenant-001",
        "role": "platform_admin",
    },
    {
        "user_id": "usr-assessor-001",
        "email": "assessor@assurance.local",
        "password": "Assessor123!",
        "display_name": "Senior Safety Assessor",
        "tenant_id": "dev-tenant-001",
        "role": "assessor",
    },
    {
        "user_id": "usr-reviewer-001",
        "email": "reviewer@assurance.local",
        "password": "Reviewer123!",
        "display_name": "Lead Findings Reviewer",
        "tenant_id": "dev-tenant-001",
        "role": "reviewer",
    },
    {
        "user_id": "usr-viewer-001",
        "email": "viewer@assurance.local",
        "password": "Viewer123!",
        "display_name": "Auditor & Viewer",
        "tenant_id": "dev-tenant-001",
        "role": "viewer",
    },
]

def hash_password(password: str, salt: str | None = None) -> str:
    if not salt:
        salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
    return f"{salt}:{h}"

def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False
    if ":" not in stored_hash:
        return password == stored_hash
    salt, h = stored_hash.split(":", 1)
    return hash_password(password, salt) == stored_hash

_DEFAULT_REPO: BaseRepository | None = None

def get_default_repo() -> BaseRepository:
    global _DEFAULT_REPO
    if _DEFAULT_REPO is None:
        db_path = os.getenv("AGENT_ASSURANCE_DB") or str(Path(__file__).resolve().parent.parent / "agent_assurance.db")
        _DEFAULT_REPO = SqliteRepository(db_path=db_path)
    return _DEFAULT_REPO

def set_default_repo(repo: BaseRepository) -> None:
    global _DEFAULT_REPO
    _DEFAULT_REPO = repo


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

    # ─── Users & Authentication ───────────────────────────────────────
    @abstractmethod
    async def get_user_by_email(self, email: str) -> dict[str, Any] | None: ...
    @abstractmethod
    async def get_user_by_id(self, user_id: str) -> dict[str, Any] | None: ...
    @abstractmethod
    async def list_users(self, tenant_id: str | None = None) -> list[dict[str, Any]]: ...
    @abstractmethod
    async def create_user(self, user_data: dict[str, Any]) -> dict[str, Any]: ...
    @abstractmethod
    async def update_user(self, user_id: str, updates: dict[str, Any]) -> dict[str, Any] | None: ...
    @abstractmethod
    async def delete_user(self, user_id: str) -> bool: ...
    @abstractmethod
    async def create_session(self, user_id: str, tenant_id: str, ttl_days: int = 7) -> str: ...
    @abstractmethod
    async def get_session(self, session_token: str) -> dict[str, Any] | None: ...
    @abstractmethod
    async def delete_session(self, session_token: str) -> bool: ...


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
        self._users: dict[str, dict[str, Any]] = {}
        self._sessions: dict[str, dict[str, Any]] = {}
        self._seed_default_users()

    def _seed_default_users(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for u in DEFAULT_USERS:
            perms = DEFAULT_ROLE_PERMISSIONS.get(u["role"], DEFAULT_ROLE_PERMISSIONS["viewer"])
            self._users[u["user_id"]] = {
                "user_id": u["user_id"],
                "email": u["email"],
                "password_hash": hash_password(u["password"]),
                "display_name": u["display_name"],
                "tenant_id": u["tenant_id"],
                "role": u["role"],
                "permissions": perms,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
                "last_login_at": None,
            }

    # ─── Users & Authentication ───────────────────────────────────────
    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        clean = email.strip().lower()
        for u in self._users.values():
            if u["email"].strip().lower() == clean:
                return copy.deepcopy(u)
        return None

    async def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        u = self._users.get(user_id)
        return copy.deepcopy(u) if u else None

    async def list_users(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        if tenant_id:
            return [copy.deepcopy(u) for u in self._users.values() if u.get("tenant_id") == tenant_id]
        return [copy.deepcopy(u) for u in self._users.values()]

    async def create_user(self, user_data: dict[str, Any]) -> dict[str, Any]:
        uid = user_data.get("user_id") or f"usr-{uuid4().hex[:8]}"
        user = copy.deepcopy(user_data)
        user["user_id"] = uid
        if "permissions" not in user:
            user["permissions"] = DEFAULT_ROLE_PERMISSIONS.get(user.get("role", "viewer"), DEFAULT_ROLE_PERMISSIONS["viewer"])
        if "created_at" not in user:
            user["created_at"] = datetime.now(timezone.utc).isoformat()
        if "updated_at" not in user:
            user["updated_at"] = user["created_at"]
        if "is_active" not in user:
            user["is_active"] = True
        self._users[uid] = user
        return copy.deepcopy(user)

    async def update_user(self, user_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        if user_id not in self._users:
            return None
        u = self._users[user_id]
        for k, v in updates.items():
            u[k] = v
        u["updated_at"] = datetime.now(timezone.utc).isoformat()
        if "role" in updates:
            u["permissions"] = DEFAULT_ROLE_PERMISSIONS.get(u["role"], DEFAULT_ROLE_PERMISSIONS["viewer"])
        return copy.deepcopy(u)

    async def delete_user(self, user_id: str) -> bool:
        if user_id in self._users:
            del self._users[user_id]
            return True
        return False

    async def create_session(self, user_id: str, tenant_id: str, ttl_days: int = 7) -> str:
        token = f"sess_{secrets.token_urlsafe(32)}"
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=ttl_days)).isoformat()
        self._sessions[token] = {
            "session_token": token,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "expires_at": expires,
            "created_at": now.isoformat(),
        }
        return token

    async def get_session(self, session_token: str) -> dict[str, Any] | None:
        s = self._sessions.get(session_token)
        if not s:
            return None
        try:
            if datetime.fromisoformat(s["expires_at"]) < datetime.now(timezone.utc):
                del self._sessions[session_token]
                return None
        except Exception:
            pass
        return copy.deepcopy(s)

    async def delete_session(self, session_token: str) -> bool:
        return self._sessions.pop(session_token, None) is not None

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

                    CREATE TABLE IF NOT EXISTS users (
                        user_id TEXT PRIMARY KEY,
                        email TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        display_name TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        permissions_json TEXT NOT NULL,
                        is_active INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        last_login_at TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
                    CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);

                    CREATE TABLE IF NOT EXISTS sessions (
                        session_token TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
                """)
                self._seed_default_users(conn)
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

    def _seed_default_users(self, conn: sqlite3.Connection) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for u in DEFAULT_USERS:
            perms = DEFAULT_ROLE_PERMISSIONS.get(u["role"], DEFAULT_ROLE_PERMISSIONS["viewer"])
            perms_json = json.dumps(perms)
            cursor = conn.execute("SELECT user_id FROM users WHERE LOWER(TRIM(email)) = LOWER(TRIM(?))", (u["email"],))
            row = cursor.fetchone()
            if not row:
                pwd_hash = hash_password(u["password"])
                conn.execute(
                    """INSERT INTO users (user_id, email, password_hash, display_name, tenant_id, role, permissions_json, is_active, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                    (u["user_id"], u["email"], pwd_hash, u["display_name"], u["tenant_id"], u["role"], perms_json, now, now)
                )
            else:
                conn.execute("UPDATE users SET permissions_json = ? WHERE user_id = ?", (perms_json, row["user_id"]))

    def _row_to_user(self, row: sqlite3.Row) -> dict[str, Any]:
        perms = []
        try:
            perms = json.loads(row["permissions_json"])
        except Exception:
            perms = DEFAULT_ROLE_PERMISSIONS.get(row["role"], [])
        return {
            "user_id": row["user_id"],
            "email": row["email"],
            "password_hash": row["password_hash"],
            "display_name": row["display_name"],
            "tenant_id": row["tenant_id"],
            "role": row["role"],
            "permissions": perms,
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_login_at": row["last_login_at"],
        }

    # ─── Users & Authentication ───────────────────────────────────────
    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT * FROM users WHERE LOWER(TRIM(email)) = LOWER(TRIM(?))",
                    (email.strip(),),
                )
                row = cursor.fetchone()
                return self._row_to_user(row) if row else None
            finally:
                conn.close()

    async def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT * FROM users WHERE user_id = ?",
                    (user_id,),
                )
                row = cursor.fetchone()
                return self._row_to_user(row) if row else None
            finally:
                conn.close()

    async def list_users(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                if tenant_id:
                    cursor = conn.execute(
                        "SELECT * FROM users WHERE tenant_id = ? ORDER BY created_at ASC",
                        (tenant_id,),
                    )
                else:
                    cursor = conn.execute("SELECT * FROM users ORDER BY created_at ASC")
                return [self._row_to_user(r) for r in cursor.fetchall()]
            finally:
                conn.close()

    async def create_user(self, user_data: dict[str, Any]) -> dict[str, Any]:
        uid = user_data.get("user_id") or f"usr-{uuid4().hex[:8]}"
        email = user_data["email"].strip().lower()
        raw_pwd = user_data.get("password")
        pwd_hash = user_data.get("password_hash") or (hash_password(raw_pwd) if raw_pwd else "")
        display_name = user_data.get("display_name") or email.split("@")[0].capitalize()
        tenant_id = user_data.get("tenant_id", "dev-tenant-001")
        role = user_data.get("role", "viewer")
        perms = user_data.get("permissions") or DEFAULT_ROLE_PERMISSIONS.get(role, DEFAULT_ROLE_PERMISSIONS["viewer"])
        perms_json = json.dumps(perms)
        now = datetime.now(timezone.utc).isoformat()
        is_active = 1 if user_data.get("is_active", True) else 0

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO users (user_id, email, password_hash, display_name, tenant_id, role, permissions_json, is_active, created_at, updated_at, last_login_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (uid, email, pwd_hash, display_name, tenant_id, role, perms_json, is_active, now, now, None),
                )
                conn.commit()
            finally:
                conn.close()

        return {
            "user_id": uid,
            "email": email,
            "password_hash": pwd_hash,
            "display_name": display_name,
            "tenant_id": tenant_id,
            "role": role,
            "permissions": perms,
            "is_active": bool(is_active),
            "created_at": now,
            "updated_at": now,
            "last_login_at": None,
        }

    async def update_user(self, user_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        user = await self.get_user_by_id(user_id)
        if not user:
            return None

        role = updates.get("role", user["role"])
        perms = updates.get("permissions")
        if not perms and "role" in updates:
            perms = DEFAULT_ROLE_PERMISSIONS.get(role, user["permissions"])
        else:
            perms = perms or user["permissions"]

        display_name = updates.get("display_name", user["display_name"])
        raw_pwd = updates.get("password")
        pwd_hash = hash_password(raw_pwd) if raw_pwd else updates.get("password_hash", user["password_hash"])
        is_active = 1 if updates.get("is_active", user["is_active"]) else 0
        last_login = updates.get("last_login_at", user.get("last_login_at"))
        now = datetime.now(timezone.utc).isoformat()

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """UPDATE users SET display_name = ?, password_hash = ?, role = ?, permissions_json = ?, is_active = ?, updated_at = ?, last_login_at = ?
                       WHERE user_id = ?""",
                    (display_name, pwd_hash, role, json.dumps(perms), is_active, now, last_login, user_id),
                )
                conn.commit()
            finally:
                conn.close()

        return await self.get_user_by_id(user_id)

    async def delete_user(self, user_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    async def create_session(self, user_id: str, tenant_id: str, ttl_days: int = 7) -> str:
        token = f"sess_{secrets.token_urlsafe(32)}"
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=ttl_days)).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """INSERT INTO sessions (session_token, user_id, tenant_id, expires_at, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (token, user_id, tenant_id, expires, now.isoformat()),
                )
                conn.commit()
            finally:
                conn.close()
        return token

    async def get_session(self, session_token: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._get_connection()
            try:
                now_str = datetime.now(timezone.utc).isoformat()
                cursor = conn.execute(
                    "SELECT * FROM sessions WHERE session_token = ? AND expires_at > ?",
                    (session_token, now_str),
                )
                row = cursor.fetchone()
                if row:
                    return {
                        "session_token": row["session_token"],
                        "user_id": row["user_id"],
                        "tenant_id": row["tenant_id"],
                        "expires_at": row["expires_at"],
                        "created_at": row["created_at"],
                    }
                return None
            finally:
                conn.close()

    async def delete_session(self, session_token: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("DELETE FROM sessions WHERE session_token = ?", (session_token,))
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()
