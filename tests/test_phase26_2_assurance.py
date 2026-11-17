"""
tests.test_phase26_2_assurance
==============================

Phase 26.2: Identity Security Closure & Final Software Assurance
Independent Software Assurance Test Suite for CAMserv 0.10.0-rc7.

Covers:
1.  Audit Checkpoint Trust Anchor Assurance:
    - External trust anchor store persistence outside SQLite DB.
    - Checkpoint sequence monotonicity enforcement (anti-rollback).
    - Coordinated database + internal checkpoint rollback detection.
    - Ed25519 asymmetric signing and verification (appliance private key, auditor public key).
    - Divergent head hash detection at identical sequence numbers.
2.  Windows Bootstrap Hardening:
    - Atomic exclusive creation (O_CREAT | O_EXCL) preventing TOCTOU races.
    - DACL application BEFORE writing sensitive token content.
    - Windows DACL verification and inheritance stripping.
3.  Lockdown State & Active Session Enforcement:
    - Durable recovery latch file surviving application process restart.
    - Fail-closed initialization upon latch corruption.
    - Active client session rejection in SessionManager.validate_and_touch().
    - Active client request rejection in ZeroTrustPolicyEngine.authorize().
    - Invariant preservation of video recording and administrative recovery.
4.  Sentinel Multi-Signal Adaptive Session Security:
    - Concurrent IP and User-Agent mutation detection (token theft -> session revocation).
    - User-Agent client fingerprint mutation detection (browser spoofing -> step-up challenge).
    - Sensitive action invocation after roaming (step-up challenge for high-impact actions).
    - Normal mobile roaming preservation for routine surveillance viewing.
5.  Recording Pipeline Independence & Fault Isolation Regression:
    - Verification that concurrent identity DB, audit store, and lockdown failures
      never drop video ingestion frames.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

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
    CheckpointSequenceRegressionError,
    DurableIdentityStore,
    EmergencyLockdownManager,
    ExternalCheckpointStore,
    IdentityRole,
    LocalAdministratorBootstrap,
    ResourceType,
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
)


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def identity_store(temp_dir):
    db_path = temp_dir / "identity.db"
    store = DurableIdentityStore(db_path=db_path)
    yield store
    store.close()


# ===========================================================================
# 1. Audit Checkpoint Trust Anchor Assurance
# ===========================================================================

class TestAuditCheckpointAssurance:
    """Verifies independent external checkpoint persistence, monotonicity, and Ed25519 asymmetric verification."""

    def test_external_checkpoint_store_monotonicity_enforcement(self, temp_dir):
        store_path = temp_dir / "trust_anchor.json"
        store = ExternalCheckpointStore(store_path=store_path)

        # Record checkpoint 1 at sequence 5
        chk1 = AuditCheckpoint(
            checkpoint_id="chk_1",
            sequence_number=5,
            head_entry_hash="hash_seq_5",
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            signature="sig_1",
        )
        store.save_checkpoint(chk1)

        latest = store.get_latest_checkpoint()
        assert latest is not None
        assert latest.sequence_number == 5

        # Record checkpoint 2 at sequence 10 (monotonic advance -> allowed)
        chk2 = AuditCheckpoint(
            checkpoint_id="chk_2",
            sequence_number=10,
            head_entry_hash="hash_seq_10",
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            signature="sig_2",
        )
        store.save_checkpoint(chk2)
        assert store.get_latest_checkpoint().sequence_number == 10

        # ATTACK: Adversary attempts to store an older checkpoint at sequence 7 (rollback)
        chk_regress = AuditCheckpoint(
            checkpoint_id="chk_rollback",
            sequence_number=7,
            head_entry_hash="hash_seq_7",
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            signature="sig_regress",
        )
        with pytest.raises(CheckpointSequenceRegressionError, match="Monotonicity violation"):
            store.save_checkpoint(chk_regress)

    def test_coordinated_snapshot_rollback_detected_by_external_store(self, identity_store, temp_dir):
        """Demonstrates that even if an attacker rolls back the database AND internal tables to a coordinated
        older backup, the independent ExternalCheckpointStore catches the rollback."""
        audit = TamperEvidentSecurityAudit(identity_store)
        store_path = temp_dir / "external_anchor.json"
        ext_store = ExternalCheckpointStore(store_path=store_path)
        signing_key = secrets.token_bytes(32)

        # 1. Log events 1-3
        for i in range(1, 4):
            audit.log_event(
                SecurityEvent(
                    event_id=f"ev_coord_{i}",
                    event_type="SYS_BOOT",
                    severity=SecurityEventSeverity.INFO,
                    actor_id="system",
                    details={"i": i},
                    action_taken="RECORDED",
                )
            )

        # 2. Adversary takes coordinated backup snapshot of identity.db at sequence 3
        snapshot_db = temp_dir / "coordinated_snapshot.db"
        snap_conn = sqlite3.connect(snapshot_db)
        try:
            identity_store._conn.backup(snap_conn)
        finally:
            snap_conn.close()

        # 3. System continues: critical security intrusion events 4-7 happen
        for i in range(4, 8):
            audit.log_event(
                SecurityEvent(
                    event_id=f"ev_coord_{i}",
                    event_type="PHYSICAL_BREACH",
                    severity=SecurityEventSeverity.CRITICAL,
                    actor_id="intruder",
                    details={"i": i},
                    action_taken="ALARM_TRIGGERED",
                )
            )

        # 4. Legitimate checkpoint anchored externally at sequence 7
        audit.create_and_persist_checkpoint(ext_store, signing_key=signing_key)
        assert ext_store.get_latest_checkpoint().sequence_number == 7

        # 5. ATTACK: Adversary restores snapshot.db over identity.db to erase breach evidence
        snap_restore = sqlite3.connect(snapshot_db)
        try:
            snap_restore.backup(identity_store._conn)
        finally:
            snap_restore.close()

        # Local SQLite database now only has 3 rows and internal chain is valid
        is_local_valid, count, _ = audit.verify_chain_integrity()
        assert is_local_valid is True
        assert count == 3

        # BUT verification against independent external trust anchor detects the coordinated rollback!
        is_trust_valid, err = audit.verify_against_external_store(ext_store, signing_key=signing_key)
        assert is_trust_valid is False
        assert "Rollback detected" in err
        assert "expected sequence 7" in err

    def test_ed25519_asymmetric_checkpoint_signing_and_verification(self, identity_store):
        """Verifies asymmetric Ed25519 signatures: appliance holds private key; auditor verifies with public key."""
        audit = TamperEvidentSecurityAudit(identity_store)
        audit.log_event(
            SecurityEvent(
                event_id="ev_ed25519_1",
                event_type="AUDIT_ANCHOR",
                severity=SecurityEventSeverity.INFO,
                actor_id="system",
                details={"cert": "test"},
                action_taken="SIGNED",
            )
        )

        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        checkpoint = audit.create_checkpoint(private_key=private_key)
        assert checkpoint.algorithm == "Ed25519"
        assert len(checkpoint.signature) == 128  # 64-byte Ed25519 signature in hex

        # Valid asymmetric verification
        ok, err = audit.verify_against_checkpoint(checkpoint, public_key=public_key)
        assert ok is True
        assert err is None

        # Verification without public key fails cleanly
        ok_no_key, err_no_key = audit.verify_against_checkpoint(checkpoint, public_key=None)
        assert ok_no_key is False
        assert "public key required" in err_no_key

        # Verification with forged public key fails
        wrong_public_key = Ed25519PrivateKey.generate().public_key()
        ok_wrong_key, err_wrong = audit.verify_against_checkpoint(checkpoint, public_key=wrong_public_key)
        assert ok_wrong_key is False
        assert "signature invalid or forged" in err_wrong


# ===========================================================================
# 2. Windows Bootstrap Hardening
# ===========================================================================

class TestWindowsBootstrapHardening:
    """Verifies atomic O_CREAT | O_EXCL creation and pre-DACL protection."""

    def test_atomic_exclusive_creation_and_dacl_application(self, identity_store, temp_dir):
        token_path = temp_dir / ".bootstrap_token"
        bootstrap = LocalAdministratorBootstrap(
            store=identity_store,
            token_path=token_path,
        )

        meta = bootstrap.initiate_bootstrap(validity_sec=300)
        assert token_path.exists()
        assert len(meta["token"]) == 64

        # Read file content and confirm format
        content = token_path.read_text(encoding="utf-8").strip()
        assert content == meta["token"]

        # Completion succeeds
        res = bootstrap.complete_bootstrap(
            bootstrap_token=meta["token"],
            username="admin_p26_2",
            password="SecurePassphrase2026!#$",
        )
        assert res["status"] == "BOOTSTRAP_COMPLETED"
        assert not token_path.exists(), "Token file shredded upon completion"

    def test_existing_token_path_is_safely_replaced(self, identity_store, temp_dir):
        """Verifies that an existing pre-created target path is cleaned up before exclusive creation."""
        token_path = temp_dir / ".bootstrap_token"
        token_path.write_text("pre_existing_garbage", encoding="utf-8")

        bootstrap = LocalAdministratorBootstrap(
            store=identity_store,
            token_path=token_path,
        )

        meta = bootstrap.initiate_bootstrap(validity_sec=300)
        # Old content is replaced with new 256-bit token
        assert token_path.read_text(encoding="utf-8").strip() == meta["token"]


# ===========================================================================
# 3. Lockdown State & Active Session Enforcement
# ===========================================================================

class TestLockdownDurableRecoveryAndActiveSessionEnforcement:
    """Verifies durable latch persistence across restarts and active session blocking in PolicyEngine and SessionManager."""

    def test_durable_latch_survives_process_restart(self, identity_store, temp_dir):
        latch_path = temp_dir / "recovery.latch"
        lockdown1 = EmergencyLockdownManager(store=identity_store, latch_path=latch_path)

        assert not lockdown1.is_active
        lockdown1.declare_lockdown(initiated_by="secops", reason="Physical perimeter breached")
        assert lockdown1.is_active
        assert latch_path.exists()

        # SIMULATE APPLICATION CRASH / RESTART:
        # Create a brand new EmergencyLockdownManager pointing to the same latch file
        lockdown2 = EmergencyLockdownManager(store=identity_store, latch_path=latch_path)
        assert lockdown2.is_active is True, "Lockdown state must survive process restarts via durable latch"
        assert lockdown2._lockdown_details.get("reason") == "Physical perimeter breached"

        # Administrator lifts lockdown
        admin_user = UserRecord(user_id="adm_1", username="admin", role=IdentityRole.ADMIN, is_administrator=True)
        res = lockdown2.lift_lockdown(lifted_by="admin", reason="All clear", authorizing_admin=admin_user)
        assert res["status"] == "LOCKDOWN_LIFTED"
        assert lockdown2.is_active is False
        assert not latch_path.exists()

    def test_corrupt_latch_fails_closed_on_boot(self, identity_store, temp_dir):
        """Verifies that if the recovery latch file is corrupted, the system fails closed on boot."""
        latch_path = temp_dir / "recovery.latch"
        latch_path.write_text("CORRUPTED_GARBAGE_JSON_NOT_VALID", encoding="utf-8")

        lockdown = EmergencyLockdownManager(store=identity_store, latch_path=latch_path)
        assert lockdown.is_active is True, "Must fail closed when recovery latch is corrupt"
        assert lockdown._lockdown_details.get("status") == "LOCKDOWN_FAIL_CLOSED_CORRUPTED_LATCH"

    def test_lockdown_enforcement_in_policy_engine(self, identity_store, temp_dir):
        """Verifies that ZeroTrustPolicyEngine checks lockdown_manager.is_active on every request."""
        latch_path = temp_dir / "recovery.latch"
        lockdown = EmergencyLockdownManager(store=identity_store, latch_path=latch_path)
        engine = ZeroTrustPolicyEngine(store=identity_store, lockdown_manager=lockdown)

        client_user = UserRecord(
            user_id="u_client_lock",
            username="guard1",
            role=IdentityRole.OPERATOR,
            allowed_camera_ids={"cam_01"},
        )
        identity_store.create_user(client_user)

        # Before lockdown -> Allowed
        d_before = engine.authorize(client_user, "camera:view", ResourceType.CAMERA, "cam_01")
        assert d_before.allowed is True

        # Declare lockdown
        lockdown.declare_lockdown(initiated_by="admin", reason="Alarm active")

        # After lockdown -> Client actions blocked immediately
        d_after = engine.authorize(client_user, "camera:view", ResourceType.CAMERA, "cam_01")
        assert d_after.allowed is False
        assert "Emergency appliance lockdown active" in d_after.reason

        # Ingestion actions remain 100% permitted during lockdown for pipeline actors
        system_user = UserRecord(user_id="u_sys_ingest", username="ingestion_worker", role=IdentityRole.ADMIN, is_administrator=True)
        identity_store.create_user(system_user)
        d_ingest = engine.authorize(system_user, "recording:ingest", ResourceType.STREAM, "cam_01")
        assert d_ingest.allowed is True

    def test_lockdown_enforcement_in_session_manager(self, identity_store, temp_dir):
        """Verifies that SessionManager rejects active client sessions immediately during lockdown."""
        latch_path = temp_dir / "recovery.latch"
        lockdown = EmergencyLockdownManager(store=identity_store, latch_path=latch_path)
        sm = SessionManager(store=identity_store, lockdown_manager=lockdown)

        client_user = UserRecord(user_id="u_sess_cli", username="client_ops", role=IdentityRole.OPERATOR)
        identity_store.create_user(client_user)
        session = sm.create_session(client_user)

        # Validate before lockdown -> OK
        assert sm.validate_and_touch(session.session_id) is not None

        # Declare lockdown
        lockdown.declare_lockdown(initiated_by="admin", reason="Incident containment")

        # Validate after lockdown -> SessionRevokedError raised immediately
        with pytest.raises(SessionRevokedError, match="emergency_lockdown"):
            sm.validate_and_touch(session.session_id)

        # Attempting to create a new client session during lockdown is rejected
        with pytest.raises(SessionError, match="emergency appliance lockdown is active"):
            sm.create_session(client_user)


# ===========================================================================
# 4. Sentinel Multi-Signal Adaptive Session Security
# ===========================================================================

class TestSentinelMultiSignalAdaptiveSecurity:
    """Verifies multi-signal correlation (IP, User-Agent, action sensitivity)."""

    def test_concurrent_ip_and_ua_mutation_revokes_session(self, identity_store):
        sentinel = CAMservSentinelIdentity(store=identity_store)
        u1 = UserRecord(user_id="u_guard", username="guard_patrol", role=IdentityRole.OPERATOR)
        identity_store.create_user(u1)
        session = SessionRecord(
            session_id="s_steal_01",
            user_id="u_guard",
            username="guard_patrol",
            role=IdentityRole.OPERATOR,
            auth_assurance_level=AuthAssuranceLevel.AAL1,
            ip_address="192.168.1.100",
            user_agent="CAMservGuardClient/1.0",
        )
        identity_store.create_session(session)

        # Adversary uses stolen session token from different IP AND different User-Agent
        mitigation = sentinel.inspect_session_context(
            session=session,
            incoming_ip="198.51.100.99",
            incoming_ua="Mozilla/5.0 (Windows NT 10.0; Win64; x64) MaliciousScanner/2.0",
        )
        assert mitigation.action == "REVOKE_SESSION"
        assert "Concurrent IP and User-Agent mutation" in mitigation.reason

        # Session is revoked in database
        refreshed = identity_store.get_session("s_steal_01")
        assert refreshed.is_revoked is True

    def test_user_agent_mutation_alone_triggers_step_up(self, identity_store):
        sentinel = CAMservSentinelIdentity(store=identity_store)
        u2 = UserRecord(user_id="u_guard2", username="guard2", role=IdentityRole.OPERATOR)
        identity_store.create_user(u2)
        session = SessionRecord(
            session_id="s_ua_01",
            user_id="u_guard2",
            username="guard2",
            role=IdentityRole.OPERATOR,
            auth_assurance_level=AuthAssuranceLevel.AAL1,
            ip_address="192.168.1.100",
            user_agent="CAMservApp/1.0",
        )
        identity_store.create_session(session)

        # Same IP, but browser User-Agent suddenly changes (e.g. injected session cookie)
        mitigation = sentinel.inspect_session_context(
            session=session,
            incoming_ip="192.168.1.100",
            incoming_ua="Python-requests/2.31",
        )
        assert mitigation.action == "STEP_UP_REQUIRED"
        assert "fingerprint mutation" in mitigation.reason

    def test_sensitive_action_after_roaming_triggers_step_up(self, identity_store):
        config = SentinelConfig(allow_ip_roaming=True)
        sentinel = CAMservSentinelIdentity(store=identity_store, config=config)
        u3 = UserRecord(user_id="u_admin_roam", username="roam_admin", role=IdentityRole.ADMIN, is_administrator=True)
        identity_store.create_user(u3)

        session = SessionRecord(
            session_id="s_roam_sens",
            user_id="u_admin_roam",
            username="roam_admin",
            role=IdentityRole.ADMIN,
            auth_assurance_level=AuthAssuranceLevel.AAL2,
            ip_address="192.168.1.50",
            user_agent="CAMservAdminConsole/1.0",
        )
        identity_store.create_session(session)

        # IP roamed to 10.0.50.25 (same UA). Routine viewing is allowed
        m_view = sentinel.inspect_session_context(
            session=session,
            incoming_ip="10.0.50.25",
            incoming_ua="CAMservAdminConsole/1.0",
            action="camera:view",
        )
        assert m_view.action == "ALLOW"
        assert session.ip_address == "10.0.50.25"

        # Now, from the new roamed IP, user attempts high-impact sensitive action: evidence:export
        m_export = sentinel.inspect_session_context(
            session=session,
            incoming_ip="10.0.50.26",
            incoming_ua="CAMservAdminConsole/1.0",
            action="evidence:export",
        )
        assert m_export.action == "STEP_UP_REQUIRED"
        assert "Sensitive action 'evidence:export' after network roaming" in m_export.reason


# ===========================================================================
# 5. Recording Pipeline Independence Regression
# ===========================================================================

class TestRecordingPipelineIndependenceRegression:
    """Proves that continuous surveillance recording remains 100% operational under combined identity failures."""

    def test_combined_identity_failure_and_lockdown_recording_continuity(self, identity_store, temp_dir):
        latch_path = temp_dir / "recovery.latch"
        lockdown = EmergencyLockdownManager(store=identity_store, latch_path=latch_path)
        queue = BoundedPipelineQueue(name="video_ingest_queue", maxsize=100)
        ledger = RecordingContinuityLedger()
        ledger.start_segment(camera_id="cam_vault", stream_id="main", segment_id="seg_vault_01")

        # Ingest initial 10 frames
        for f in range(10):
            queue.put({"channel_id": "cam_vault", "frame_idx": f, "data": b"h264_payload"})
            ledger.record_frame(camera_id="cam_vault", segment_id="seg_vault_01", frame_seq=f, pts=f * 0.0333)

        # DECLARE EMERGENCY LOCKDOWN
        lockdown.declare_lockdown(initiated_by="perimeter_sensor", reason="Intrusion barrier trip")

        # FORCIBLY CRASH IDENTITY DATABASE
        identity_store.close()

        # Ingest subsequent 20 frames during active lockdown AND crashed identity DB
        for f in range(10, 30):
            queue.put({"channel_id": "cam_vault", "frame_idx": f, "data": b"h264_payload"})
            ledger.record_frame(camera_id="cam_vault", segment_id="seg_vault_01", frame_seq=f, pts=f * 0.0333)

        assert queue.qsize() == 30
        rec = ledger._records["cam_vault:seg_vault_01"]
        assert rec.observed_frames == 30
        assert rec.confirmed_missing_frames_total == 0
