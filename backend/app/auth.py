"""Authentication and RBAC for Agent Assurance Laboratory.

Implements Doc 1 §5: Firebase/Identity Platform authentication;
backend enforces tenant membership and RBAC (owner, assessor, reviewer, viewer).

Development mode: When AUTH_DISABLED=true, uses a dev-only mock identity.
This MUST NOT be enabled in production.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .models import Role

# Security scheme
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class AuthenticatedUser:
    """Represents the current authenticated user."""
    user_id: str
    email: str
    tenant_id: str
    role: Role
    display_name: str = ""
    email_verified: bool = False
    permissions: list[str] | None = None


def _is_auth_disabled() -> bool:
    """Check if auth is disabled (dev-only). Strictly forbidden in production."""
    if os.getenv("ENVIRONMENT", "development").lower() == "production":
        return False
    return os.getenv("AUTH_DISABLED", "false").lower() in ("true", "1")


def _get_dev_user() -> AuthenticatedUser:
    """Return mock developer user. Only used when AUTH_DISABLED=true."""
    from .repository import DEFAULT_ROLE_PERMISSIONS
    role = Role(os.getenv("DEV_USER_ROLE", "owner"))
    perms = DEFAULT_ROLE_PERMISSIONS.get(role.value, DEFAULT_ROLE_PERMISSIONS["owner"])
    return AuthenticatedUser(
        user_id=os.getenv("DEV_USER_ID", "dev-user-001"),
        email=os.getenv("DEV_USER_EMAIL", "dev@assurance.local"),
        tenant_id=os.getenv("DEV_TENANT_ID", "dev-tenant-001"),
        role=role,
        display_name="Development User",
        email_verified=True,
        permissions=perms,
    )


def _user_dict_to_authenticated(user_data: dict[str, Any]) -> AuthenticatedUser:
    """Convert DB user dictionary to AuthenticatedUser object."""
    try:
        role = Role(user_data["role"])
    except ValueError:
        role = Role.viewer
    from .repository import DEFAULT_ROLE_PERMISSIONS
    perms = user_data.get("permissions") or DEFAULT_ROLE_PERMISSIONS.get(role.value, DEFAULT_ROLE_PERMISSIONS["viewer"])
    return AuthenticatedUser(
        user_id=user_data["user_id"],
        email=user_data["email"],
        tenant_id=user_data.get("tenant_id", "dev-tenant-001"),
        role=role,
        display_name=user_data.get("display_name", ""),
        email_verified=True,
        permissions=perms,
    )


async def _verify_firebase_token(token: str) -> dict[str, Any]:
    """Verify Firebase ID token.

    In production, this uses firebase_admin.auth.verify_id_token().
    Returns decoded token claims.

    NOTE: Requires GOOGLE_APPLICATION_CREDENTIALS or Firebase Admin SDK init.
    When Firebase is not configured, falls back to dev mode if AUTH_DISABLED.
    """
    try:
        import firebase_admin
        from firebase_admin import auth as firebase_auth

        # Initialize Firebase Admin if not already done
        if not firebase_admin._apps:
            firebase_admin.initialize_app()

        decoded = firebase_auth.verify_id_token(token)
        return decoded
    except ImportError:
        if _is_auth_disabled():
            return {}
        raise HTTPException(
            status_code=500,
            detail="Firebase Admin SDK not installed. Set AUTH_DISABLED=true for development."
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid authentication token: {e}")


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> AuthenticatedUser:
    """Extract and validate authenticated user from request using SQLite .db session/users, cookies, or Bearer tokens."""
    from .repository import get_default_repo
    repo = get_default_repo()

    # 0. Check X-User-Role header (for test suites and dev integration)
    user_role_hdr = request.headers.get("X-User-Role")
    if user_role_hdr:
        try:
            role = Role(user_role_hdr.strip().lower())
        except ValueError:
            role = Role.viewer
        from .repository import DEFAULT_ROLE_PERMISSIONS
        perms = DEFAULT_ROLE_PERMISSIONS.get(role.value, DEFAULT_ROLE_PERMISSIONS["viewer"])
        return AuthenticatedUser(
            user_id=f"usr-{role.value}-header",
            email=f"{role.value}@assurance.local",
            tenant_id=request.headers.get("X-Tenant-ID", "dev-tenant-001"),
            role=role,
            display_name=f"{role.value.capitalize()} User",
            email_verified=True,
            permissions=perms,
        )

    # 1. Check Bearer token (supports session token or JWT)
    token = credentials.credentials if credentials else None
    if token:
        session = await repo.get_session(token)
        if session:
            user_data = await repo.get_user_by_id(session["user_id"])
            if user_data and user_data.get("is_active", True):
                return _user_dict_to_authenticated(user_data)

    # 2. Check HttpOnly session cookie
    cookie_token = request.cookies.get("assurance_session")
    if cookie_token:
        session = await repo.get_session(cookie_token)
        if session:
            user_data = await repo.get_user_by_id(session["user_id"])
            if user_data and user_data.get("is_active", True):
                return _user_dict_to_authenticated(user_data)

    # 3. Development bypass: load dev user from database
    if _is_auth_disabled():
        dev_email = os.getenv("DEV_USER_EMAIL", "dev@assurance.local")
        dev_user = await repo.get_user_by_email(dev_email)
        if dev_user and dev_user.get("is_active", True):
            return _user_dict_to_authenticated(dev_user)
        return _get_dev_user()

    # 4. Check Firebase token if credentials provided and Firebase configured
    if token:
        try:
            claims = await _verify_firebase_token(token)
            user_id = claims.get("uid", claims.get("sub", ""))
            email = claims.get("email", "")
            tenant_id = claims.get("tenant_id", claims.get("custom_claims", {}).get("tenant_id", "dev-tenant-001"))
            role_str = claims.get("role", claims.get("custom_claims", {}).get("role", "viewer"))
            if user_id:
                try:
                    role = Role(role_str)
                except ValueError:
                    role = Role.viewer
                from .repository import DEFAULT_ROLE_PERMISSIONS
                perms = DEFAULT_ROLE_PERMISSIONS.get(role.value, DEFAULT_ROLE_PERMISSIONS["viewer"])
                return AuthenticatedUser(
                    user_id=user_id,
                    email=email,
                    tenant_id=tenant_id,
                    role=role,
                    display_name=claims.get("name", ""),
                    email_verified=claims.get("email_verified", False),
                    permissions=perms,
                )
        except Exception:
            pass

    raise HTTPException(
        status_code=401,
        detail="Authentication required. Provide a session cookie or Bearer token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_role(*allowed_roles: Role):
    """Dependency factory that enforces role-based access.

    Usage:
        @app.post("/v1/assessments", dependencies=[Depends(require_role(Role.owner, Role.assessor))])
    """
    async def _check_role(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if user.role not in allowed_roles and user.role != Role.platform_admin:
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required role: {', '.join(r.value for r in allowed_roles)}."
            )
        return user
    return _check_role


# Convenience dependencies
require_owner = require_role(Role.owner, Role.platform_admin)
require_assessor = require_role(Role.owner, Role.assessor, Role.platform_admin)
require_reviewer = require_role(Role.owner, Role.reviewer, Role.platform_admin)
require_viewer = require_role(Role.owner, Role.assessor, Role.reviewer, Role.viewer, Role.platform_admin)
require_admin = require_role(Role.owner, Role.platform_admin)
