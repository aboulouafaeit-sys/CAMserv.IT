"""
tests.test_enterprise_security
==============================

Unit and integration tests for CAMserv Enterprise security:
multi-tenancy isolation boundaries, RBAC role-to-permission matrix,
dual-control quorum enforcement, and cryptographic audit hash chaining.
"""

import pytest

from camserv.security.audit_trail import AuditAction, SecurityAuditLogger
from camserv.security.rbac import (
    Permission,
    PermissionDeniedError,
    QuorumAuthorizationError,
    RBACPolicyEngine,
    Role,
)
from camserv.security.tenancy import (
    MultiTenantEnforcer,
    TenantAccessDeniedError,
    TenantContext,
)


def test_multi_tenant_isolation_and_cross_tenant_denial():
    """Verify that cross-tenant access attempts are blocked server-side."""
    enforcer = MultiTenantEnforcer()
    enforcer.register_tenant("tenant-alpha", "Alpha Airport Corp", allowed_sites=["site-1", "site-2"])
    enforcer.register_tenant("tenant-beta", "Beta Logistics Ltd", allowed_sites=["site-3"])

    caller_alpha = TenantContext(
        tenant_id="tenant-alpha",
        user_id="alice",
        role="site_operator",
        assigned_sites=["site-1"],
    )

    # Accessing own tenant resource succeeds
    enforcer.enforce_tenant_boundary(caller_alpha, resource_tenant_id="tenant-alpha")

    # Accessing another tenant's resource MUST raise TenantAccessDeniedError!
    with pytest.raises(TenantAccessDeniedError, match="cannot access camera belonging to tenant 'tenant-beta'"):
        enforcer.enforce_tenant_boundary(caller_alpha, resource_tenant_id="tenant-beta", resource_description="camera")

    # Super admin bypasses tenant boundary
    super_admin = TenantContext(
        tenant_id="tenant-system",
        user_id="root",
        role="super_admin",
        is_system_admin=True,
    )
    enforcer.enforce_tenant_boundary(super_admin, resource_tenant_id="tenant-beta")


def test_site_boundary_within_tenant():
    """Verify that a user cannot access unassigned sites within their tenant."""
    enforcer = MultiTenantEnforcer()
    caller = TenantContext(
        tenant_id="tenant-alpha",
        user_id="bob",
        role="site_operator",
        assigned_sites=["site-1"],
    )

    # Site 1 allowed
    enforcer.enforce_site_boundary(caller, resource_site_id="site-1")

    # Site 2 denied
    with pytest.raises(TenantAccessDeniedError, match="not authorized to access site 'site-2'"):
        enforcer.enforce_site_boundary(caller, resource_site_id="site-2")


def test_rbac_permissions_and_role_enforcement():
    """Verify RBAC capability matrix and permission denials."""
    # Operator can view masked stream
    assert RBACPolicyEngine.has_permission(Role.SECURITY_OPERATOR, Permission.STREAM_VIEW_MASKED) is True
    assert RBACPolicyEngine.has_permission(Role.SECURITY_OPERATOR, Permission.EVENT_REVIEW) is True

    # Operator cannot configure cameras or manage tenants
    assert RBACPolicyEngine.has_permission(Role.SECURITY_OPERATOR, Permission.CAMERA_CONFIGURE) is False
    assert RBACPolicyEngine.has_permission(Role.SECURITY_OPERATOR, Permission.TENANT_MANAGE) is False

    with pytest.raises(PermissionDeniedError, match="lacks required capability 'tenant:manage'"):
        RBACPolicyEngine.enforce_permission(Role.SECURITY_OPERATOR, Permission.TENANT_MANAGE)

    # Super admin holds all capabilities
    RBACPolicyEngine.enforce_permission(Role.SUPER_ADMIN, Permission.CAMERA_CONFIGURE)
    RBACPolicyEngine.enforce_permission(Role.SUPER_ADMIN, Permission.DEVICE_MANAGE)


def test_dual_control_quorum_enforcement():
    """Verify dual-control authorization for privacy-sensitive raw evidence access."""
    # Single operator cannot authorize raw export
    with pytest.raises(QuorumAuthorizationError, match="requires co-signing by both Forensic Investigator"):
        RBACPolicyEngine.enforce_quorum_authorization(
            primary_role=Role.SECURITY_OPERATOR,
            co_signer_role=Role.SITE_ADMIN,
            permission=Permission.EVIDENCE_EXPORT_RAW,
        )

    # Valid quorum: Forensic Investigator + Tenant Admin
    RBACPolicyEngine.enforce_quorum_authorization(
        primary_role=Role.FORENSIC_INVESTIGATOR,
        co_signer_role=Role.TENANT_ADMIN,
        permission=Permission.EVIDENCE_EXPORT_RAW,
    )

    # Valid quorum: Super Admin + Forensic Investigator
    RBACPolicyEngine.enforce_quorum_authorization(
        primary_role=Role.SUPER_ADMIN,
        co_signer_role=Role.FORENSIC_INVESTIGATOR,
        permission=Permission.STREAM_VIEW_UNMASKED,
    )


def test_audit_trail_sanitization_and_hash_chaining():
    """Verify credential stripping, SHA-256 Merkle chain formation, and tamper detection."""
    audit_logger = SecurityAuditLogger(in_memory=True)

    # 1. Test credential sanitization
    entry1 = audit_logger.record_event(
        tenant_id="tenant-alpha",
        user_id="alice",
        action=AuditAction.USER_LOGIN,
        resource_id="auth-session-001",
        status="SUCCESS",
        details={"username": "alice", "password": "super_secret_password_123", "client_ip": "10.0.0.1"},
    )
    assert entry1.details["username"] == "alice"
    assert entry1.details["password"] == "[REDACTED_BY_SECURITY_POLICY]"
    assert entry1.previous_hash == SecurityAuditLogger.GENESIS_HASH

    # 2. Record second chained event
    entry2 = audit_logger.record_event(
        tenant_id="tenant-alpha",
        user_id="bob",
        action=AuditAction.EVIDENCE_ACCESS,
        resource_id="vault-chunk-99",
        status="SUCCESS",
        details={"reason": "Audit inquiry"},
    )
    assert entry2.previous_hash == entry1.entry_hash

    # 3. Verify intact chain
    assert SecurityAuditLogger.verify_chain_integrity(audit_logger.entries) is True

    # 4. Tamper with entry status and verify verification failure
    tampered_entries = [e for e in audit_logger.entries]
    # Modify details of entry 1 without recalculating hash
    tampered_entries[0].details["tampered_key"] = "hacked"
    assert SecurityAuditLogger.verify_chain_integrity(tampered_entries) is False
