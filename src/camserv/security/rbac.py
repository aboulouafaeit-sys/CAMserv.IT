"""
camserv.security.rbac
=====================

Role-Based Access Control (RBAC) permission matrix, role hierarchies,
and dual-control forensic quorum enforcement for CAMserv Enterprise.
"""

from __future__ import annotations

import enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class PermissionDeniedError(PermissionError):
    """Raised when an identity lacks the required permission for an action."""


class QuorumAuthorizationError(PermissionError):
    """Raised when an operation requiring dual-control cryptographic quorum lacks valid co-signers."""


class Role(str, enum.Enum):
    """Hierarchical enterprise security roles."""

    SUPER_ADMIN = "super_admin"                  # Global platform master authority
    TENANT_ADMIN = "tenant_admin"                # Administrative lead for tenant organization
    SITE_ADMIN = "site_admin"                    # Administrator for physical facility sites
    SECURITY_OPERATOR = "security_operator"      # Guard / operator reviewing masked streams and alerts
    FORENSIC_INVESTIGATOR = "forensic_investigator" # Legal investigator examining evidence and derivatives
    AUDITOR = "auditor"                          # Read-only compliance and audit trail inspector


class Permission(str, enum.Enum):
    """Granular platform authorization capabilities."""

    STREAM_VIEW_MASKED = "stream:view_masked"
    STREAM_VIEW_UNMASKED = "stream:view_unmasked"  # RESTRICTED: Requires dual-control quorum
    EVENT_REVIEW = "event:review"
    EVENT_CONFIRM_ALERT = "event:confirm_alert"
    EVIDENCE_VIEW_DERIVATIVE = "evidence:view_derivative"
    EVIDENCE_EXPORT_DERIVATIVE = "evidence:export_derivative"
    EVIDENCE_EXPORT_RAW = "evidence:export_raw"    # RESTRICTED: Requires dual-control quorum
    CAMERA_CONFIGURE = "camera:configure"
    DEVICE_ENROLL = "device:enroll"
    DEVICE_MANAGE = "device:manage"
    AUDIT_READ = "audit:read"
    TENANT_MANAGE = "tenant:manage"


class RBACPolicyEngine:
    """Enforces role-to-permission mapping and dual-control quorum policies."""

    ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
        Role.SUPER_ADMIN: {
            Permission.STREAM_VIEW_MASKED,
            Permission.EVENT_REVIEW,
            Permission.EVENT_CONFIRM_ALERT,
            Permission.EVIDENCE_VIEW_DERIVATIVE,
            Permission.EVIDENCE_EXPORT_DERIVATIVE,
            Permission.CAMERA_CONFIGURE,
            Permission.DEVICE_ENROLL,
            Permission.DEVICE_MANAGE,
            Permission.AUDIT_READ,
            Permission.TENANT_MANAGE,
        },
        Role.TENANT_ADMIN: {
            Permission.STREAM_VIEW_MASKED,
            Permission.EVENT_REVIEW,
            Permission.EVENT_CONFIRM_ALERT,
            Permission.EVIDENCE_VIEW_DERIVATIVE,
            Permission.EVIDENCE_EXPORT_DERIVATIVE,
            Permission.CAMERA_CONFIGURE,
            Permission.DEVICE_ENROLL,
            Permission.DEVICE_MANAGE,
            Permission.AUDIT_READ,
        },
        Role.SITE_ADMIN: {
            Permission.STREAM_VIEW_MASKED,
            Permission.EVENT_REVIEW,
            Permission.EVENT_CONFIRM_ALERT,
            Permission.EVIDENCE_VIEW_DERIVATIVE,
            Permission.EVIDENCE_EXPORT_DERIVATIVE,
            Permission.CAMERA_CONFIGURE,
            Permission.DEVICE_MANAGE,
        },
        Role.SECURITY_OPERATOR: {
            Permission.STREAM_VIEW_MASKED,
            Permission.EVENT_REVIEW,
            Permission.EVENT_CONFIRM_ALERT,
            Permission.EVIDENCE_VIEW_DERIVATIVE,
        },
        Role.FORENSIC_INVESTIGATOR: {
            Permission.STREAM_VIEW_MASKED,
            Permission.EVENT_REVIEW,
            Permission.EVIDENCE_VIEW_DERIVATIVE,
            Permission.EVIDENCE_EXPORT_DERIVATIVE,
            Permission.AUDIT_READ,
        },
        Role.AUDITOR: {
            Permission.AUDIT_READ,
            Permission.EVIDENCE_VIEW_DERIVATIVE,
        },
    }

    # Permissions strictly requiring dual-control quorum (cannot be executed by single user)
    QUORUM_REQUIRED_PERMISSIONS: set[Permission] = {
        Permission.STREAM_VIEW_UNMASKED,
        Permission.EVIDENCE_EXPORT_RAW,
    }

    @classmethod
    def has_permission(cls, role: Role | str, permission: Permission) -> bool:
        """Check if role holds the specified permission."""
        try:
            r = Role(role) if isinstance(role, str) else role
        except ValueError:
            return False
        return permission in cls.ROLE_PERMISSIONS.get(r, set())

    @classmethod
    def enforce_permission(cls, role: Role | str, permission: Permission) -> None:
        """Enforce single-actor permission check."""
        if not cls.has_permission(role, permission):
            logger.warning("rbac.permission_denied", role=str(role), required_permission=permission.value)
            raise PermissionDeniedError(
                f"PERMISSION DENIED: Role '{role}' lacks required capability '{permission.value}'."
            )

    @classmethod
    def enforce_quorum_authorization(
        cls,
        primary_role: Role | str,
        co_signer_role: Role | str,
        permission: Permission,
        primary_user_id: str | None = None,
        co_signer_user_id: str | None = None,
    ) -> None:
        """
        Enforce dual-control authorization for privacy-sensitive actions
        (unmasked raw evidence access / export).
        Mandates that primary actor and co-signer are distinct roles and distinct identities.
        """
        if permission not in cls.QUORUM_REQUIRED_PERMISSIONS:
            return

        if primary_user_id and co_signer_user_id:
            if primary_user_id.strip() == co_signer_user_id.strip():
                logger.critical(
                    "rbac.quorum_self_approval_blocked",
                    user_id=primary_user_id,
                    permission=permission.value,
                )
                raise QuorumAuthorizationError(
                    f"QUORUM AUTHORIZATION REJECTED: Primary actor and co-signer must be distinct identities "
                    f"(both claimed by user '{primary_user_id}')."
                )

        try:
            r1 = Role(primary_role) if isinstance(primary_role, str) else primary_role
            r2 = Role(co_signer_role) if isinstance(co_signer_role, str) else co_signer_role
        except ValueError:
            raise QuorumAuthorizationError("Invalid role specification in quorum request.")

        # Require that one is a FORENSIC_INVESTIGATOR and the other is at least TENANT_ADMIN or SUPER_ADMIN
        authorized_pairs = [
            (Role.FORENSIC_INVESTIGATOR, Role.TENANT_ADMIN),
            (Role.FORENSIC_INVESTIGATOR, Role.SUPER_ADMIN),
            (Role.TENANT_ADMIN, Role.FORENSIC_INVESTIGATOR),
            (Role.SUPER_ADMIN, Role.FORENSIC_INVESTIGATOR),
        ]

        if (r1, r2) not in authorized_pairs:
            logger.critical(
                "rbac.quorum_rejected",
                primary=r1.value,
                co_signer=r2.value,
                permission=permission.value,
            )
            raise QuorumAuthorizationError(
                f"QUORUM AUTHORIZATION REJECTED: Unmasked evidence export requires co-signing by both "
                "Forensic Investigator and Tenant/Super Administrator. "
                f"Provided roles: '{r1.value}' and '{r2.value}'."
            )

        logger.info("rbac.quorum_granted", primary=r1.value, co_signer=r2.value, permission=permission.value)
