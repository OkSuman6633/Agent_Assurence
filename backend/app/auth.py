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


def _is_auth_disabled() -> bool:
    """Check if auth is disabled (dev-only). Strictly forbidden in production."""
    if os.getenv("ENVIRONMENT", "development").lower() == "production":
        return False
    return os.getenv("AUTH_DISABLED", "true").lower() == "true"


def _get_dev_user() -> AuthenticatedUser:
    """Return mock developer user. Only used when AUTH_DISABLED=true."""
    return AuthenticatedUser(
        user_id=os.getenv("DEV_USER_ID", "dev-user-001"),
        email=os.getenv("DEV_USER_EMAIL", "dev@assurance.local"),
        tenant_id=os.getenv("DEV_TENANT_ID", "dev-tenant-001"),
        role=Role(os.getenv("DEV_USER_ROLE", "owner")),
        display_name="Development User",
        email_verified=True,
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
    """Extract and validate authenticated user from request.

    Priority:
    1. Bearer token → Firebase verification → decode claims
    2. AUTH_DISABLED=true → development mock user
    3. No credentials → 401 Unauthorized
    """
    # Development bypass (NEVER in production)
    if _is_auth_disabled():
        return _get_dev_user()

    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Provide a Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    claims = await _verify_firebase_token(token)

    # Extract user info from Firebase claims
    user_id = claims.get("uid", claims.get("sub", ""))
    email = claims.get("email", "")
    tenant_id = claims.get("tenant_id", claims.get("custom_claims", {}).get("tenant_id", ""))
    role_str = claims.get("role", claims.get("custom_claims", {}).get("role", "viewer"))

    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: missing user ID.")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="User has no tenant assignment.")

    try:
        role = Role(role_str)
    except ValueError:
        role = Role.viewer

    return AuthenticatedUser(
        user_id=user_id,
        email=email,
        tenant_id=tenant_id,
        role=role,
        display_name=claims.get("name", ""),
        email_verified=claims.get("email_verified", False),
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
require_owner = require_role(Role.owner)
require_assessor = require_role(Role.owner, Role.assessor)
require_reviewer = require_role(Role.owner, Role.assessor, Role.reviewer)
require_viewer = require_role(Role.owner, Role.assessor, Role.reviewer, Role.viewer)
require_admin = require_role(Role.platform_admin)
