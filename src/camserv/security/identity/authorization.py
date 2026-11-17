"""
camserv.security.identity.authorization
======================================

Zero-Trust object-level authorization engine for CAMserv.
Enforces deny-by-default, granular resource scopes, IDOR/BOLA prevention,
and NIST SP 800-63B Authentication Assurance Level (AAL) requirements.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from camserv.security.identity.models import (
    AccountStatus,
    AuthAssuranceLevel,
    IdentityRole,
    ResourceScope,
    ResourceType,
    SessionRecord,
    UserRecord,
)
from camserv.security.identity.store import DurableIdentityStore

logger = structlog.get_logger(__name__)


# Operations that strictly mandate AAL2 (multi-factor authentication)
AAL2_MANDATORY_PERMISSIONS: frozenset[str] = frozenset({
    "evidence:export",
    "evidence:delete",
    "evidence:hold",
    "evidence:release",
    "system:config",
    "system:shutdown",
    "system:upgrade",
    "account:create",
    "account:delete",
    "account:modify_role",
    "recording:delete",
    "audit:export",
    "secrets:read",
})

# Base permissions granted by role
ROLE_BASE_PERMISSIONS: dict[IdentityRole, set[str]] = {
    IdentityRole.ADMIN: {"*"},
    IdentityRole.OPERATOR: {
        "camera:view",
        "camera:ptz",
        "stream:view",
        "recording:view",
        "recording:playback",
        "event:view",
        "event:acknowledge",
        "analytics:view",
        "system:status",
    },
    IdentityRole.VIEWER: {
        "camera:view",
        "stream:view",
        "recording:view",
        "recording:playback",
        "event:view",
        "analytics:view",
    },
    IdentityRole.AUDITOR: {
        "camera:view",
        "recording:view",
        "recording:playback",
        "event:view",
        "evidence:view",
        "audit:view",
        "audit:export",
        "analytics:view",
        "system:status",
    },
}


class AuthorizationError(Exception):
    """Base exception for authorization check failures."""


class StepUpRequiredError(AuthorizationError):
    """Raised when an operation requires higher Authentication Assurance Level (AAL2)."""
    def __init__(self, action: str, required_aal: AuthAssuranceLevel) -> None:
        self.action = action
        self.required_aal = required_aal
        super().__init__(f"Action '{action}' requires step-up authentication ({required_aal.value})")


@dataclass(slots=True)
class AuthorizationDecision:
    """Outcome of a zero-trust authorization check."""

    allowed: bool
    reason: str
    action: str
    resource_type: ResourceType
    resource_id: str
    required_aal: AuthAssuranceLevel = AuthAssuranceLevel.AAL1
    matched_scope_id: str | None = None


class ZeroTrustPolicyEngine:
    """Deny-by-default, object-level policy engine protecting surveillance assets."""

    def __init__(
        self,
        store: DurableIdentityStore,
        lockdown_manager: Any | None = None,
    ) -> None:
        self.store = store
        self.lockdown_manager = lockdown_manager

    def set_lockdown_manager(self, lockdown_manager: Any) -> None:
        """Dynamically bind emergency lockdown manager."""
        self.lockdown_manager = lockdown_manager

    def authorize(
        self,
        user: UserRecord,
        action: str,
        resource_type: ResourceType,
        resource_id: str,
        session: SessionRecord | None = None,
        associated_camera_id: str | None = None,
    ) -> AuthorizationDecision:
        """Evaluate access authorization for a user against an asset.

        Follows Zero-Trust Deny-by-Default principles:
        0. Check emergency lockdown state (blocks all non-whitelisted actions).
        1. Check account status (must be ACTIVE, not locked or suspended).
        2. Check session validity (if provided).
        3. Check Authentication Assurance Level (AAL) requirements.
        4. Check role-level permission grant.
        5. Check object-level resource scope / camera assignment (BOLA/IDOR check).
        """
        # 0. Emergency Appliance Lockdown Check
        if self.lockdown_manager and self.lockdown_manager.is_active:
            is_admin = bool(user.is_administrator or getattr(user.role, "value", str(user.role)) == "admin")
            if not self.lockdown_manager.can_perform_action(action, is_admin=is_admin):
                return AuthorizationDecision(
                    allowed=False,
                    reason=f"Emergency appliance lockdown active: action '{action}' blocked",
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                )
        # 1. Account status validation
        if user.status != AccountStatus.ACTIVE or user.is_locked():
            return AuthorizationDecision(
                allowed=False,
                reason=f"Account is {user.status.value} or locked",
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
            )

        # 2. Session validity check
        if session:
            if not session.is_active():
                return AuthorizationDecision(
                    allowed=False,
                    reason="Session is expired or revoked",
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                )

        # 3. Assurance Level (AAL) check
        if action in AAL2_MANDATORY_PERMISSIONS:
            current_aal = session.auth_assurance_level if session else (
                AuthAssuranceLevel.AAL2 if user.mfa_enabled else AuthAssuranceLevel.AAL1
            )
            if current_aal == AuthAssuranceLevel.AAL1:
                return AuthorizationDecision(
                    allowed=False,
                    reason=f"Action '{action}' requires multi-factor authentication (AAL2)",
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    required_aal=AuthAssuranceLevel.AAL2,
                )

        # 4. Object-level resource scopes take precedence (explicit grants/delegations)
        scopes = self.store.get_user_resource_scopes(user.user_id, resource_type=resource_type)
        for s in scopes:
            if s.resource_id == "*" or s.resource_id == resource_id:
                if self._check_permission_pattern(s.permissions, action):
                    return AuthorizationDecision(
                        allowed=True,
                        reason=f"Granted by explicit resource scope '{s.scope_id}'",
                        action=action,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        matched_scope_id=s.scope_id,
                    )

        # 5. Administrators have global scope unless specifically overridden
        if user.is_administrator or user.role == IdentityRole.ADMIN:
            return AuthorizationDecision(
                allowed=True,
                reason="Administrator unrestricted resource scope",
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                matched_scope_id="admin_wildcard",
            )

        # 6. Role-level permission check
        role_perms = ROLE_BASE_PERMISSIONS.get(user.role, set())
        has_role_permission = self._check_permission_pattern(role_perms, action)

        if not has_role_permission:
            return AuthorizationDecision(
                allowed=False,
                reason=f"Role '{user.role.value}' does not permit action '{action}'",
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
            )

        # Object-level check: Camera and camera-derived resources (streams, recordings)
        target_camera = associated_camera_id or (resource_id if resource_type == ResourceType.CAMERA else None)
        if target_camera:
            if "*" in user.allowed_camera_ids or target_camera in user.allowed_camera_ids:
                return AuthorizationDecision(
                    allowed=True,
                    reason=f"User has explicit assignment for camera '{target_camera}'",
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    matched_scope_id=f"camera_assignment:{target_camera}",
                )

        # If it's a camera or recording and not in allowed cameras or scopes, DENY (prevents BOLA)
        if resource_type in (ResourceType.CAMERA, ResourceType.STREAM, ResourceType.RECORDING):
            return AuthorizationDecision(
                allowed=False,
                reason=f"Access denied: user is not assigned to resource '{resource_id}' (BOLA prevention)",
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
            )

        # For non-camera generic resources (e.g. system:status, event:view), check if role alone is sufficient
        if resource_id == "*" or resource_type in (ResourceType.SYSTEM, ResourceType.EVENT, ResourceType.AUDIT):
            return AuthorizationDecision(
                allowed=True,
                reason=f"Granted by role '{user.role.value}' baseline",
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
            )

        # Deny by default
        return AuthorizationDecision(
            allowed=False,
            reason="Deny-by-default: no explicit resource scope matched",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
        )

    @staticmethod
    def _check_permission_pattern(granted: set[str], requested: str) -> bool:
        """Check exact, wildcard (*), or domain wildcard (camera:*) match."""
        if "*" in granted or requested in granted:
            return True
        domain = requested.split(":")[0] + ":*"
        return domain in granted
