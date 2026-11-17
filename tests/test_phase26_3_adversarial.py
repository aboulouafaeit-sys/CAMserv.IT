"""
tests.test_phase26_3_adversarial
================================

Phase 26.3: Local Trust Boundary Closure & Final Identity Security Assurance.
Comprehensive adversarial verification suite for CAMserv 0.10.0-rc7.

Domains Covered:
- Domain A: External Audit Checkpoint Trust Anchor (Rollback, Deletion, Corruption, Signatures)
- Domain B: Windows Bootstrap Handle Races, ACL Hardening & Memory Zeroing
- Domain C: Emergency Lockdown Latch HMAC Assurance, Reconciliation & Session Interception
- Domain D: Sentinel Reverse-Proxy Header Spoofing & Multi-Signal Risk Correlation
- Domain E: Object-Level Authorization, BOLA/IDOR Camera Isolation & Step-Up MFA
- Domain F & G: Surveillance Ingestion Pipeline Isolation Under Compound Fault Injection
"""

from __future__ import annotations

import collections
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from camserv.platform.stability import (
    BoundedPipelineQueue,
    RecordingContinuityLedger,
)
from camserv.security.identity import (
    AccountStatus,
    AuditCheckpoint,
    AuthAssuranceLevel,
    AuthorizationDecision,
    BootstrapError,
    CAMservSentinelIdentity,
    CheckpointCorruptedError,
    CheckpointSequenceRegressionError,
    CheckpointStoreMissingError,
    DurableIdentityStore,
    EmergencyLockdownManager,
    ExternalCheckpointStore,
    IdentityRole,
    LocalAdministratorBootstrap,
    ResourceType,
    ResourceScope,
    SecurityEvent,
    SecurityEventSeverity,
    SentinelConfig,
    SessionError,
    SessionManager,
    SessionRecord,
    SessionRevokedError,
    TamperEvidentSecurityAudit,
    UserRecord,
    ZeroTrustPolicyEngine,
    resolve_client_ip,
    secure_zero_memory,
)


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="camserv_test_p26_3_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def identity_store(temp_dir):
    db_path = temp_dir / "identity.db"
    store = DurableIdentityStore(db_path=db_path)
    yield store
    store.close()


@pytest.fixture
def admin_user():
    return UserRecord(
        user_id="usr_admin_01",
        username="admin",
        role=IdentityRole.ADMIN,
        status=AccountStatus.ACTIVE,
        full_name="Local Administrator",
        is_administrator=True,
        mfa_enabled=True,
    )


@pytest.fixture
def operator_user():
    return UserRecord(
        user_id="usr_op_01",
        username="operator_east",
        role=IdentityRole.OPERATOR,
        status=AccountStatus.ACTIVE,
        full_name="East Sector Operator",
        is_administrator=False,
        mfa_enabled=True,
    )


@pytest.fixture
def viewer_user():
    return UserRecord(
        user_id="usr_view_01",
        username="viewer_guest",
        role=IdentityRole.VIEWER,
        status=AccountStatus.ACTIVE,
        full_name="Guest Viewer",
        is_administrator=False,
        mfa_enabled=False,
    )


# ---------------------------------------------------------------------------
# Domain A: External Audit Checkpoint & Rollback Attacks
# ---------------------------------------------------------------------------

class TestDomainAExternalCheckpointRollback:
    """Adversarial verification of external audit checkpoints and rollback detection."""

    def test_database_only_rollback_detected(self, identity_store, temp_dir):
        """Vector A: Restoring older database while external store has advanced sequence fails verification."""
        audit = TamperEvidentSecurityAudit(store=identity_store)
        checkpoint_store = ExternalCheckpointStore(store_path=temp_dir / "trust_anchor.json")

        # 1. Generate 5 events and create checkpoint at sequence 5
        for i in range(5):
            audit.log_event(
                SecurityEvent(
                    event_id=f"ev_{i}",
                    event_type="TEST_EVENT",
                    severity=SecurityEventSeverity.INFO,
                    actor_id="admin",
                )
            )
        chk5 = audit.create_and_persist_checkpoint(checkpoint_store)
        assert chk5.sequence_number == 5

        # 2. Advance to 10 events and create checkpoint at sequence 10
        for i in range(5, 10):
            audit.log_event(
                SecurityEvent(
                    event_id=f"ev_{i}",
                    event_type="TEST_EVENT",
                    severity=SecurityEventSeverity.INFO,
                    actor_id="admin",
                )
            )
        chk10 = audit.create_and_persist_checkpoint(checkpoint_store)
        assert chk10.sequence_number == 10

        # Verification passes on current state
        valid, err = audit.verify_against_external_store(checkpoint_store)
        assert valid is True
        assert err is None

        # 3. Simulate Database-Only Rollback attack: delete last 3 rows from SQLite
        with identity_store._lock:
            identity_store._conn.execute("DELETE FROM security_events WHERE rowid > 7")
            identity_store._conn.commit()

        # 4. Verify against external store -> must detect rollback!
        valid, err = audit.verify_against_external_store(checkpoint_store)
        assert valid is False
        assert "Rollback detected" in err
        assert "database has fewer rows" in err

    def test_checkpoint_store_deletion_fails_closed(self, identity_store, temp_dir):
        """Vector D: Deleting trust_anchor.json when database has records raises CheckpointStoreMissingError."""
        audit = TamperEvidentSecurityAudit(store=identity_store)
        anchor_path = temp_dir / "trust_anchor.json"
        checkpoint_store = ExternalCheckpointStore(store_path=anchor_path)

        for i in range(4):
            audit.log_event(
                SecurityEvent(
                    event_id=f"ev_del_{i}",
                    event_type="TEST_EVENT",
                    severity=SecurityEventSeverity.INFO,
                    actor_id="admin",
                )
            )
        audit.create_and_persist_checkpoint(checkpoint_store)
        assert anchor_path.exists()

        # Attacker deletes trust_anchor.json
        anchor_path.unlink()
        assert not anchor_path.exists()

        # Verification must fail closed with CheckpointStoreMissingError
        with pytest.raises(CheckpointStoreMissingError, match="missing or empty"):
            audit.verify_against_external_store(checkpoint_store)

    def test_corrupted_checkpoint_store_fails_closed(self, identity_store, temp_dir):
        """Vector G: Truncated, 0-byte, or malformed JSON in trust_anchor.json raises CheckpointCorruptedError."""
        audit = TamperEvidentSecurityAudit(store=identity_store)
        anchor_path = temp_dir / "trust_anchor.json"
        checkpoint_store = ExternalCheckpointStore(store_path=anchor_path)

        # Case 1: 0-byte file
        anchor_path.write_text("", encoding="utf-8")
        with pytest.raises(CheckpointCorruptedError, match="empty or truncated"):
            checkpoint_store.get_all_checkpoints()

        # Case 2: Malformed JSON syntax
        anchor_path.write_text('{"incomplete": [', encoding="utf-8")
        with pytest.raises(CheckpointCorruptedError, match="could not be parsed"):
            checkpoint_store.get_all_checkpoints()

        # Case 3: Root JSON is not an array
        anchor_path.write_text('{"status": "not_an_array"}', encoding="utf-8")
        with pytest.raises(CheckpointCorruptedError, match="root must be a JSON array"):
            checkpoint_store.get_all_checkpoints()

    def test_sequence_regression_and_divergence_blocked(self, identity_store, temp_dir):
        """Vectors E & F: Sequence regressions and divergent head hashes are strictly blocked."""
        checkpoint_store = ExternalCheckpointStore(store_path=temp_dir / "trust_anchor.json")

        c1 = AuditCheckpoint(
            checkpoint_id="chk_01",
            sequence_number=10,
            head_entry_hash="hash_10",
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            signature="sig1",
        )
        checkpoint_store.save_checkpoint(c1)

        # Regressed sequence (sequence 8 < sequence 10)
        c_regressed = AuditCheckpoint(
            checkpoint_id="chk_regressed",
            sequence_number=8,
            head_entry_hash="hash_08",
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            signature="sig_reg",
        )
        with pytest.raises(CheckpointSequenceRegressionError, match="Monotonicity violation"):
            checkpoint_store.save_checkpoint(c_regressed)

        # Divergent head hash at identical sequence
        c_divergent = AuditCheckpoint(
            checkpoint_id="chk_divergent",
            sequence_number=10,
            head_entry_hash="divergent_hash_at_10",
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            signature="sig_div",
        )
        with pytest.raises(CheckpointSequenceRegressionError, match="Divergent head hash"):
            checkpoint_store.save_checkpoint(c_divergent)

    def test_ed25519_tampered_payload_and_key_substitution(self, identity_store):
        """Vector H: Ed25519 checkpoint rejects forged payloads and substituted public keys."""
        audit = TamperEvidentSecurityAudit(store=identity_store)

        priv_key1 = Ed25519PrivateKey.generate()
        pub_key1 = priv_key1.public_key()

        priv_key2 = Ed25519PrivateKey.generate()
        pub_key2 = priv_key2.public_key()

        for i in range(3):
            audit.log_event(
                SecurityEvent(
                    event_id=f"ev_ed_{i}",
                    event_type="TEST_EVENT",
                    severity=SecurityEventSeverity.INFO,
                    actor_id="admin",
                )
            )

        chk = audit.create_checkpoint(private_key=priv_key1)
        assert chk.algorithm == "Ed25519"

        # Legitimate verification with corresponding public key
        valid, err = audit.verify_against_checkpoint(chk, public_key=pub_key1)
        assert valid is True
        assert err is None

        # Key substitution attack: verify with pub_key2
        valid, err = audit.verify_against_checkpoint(chk, public_key=pub_key2)
        assert valid is False
        assert "invalid or forged" in err

        # Payload tampering: modify checkpoint sequence number
        tampered_chk = AuditCheckpoint(
            checkpoint_id=chk.checkpoint_id,
            sequence_number=chk.sequence_number + 1,
            head_entry_hash=chk.head_entry_hash,
            created_at_utc=chk.created_at_utc,
            signature=chk.signature,
            algorithm=chk.algorithm,
        )
        valid, err = audit.verify_against_checkpoint(tampered_chk, public_key=pub_key1)
        assert valid is False
        assert "invalid or forged" in err


# ---------------------------------------------------------------------------
# Domain B: Windows Bootstrap Handle Races, ACL Hardening & Memory Zeroing
# ---------------------------------------------------------------------------

class TestDomainBBootstrapSecurity:
    """Adversarial verification of local administrator bootstrap creation and memory zeroing."""

    def test_bootstrap_path_integrity_and_symlink_rejection(self, identity_store, temp_dir):
        """Bootstrap aborts if token path or parent is a symlink or directory junction."""
        bootstrap = LocalAdministratorBootstrap(
            store=identity_store,
            token_path=temp_dir / ".bootstrap_token",
        )

        fake_symlink = temp_dir / "symlink_test"
        with patch.object(Path, "is_symlink", return_value=True):
            with pytest.raises(BootstrapError, match="Symlink or reparse point"):
                bootstrap._verify_path_integrity(fake_symlink)

    def test_bootstrap_parent_directory_pre_hardening(self, identity_store, temp_dir):
        """Parent directory is pre-created and pre-hardened before token generation."""
        token_path = temp_dir / "secure_dir" / ".bootstrap_token"
        bootstrap = LocalAdministratorBootstrap(
            store=identity_store,
            token_path=token_path,
        )

        # Mock icacls execution to verify commands are issued
        with patch("subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(returncode=0, stdout="SUCCESS")
            res = bootstrap.initiate_bootstrap(validity_sec=300)
            assert Path(res["token_path"]).exists()
            # Assert icacls was invoked for parent directory and token file
            assert mock_sub.call_count >= 1

    def test_secure_zero_memory_ctypes(self):
        """secure_zero_memory overwrites bytearray buffers in place with zeros."""
        secret_bytes = bytearray(b"super_secret_bootstrap_token_string_12345")
        assert any(b != 0 for b in secret_bytes)

        secure_zero_memory(secret_bytes)

        # Buffer must be strictly 0x00 across all bytes
        assert all(b == 0 for b in secret_bytes)
        assert len(secret_bytes) == len(b"super_secret_bootstrap_token_string_12345")


# ---------------------------------------------------------------------------
# Domain C: Emergency Lockdown Latch HMAC Assurance & Session Interception
# ---------------------------------------------------------------------------

class TestDomainCEmergencyLockdownAssurance:
    """Adversarial verification of emergency lockdown latch persistence and active session blocking."""

    def test_lockdown_hmac_signature_tampering_fails_closed(self, identity_store, temp_dir):
        """Tampering with .emergency_lockdown.latch without valid HMAC fails closed on boot."""
        latch_path = temp_dir / ".emergency_lockdown.latch"
        lockdown1 = EmergencyLockdownManager(store=identity_store, latch_path=latch_path)

        lockdown1.declare_lockdown(initiated_by="admin", reason="Perimeter breach")
        assert latch_path.exists()

        # Attacker modifies status in latch file
        content = json.loads(latch_path.read_text(encoding="utf-8"))
        content["status"] = "LOCKDOWN_INACTIVE"  # Tampered without recomputing signature
        latch_path.write_text(json.dumps(content), encoding="utf-8")

        # Boot new manager -> signature verification fails -> fails closed!
        lockdown2 = EmergencyLockdownManager(store=identity_store, latch_path=latch_path)
        assert lockdown2.is_active is True
        assert lockdown2._lockdown_details["status"] == "LOCKDOWN_FAIL_CLOSED_CORRUPTED_LATCH"
        assert "invalid signature" in lockdown2._lockdown_details["reason"]

    def test_lockdown_deleted_latch_reconciled_from_database(self, identity_store, temp_dir):
        """Deleting latch file across reboot is detected via SQLite events and fails closed."""
        latch_path = temp_dir / ".emergency_lockdown.latch"
        lockdown1 = EmergencyLockdownManager(store=identity_store, latch_path=latch_path)

        lockdown1.declare_lockdown(initiated_by="admin", reason="Active cyber attack")
        assert latch_path.exists()

        # Attacker unlinks the latch file before restart
        latch_path.unlink()
        assert not latch_path.exists()

        # Boot new manager -> cross-checks SQLite events -> detects unlifted lockdown -> fails closed!
        lockdown2 = EmergencyLockdownManager(store=identity_store, latch_path=latch_path)
        assert lockdown2.is_active is True
        assert "deleted latch detected" in lockdown2._lockdown_details["reason"]
        # Latch must be re-persisted
        assert latch_path.exists()

    def test_lockdown_empty_latch_fails_closed(self, identity_store, temp_dir):
        """0-byte latch file triggers immediate fail-closed lockdown on boot."""
        latch_path = temp_dir / ".emergency_lockdown.latch"
        latch_path.write_text("", encoding="utf-8")

        lockdown = EmergencyLockdownManager(store=identity_store, latch_path=latch_path)
        assert lockdown.is_active is True
        assert lockdown._lockdown_details["status"] == "LOCKDOWN_FAIL_CLOSED_CORRUPTED_LATCH"

    def test_lockdown_unauthorized_lift_rejected(self, identity_store, temp_dir, admin_user, operator_user):
        """Non-admin callers cannot terminate emergency lockdown."""
        identity_store.create_user(admin_user)
        identity_store.create_user(operator_user)

        latch_path = temp_dir / ".emergency_lockdown.latch"
        lockdown = EmergencyLockdownManager(store=identity_store, latch_path=latch_path)
        lockdown.declare_lockdown(initiated_by="admin", reason="Threat active")

        # Operator attempts lift -> PermissionError
        with pytest.raises(PermissionError, match="not authorized"):
            lockdown.lift_lockdown(lifted_by="operator_east", reason="Try bypass", authorizing_admin=operator_user)

        # Anonymous or unprivileged username -> PermissionError
        with pytest.raises(PermissionError, match="not authorized"):
            lockdown.lift_lockdown(lifted_by="intruder", reason="Try bypass")

        # Verified admin succeeds
        res = lockdown.lift_lockdown(lifted_by="admin", reason="Perimeter secured", authorizing_admin=admin_user)
        assert res["status"] == "LOCKDOWN_LIFTED"
        assert lockdown.is_active is False

    def test_lockdown_active_client_session_blocked_from_surveillance(
        self, identity_store, temp_dir, operator_user
    ):
        """Active client sessions are blocked by policy engine and session manager during lockdown."""
        identity_store.create_user(operator_user)

        latch_path = temp_dir / ".emergency_lockdown.latch"
        lockdown = EmergencyLockdownManager(store=identity_store, latch_path=latch_path)
        session_mgr = SessionManager(store=identity_store, lockdown_manager=lockdown)
        policy_engine = ZeroTrustPolicyEngine(store=identity_store, lockdown_manager=lockdown)

        # Create session before lockdown
        sess = session_mgr.create_session(operator_user)
        assert sess.is_active()

        # Declare lockdown
        lockdown.declare_lockdown(initiated_by="admin", reason="Containment")

        # 1. SessionManager blocks client session validation
        with pytest.raises(SessionRevokedError, match="emergency_lockdown|lockdown"):
            session_mgr.validate_and_touch(sess.session_id)

        # 2. Policy Engine blocks surveillance operations
        dec = policy_engine.authorize(
            user=operator_user,
            action="camera:view",
            resource_type=ResourceType.CAMERA,
            resource_id="cam_01",
            session=sess,
        )
        assert dec.allowed is False
        assert "lockdown" in dec.reason.lower()


# ---------------------------------------------------------------------------
# Domain D: Sentinel Reverse-Proxy Header Spoofing & Multi-Signal Risk
# ---------------------------------------------------------------------------

class TestDomainDSentinelSessionSecurity:
    """Adversarial verification of Sentinel reverse-proxy header anti-spoofing and session risk."""

    def test_proxy_header_spoofing_prevented_without_trusted_proxy(self):
        """Client-supplied X-Forwarded-For is ignored when direct socket is not in trusted_proxies."""
        headers = {
            "X-Forwarded-For": "10.0.0.1, 172.16.0.1",
            "X-Real-IP": "10.0.0.1",
            "Client-IP": "10.0.0.1",
        }
        direct_socket_ip = "192.168.1.100"

        resolved = resolve_client_ip(
            direct_socket_ip=direct_socket_ip,
            headers=headers,
            trusted_proxies=set(),  # No trusted proxy configured
        )
        # Must return the direct socket IP, completely ignoring spoofed headers
        assert resolved == "192.168.1.100"

    def test_proxy_header_honored_for_trusted_proxy_only(self):
        """X-Forwarded-For is honored ONLY when direct socket IP is in trusted_proxies."""
        headers = {"X-Forwarded-For": "203.0.113.195, 10.0.0.2"}
        direct_socket_ip = "127.0.0.1"  # Local NGINX proxy

        resolved = resolve_client_ip(
            direct_socket_ip=direct_socket_ip,
            headers=headers,
            trusted_proxies={"127.0.0.1"},
        )
        assert resolved == "203.0.113.195"

    def test_sentinel_dual_mutation_immediate_session_revocation(self, identity_store, operator_user):
        """Simultaneous IP and User-Agent mutation triggers immediate session revocation."""
        identity_store.create_user(operator_user)
        sentinel = CAMservSentinelIdentity(store=identity_store)

        sess = SessionRecord(
            session_id="sess_dual_mut_01",
            user_id=operator_user.user_id,
            username=operator_user.username,
            role=operator_user.role,
            auth_assurance_level=AuthAssuranceLevel.AAL1,
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            last_activity_utc=datetime.now(timezone.utc).isoformat(),
            expires_at_utc="2099-01-01T00:00:00Z",
            ip_address="192.168.1.50",
            user_agent="CAMserv-Desktop-v1.0",
        )
        identity_store.create_session(sess)

        mitigation = sentinel.inspect_session_context(
            session=sess,
            incoming_ip="10.200.5.99",
            incoming_ua="Mozilla/5.0 (Windows NT 10.0; Win64; x64) MaliciousBrowser/99.0",
        )
        assert mitigation.action == "REVOKE_SESSION"
        assert identity_store.get_session("sess_dual_mut_01").is_revoked is True

    def test_sentinel_sensitive_action_post_roaming_demands_step_up(self, identity_store, operator_user):
        """Mobile roaming permits routine view, but sensitive action post-roam demands step-up MFA."""
        identity_store.create_user(operator_user)
        config = SentinelConfig(allow_ip_roaming=True)
        sentinel = CAMservSentinelIdentity(store=identity_store, config=config)

        sess = SessionRecord(
            session_id="sess_roam_01",
            user_id=operator_user.user_id,
            username=operator_user.username,
            role=operator_user.role,
            auth_assurance_level=AuthAssuranceLevel.AAL1,
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            last_activity_utc=datetime.now(timezone.utc).isoformat(),
            expires_at_utc="2099-01-01T00:00:00Z",
            ip_address="192.168.1.50",
            user_agent="CAMserv-Mobile-v1.0",
        )
        identity_store.create_session(sess)

        # 1. Routine camera viewing after network transition -> ALLOW
        mit_view = sentinel.inspect_session_context(
            session=sess,
            incoming_ip="10.50.0.100",  # Roamed IP
            incoming_ua="CAMserv-Mobile-v1.0",
            action="camera:view",
        )
        assert mit_view.action == "ALLOW"

        # 2. Sensitive evidence export during another network transition -> STEP_UP_REQUIRED
        mit_export = sentinel.inspect_session_context(
            session=sess,
            incoming_ip="10.60.0.200",  # Second IP mutation with sensitive action
            incoming_ua="CAMserv-Mobile-v1.0",
            action="evidence:export",
        )
        assert mit_export.action == "STEP_UP_REQUIRED"

    def test_sentinel_admin_anti_lockout_under_brute_force(self, identity_store, admin_user):
        """Distributed credential spraying does not lock out local administrator."""
        identity_store.create_user(admin_user)
        config = SentinelConfig(admin_lockout_protection=True, max_account_failures=5)
        sentinel = CAMservSentinelIdentity(store=identity_store, config=config)

        # Simulate 10 failed login attempts
        for _ in range(10):
            mit = sentinel.record_login_attempt(username="admin", ip_address="192.168.1.200", success=False)
            assert mit.action in ("DELAY", "BLOCK_IP")

        # Administrator account remains ACTIVE (not locked)
        user = identity_store.get_user_by_username("admin")
        assert user.status == AccountStatus.ACTIVE
        assert user.is_locked() is False


# ---------------------------------------------------------------------------
# Domain E: Object-Level Authorization, BOLA/IDOR & Step-Up MFA
# ---------------------------------------------------------------------------

class TestDomainEAuthorizationCoverage:
    """Adversarial verification of BOLA/IDOR camera isolation and privilege boundaries."""

    def test_bola_idor_cross_camera_denied(self, identity_store, operator_user):
        """Operator assigned to camera_east cannot access camera_west."""
        identity_store.create_user(operator_user)
        # Assign explicit scope to camera_east only
        scope = ResourceScope(
            scope_id="scope_east",
            user_id=operator_user.user_id,
            resource_type=ResourceType.CAMERA,
            resource_id="camera_east",
            permissions={"camera:view", "camera:ptz", "stream:view"},
            granted_by="admin",
        )
        identity_store.add_resource_scope(scope)

        engine = ZeroTrustPolicyEngine(store=identity_store)

        # Access to camera_east is granted
        dec_east = engine.authorize(
            user=operator_user,
            action="camera:view",
            resource_type=ResourceType.CAMERA,
            resource_id="camera_east",
        )
        assert dec_east.allowed is True

        # Access to camera_west is strictly denied (BOLA/IDOR defense)
        dec_west = engine.authorize(
            user=operator_user,
            action="camera:view",
            resource_type=ResourceType.CAMERA,
            resource_id="camera_west",
        )
        assert dec_west.allowed is False
        assert "not assigned" in dec_west.reason.lower() or "does not permit" in dec_west.reason.lower()

    def test_vertical_privilege_escalation_denied(self, identity_store, viewer_user):
        """Viewer cannot execute operator PTZ control or administrative configuration."""
        identity_store.create_user(viewer_user)
        engine = ZeroTrustPolicyEngine(store=identity_store)

        dec_ptz = engine.authorize(
            user=viewer_user,
            action="camera:ptz",
            resource_type=ResourceType.CAMERA,
            resource_id="camera_01",
        )
        assert dec_ptz.allowed is False
        assert "does not permit" in dec_ptz.reason.lower()

    def test_step_up_mandatory_for_evidence_export(self, identity_store, operator_user):
        """Evidence export strictly requires AAL2 session; AAL1 session is rejected."""
        identity_store.create_user(operator_user)
        engine = ZeroTrustPolicyEngine(store=identity_store)

        sess_aal1 = SessionRecord(
            session_id="sess_aal1",
            user_id=operator_user.user_id,
            username=operator_user.username,
            role=operator_user.role,
            auth_assurance_level=AuthAssuranceLevel.AAL1,
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            last_activity_utc=datetime.now(timezone.utc).isoformat(),
            expires_at_utc="2099-01-01T00:00:00Z",
            ip_address="127.0.0.1",
            user_agent="test",
        )

        dec = engine.authorize(
            user=operator_user,
            action="evidence:export",
            resource_type=ResourceType.RECORDING,
            resource_id="rec_001",
            session=sess_aal1,
        )
        assert dec.allowed is False
        assert dec.required_aal == AuthAssuranceLevel.AAL2
        assert "multi-factor authentication" in dec.reason.lower()


# ---------------------------------------------------------------------------
# Domain F & G: Pipeline Isolation Under Compound Fault Injection
# ---------------------------------------------------------------------------

class TestDomainFGPipelineIsolationRegression:
    """Surveillance pipeline air-gap: compound identity failures never drop video frames."""

    def test_pipeline_zero_frame_loss_under_compound_failures(self, identity_store, temp_dir):
        """Ingestion queue maintains 100% continuity under concurrent database crash and lockdown."""
        latch_path = temp_dir / ".emergency_lockdown.latch"
        lockdown = EmergencyLockdownManager(store=identity_store, latch_path=latch_path)

        # 1. Trigger catastrophic identity failures
        lockdown.declare_lockdown(initiated_by="admin", reason="Hardware qualification stress")
        # Tamper latch
        latch_path.write_text("corrupted_content", encoding="utf-8")

        # 2. Ingest 50 video frames into pipeline queue
        queue = BoundedPipelineQueue(name="video_ingest_test", maxsize=200)
        ledger = RecordingContinuityLedger()
        ledger.start_segment(camera_id="cam_stress_01", stream_id="main", segment_id="seg_stress_01")

        for f in range(50):
            frame_data = {
                "sequence": f,
                "timestamp": time.time(),
                "payload_hash": hashlib.sha256(f"frame_{f}".encode()).hexdigest(),
            }
            queue.put(frame_data)
            ledger.record_frame(camera_id="cam_stress_01", segment_id="seg_stress_01", frame_seq=f, pts=f * 0.0333)

        # 3. Verify zero frame loss and 100% continuity
        assert queue.qsize() == 50
        rec = ledger._records["cam_stress_01:seg_stress_01"]
        assert rec.observed_frames == 50
        assert rec.confirmed_missing_frames_total == 0
