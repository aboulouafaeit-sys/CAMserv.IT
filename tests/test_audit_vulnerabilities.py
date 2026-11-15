"""
tests/test_audit_vulnerabilities.py
===================================

Independent Security Audit Vulnerability Reproduction & Regression Tests.
Safely reproduces and validates remediations for:
- SEC-P3-01: Zip Slip / Path Traversal in OTA updater
- SEC-P3-02: Dual-Control Quorum Bypass in snapshot export
- SEC-P3-03: Path Traversal in storage chunk & incident capture
- SEC-P3-04: Unauthenticated Rate Limit DoS via sender_id spoofing
- SEC-P3-05: Missing Site/Role Authorization in device suspend/revoke
- SEC-P3-06: Credential leakage in nested audit log structures
- SEC-P3-07: Dual-control quorum single-user bypass
- SEC-P3-08: Inactive tenant enforcement bypass
"""

import hashlib
import json
import time
import zipfile
from pathlib import Path

import numpy as np
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from camserv.central.comm import (
    DistributedGateway,
    MessageVerificationError,
    RateLimitExceededError,
    SecureMessageEnvelope,
)
from camserv.central.models import DeviceRole, DeviceStatus, SiteRecord
from camserv.central.registry import DeviceRegistry, SiteAccessDeniedError
from camserv.deploy.updater import (
    DeploymentChannel,
    PackageIntegrityError,
    SignedUpdateManager,
    UpdatePackageManifest,
    UpdateSignatureError,
)
from camserv.inference.privacy_pipeline import (
    CentralizedPrivacyEnforcer,
    FailClosedPrivacyPipeline,
)
from camserv.security.audit_trail import AuditAction, SecurityAuditLogger
from camserv.security.rbac import (
    Permission,
    QuorumAuthorizationError,
    RBACPolicyEngine,
    Role,
)
from camserv.security.tenancy import (
    MultiTenantEnforcer,
    TenantAccessDeniedError,
    TenantContext,
)
from camserv.storage.tiered_storage import (
    ExportAuthorizationError,
    TieredStorageManager,
)


# ---------------------------------------------------------------------------
# Test SEC-P3-01: Zip Slip / Path Traversal in OTA Updater
# ---------------------------------------------------------------------------

def test_sec_p3_01_zip_slip_rejection(tmp_path: Path) -> None:
    """Verify that update archives containing path traversal payloads are rejected."""
    dest_dir = tmp_path / "installed_app"
    backup_dir = tmp_path / "backups"
    dest_dir.mkdir()
    (dest_dir / "app.py").write_text("print('original')")

    # Generate release key
    release_priv = ed25519.Ed25519PrivateKey.generate()
    release_pub_hex = release_priv.public_key().public_bytes_raw().hex()

    updater = SignedUpdateManager(trusted_release_keys=[release_pub_hex])

    # Craft malicious zip containing Zip Slip entry
    malicious_pkg = tmp_path / "exploit.camserv-upd"
    with zipfile.ZipFile(str(malicious_pkg), "w") as zf:
        manifest_dict = {
            "package_id": "PKG-MALICIOUS-01",
            "target_version": "1.1.0",
            "minimum_supported_version": "1.0.0",
            "channel": "stable",
            "files": [
                {"path": "../../escaped.txt", "sha256": hashlib.sha256(b"pwned").hexdigest(), "size": 5}
            ],
            "created_at": time.time(),
        }
        # Compute signature
        files_canonical = json.dumps(manifest_dict["files"], sort_keys=True)
        files_hash = hashlib.sha256(files_canonical.encode("utf-8")).hexdigest()
        canon = f"UPDATE_V1|{manifest_dict['package_id']}|{manifest_dict['target_version']}|{manifest_dict['minimum_supported_version']}|stable|{int(manifest_dict['created_at'])}|{files_hash}"
        sig = release_priv.sign(canon.encode("utf-8")).hex()
        manifest_dict["signature_hex"] = sig

        zf.writestr("manifest.json", json.dumps(manifest_dict))
        zf.writestr("payload/../../escaped.txt", b"pwned")

    # Verification or application must reject path traversal
    with pytest.raises((ValueError, PackageIntegrityError)):
        updater.verify_and_stage_package(malicious_pkg, current_version="1.0.0")

    result = updater.apply_update_with_atomic_rollback(malicious_pkg, dest_dir, backup_dir)
    assert result is False
    assert not (tmp_path / "escaped.txt").exists()


# ---------------------------------------------------------------------------
# Test SEC-P3-02: Dual-Control Quorum in Centralized Privacy Snapshot Export
# ---------------------------------------------------------------------------

def test_sec_p3_02_snapshot_export_requires_quorum() -> None:
    """Verify that single user role cannot obtain unmasked raw frames from snapshot export."""
    enforcer = CentralizedPrivacyEnforcer(is_production_profile=True, require_dual_control=True)
    frame = np.ones((100, 100, 3), dtype=np.uint8) * 128

    # A single role without co-signer must NOT receive raw unmasked frame
    exported_frame, manifest, is_raw = enforcer.process_snapshot_export(
        raw_frame=frame,
        camera_id="cam-01",
        frame_id=1,
        user_role="FORENSIC_AUTHORITY",
        co_signer_role=None,  # No co-signer provided
    )
    assert is_raw is False
    assert manifest.fail_closed_active is False

    # With proper dual-control quorum co-signing, raw export is authorized
    exported_raw, manifest_raw, is_raw_approved = enforcer.process_snapshot_export(
        raw_frame=frame,
        camera_id="cam-01",
        frame_id=2,
        user_role="FORENSIC_INVESTIGATOR",
        co_signer_role="TENANT_ADMIN",
    )
    assert is_raw_approved is True
    assert np.array_equal(exported_raw, frame)


# ---------------------------------------------------------------------------
# Test SEC-P3-03: Path Traversal in Storage Chunks
# ---------------------------------------------------------------------------

def test_sec_p3_03_storage_chunk_path_traversal(tmp_path: Path) -> None:
    """Verify that path traversal in camera_id or chunk_id is blocked."""
    mgr = TieredStorageManager(base_dir=tmp_path / "storage")

    # Malicious camera_id with directory traversal
    with pytest.raises(ValueError, match="Path traversal"):
        mgr.store_chunk(chunk_id="chunk1", camera_id="../../evil", data=b"video")

    with pytest.raises(ValueError, match="Path traversal"):
        mgr.store_chunk(chunk_id="../outside", camera_id="cam1", data=b"video")


# ---------------------------------------------------------------------------
# Test SEC-P3-04: Unauthenticated Rate Limit DoS via Sender ID Spoofing
# ---------------------------------------------------------------------------

def test_sec_p3_04_unauthenticated_rate_limit_spoofing() -> None:
    """Verify that forged messages with invalid signatures do not exhaust victim's rate limit."""
    gw = DistributedGateway(node_id="central-01", rate_limit_per_minute=2)
    victim_id = "device-victim"
    victim_priv = ed25519.Ed25519PrivateKey.generate()
    victim_pub_hex = victim_priv.public_key().public_bytes_raw().hex()

    # Attacker sends forged envelopes claiming sender_id = victim_id with invalid signature
    for i in range(5):
        forged_env = SecureMessageEnvelope(
            message_id=f"forged-{i}",
            sender_id=victim_id,
            recipient_id="central-01",
            payload_type="telemetry",
            payload_data={"status": "fake"},
            signature_hex="deadbeef" * 8,  # Invalid signature
        )
        with pytest.raises(MessageVerificationError):
            gw.validate_incoming_envelope(forged_env, victim_pub_hex)

    # Now legitimate victim sends a valid envelope — MUST NOT be blocked by rate limiting!
    valid_env = SecureMessageEnvelope(
        message_id="valid-01",
        sender_id=victim_id,
        recipient_id="central-01",
        payload_type="telemetry",
        payload_data={"status": "ok"},
    )
    valid_env.sign(victim_priv)

    # Must succeed (not raise RateLimitExceededError)
    assert gw.validate_incoming_envelope(valid_env, victim_pub_hex) is True


# ---------------------------------------------------------------------------
# Test SEC-P3-05: Missing Site/Role Authorization in Device Suspend/Revoke
# ---------------------------------------------------------------------------

def test_sec_p3_05_device_lifecycle_authorization() -> None:
    """Verify that unauthorized operators cannot suspend or revoke devices across sites."""
    reg = DeviceRegistry()
    site_a = reg.register_site("site-a", "Facility A", "HQ", assigned_operators=["op-a"])
    site_b = reg.register_site("site-b", "Facility B", "Branch", assigned_operators=["op-b"])

    # Enroll device in site-b
    reg.create_enrollment_token("token-b", "site-b")
    priv_b = ed25519.Ed25519PrivateKey.generate()
    reg.enroll_device(
        device_id="dev-b",
        device_name="Cam Branch",
        device_role=DeviceRole.EDGE_NODE,
        site_id="site-b",
        public_key_hex=priv_b.public_key().public_bytes_raw().hex(),
        hardware_profile="Profile B",
        software_version="1.0.0",
        enrollment_token="token-b",
        authorized_by="admin",
    )

    # Operator from site-a attempts to suspend dev-b
    with pytest.raises(SiteAccessDeniedError):
        reg.suspend_device(
            device_id="dev-b",
            reason="Malicious suspend",
            operator_id="op-a",
            user_role="SECURITY_OPERATOR",
            user_assigned_sites=["site-a"],
        )

    # Super admin or authorized site-b operator can suspend
    assert reg.suspend_device(
        device_id="dev-b",
        reason="Scheduled maintenance",
        operator_id="op-b",
        user_role="SITE_ADMIN",
        user_assigned_sites=["site-b"],
    ) is True


# ---------------------------------------------------------------------------
# Test SEC-P3-06: Credential Leakage in Nested Audit Structures
# ---------------------------------------------------------------------------

def test_sec_p3_06_audit_logger_nested_redaction() -> None:
    """Verify that credentials inside nested lists and iterables are sanitized."""
    logger = SecurityAuditLogger()
    leaky_details = {
        "user_records": [
            {"username": "alice", "token": "secret-jwt-token"},
            {"username": "bob", "password": "supersecretpassword"},
        ],
        "api_keys": ["raw_api_key_1", "raw_api_key_2"],
    }

    sanitized = logger.sanitize_details(leaky_details)
    assert sanitized["user_records"][0]["token"] == "[REDACTED_BY_SECURITY_POLICY]"
    assert sanitized["user_records"][1]["password"] == "[REDACTED_BY_SECURITY_POLICY]"


# ---------------------------------------------------------------------------
# Test SEC-P3-07: Dual-Control Quorum Single-User Bypass Prevention
# ---------------------------------------------------------------------------

def test_sec_p3_07_quorum_distinct_user_identities() -> None:
    """Verify that a single user holding multiple roles cannot co-sign for themselves."""
    # Same user attempting to satisfy quorum with two roles
    with pytest.raises(QuorumAuthorizationError, match="must be distinct identities"):
        RBACPolicyEngine.enforce_quorum_authorization(
            primary_role=Role.FORENSIC_INVESTIGATOR,
            co_signer_role=Role.TENANT_ADMIN,
            permission=Permission.EVIDENCE_EXPORT_RAW,
            primary_user_id="user-123",
            co_signer_user_id="user-123",  # Same user!
        )

    # Two distinct users
    RBACPolicyEngine.enforce_quorum_authorization(
        primary_role=Role.FORENSIC_INVESTIGATOR,
        co_signer_role=Role.TENANT_ADMIN,
        permission=Permission.EVIDENCE_EXPORT_RAW,
        primary_user_id="user-investigator",
        co_signer_user_id="user-admin",
    )


# ---------------------------------------------------------------------------
# Test SEC-P3-08: Inactive Tenant Boundary Enforcement
# ---------------------------------------------------------------------------

def test_sec_p3_08_inactive_tenant_rejection() -> None:
    """Verify that deactivated tenants are blocked from accessing resources."""
    enforcer = MultiTenantEnforcer()
    t = enforcer.register_tenant("tenant-suspended", "Suspended Corp")
    t.is_active = False

    ctx = TenantContext(tenant_id="tenant-suspended", user_id="user-1", role="SECURITY_OPERATOR")

    with pytest.raises(TenantAccessDeniedError, match="inactive or suspended"):
        enforcer.enforce_tenant_boundary(ctx, resource_tenant_id="tenant-suspended")
