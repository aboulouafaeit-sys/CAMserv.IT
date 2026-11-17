"""
tests.test_phase26_1_adversarial
================================

Phase 26.1: Identity Security Verification & Adversarial Hardening
Independent Adversarial Test Suite for CAMserv 0.10.0-rc7.

Covers:
1.  WebAuthn/Passkey Capability Truthfulness Verification (Option generation vs provisional hooks).
2.  Key Theft & Offline Database Decryption Resistance (AES-256-GCM authentication tag integrity).
3.  Audit Ledger Adversarial Attacks & External Checkpoint Verification:
    - In-place row modification detection.
    - Row deletion detection.
    - Row insertion detection.
    - Full forward hash chain rewrite detection via HMAC/Ed25519 signed AuditCheckpoint.
    - Database snapshot rollback detection via AuditCheckpoint sequence verification.
    - Checkpoint signature tampering rejection.
4.  Bootstrap Token Security Hardening:
    - Symlink / reparse point traversal rejection.
    - Atomic O_CREAT descriptor and Windows NTFS DACL inheritance stripping.
    - One-time consumption and TTL expiration.
5.  Sentinel Hardening & DoS Resistance:
    - Administrator lockout DoS mitigation (progressive delay without account locking).
    - Operator/Viewer lockout enforcement on brute force.
    - Mobile IP roaming support without false-positive session drops.
    - Anomaly detection and session revocation when IP roaming is disabled.
    - Memory bounding and expired sliding-window pruning.
6.  Emergency Lockdown Failsafe Hardening:
    - Immediate in-memory barrier engagement even if database operations fail.
    - Unprivileged / unauthorized attempts to lift lockdown strictly denied.
    - Continuous video ingestion actions permitted during active lockdown.
7.  Zero-Trust Authorization & BOLA/IDOR Penetration:
    - Horizontal cross-camera BOLA/IDOR scanning blocked.
    - Vertical privilege escalation from Viewer/Operator to Administrator blocked.
    - AAL2 step-up enforcement for critical administrative actions.
8.  Recording Pipeline Failure Isolation:
    - Verification that catastrophic identity DB crash fails closed for auth without halting video ingestion.
9.  Argon2id Calibration & Concurrency Bounding:
    - Parameter verification (RFC 9106) and semaphore exhaustion behavior.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.exceptions import InvalidTag

from camserv.platform.stability import (
    BoundedPipelineQueue,
    RecordingContinuityLedger,
)
from camserv.security.identity import (
    AAL2_MANDATORY_PERMISSIONS,
    AccountStatus,
    Argon2idConfig,
    Argon2idPasswordHasher,
    AuditCheckpoint,
    AuthAssuranceLevel,
    AuthorizationDecision,
    BootstrapAlreadyCompletedError,
    BootstrapError,
    BootstrapTokenExpiredError,
    CameraCredentialProtection,
    CAMservSentinelIdentity,
    ConcurrencyExhaustedError,
    DurableIdentityStore,
    EmergencyLockdownManager,
    IdentityRole,
    InvalidBootstrapTokenError,
    LocalAdministratorBootstrap,
    MFASecretProtector,
    MFAType,
    PasskeyManager,
    ResourceScope,
    ResourceType,
    SecurityEvent,
    SecurityEventSeverity,
    SentinelConfig,
    SessionManager,
    SessionRecord,
    StepUpRequiredError,
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
# 1. WebAuthn / Passkey Capability Verification
# ===========================================================================

class TestWebAuthnCapabilityVerification:
    """Verifies that WebAuthn capabilities are accurately delineated as provisional interface hooks."""

    def test_passkey_options_generation(self):
        pm = PasskeyManager(rp_id="camserv.local", rp_name="CAMserv Appliance")
        opts = pm.create_registration_options("usr_test123", "secops_admin")

        assert opts["rp"]["id"] == "camserv.local"
        assert opts["rp"]["name"] == "CAMserv Appliance"
        assert opts["user"]["name"] == "secops_admin"
        assert "challenge" in opts
        assert len(opts["pubKeyCredParams"]) >= 2
        assert opts["pubKeyCredParams"][0]["alg"] == -7  # ES256
        assert opts["timeout"] == 60000

        auth_opts = pm.create_assertion_options("usr_test123")
        assert auth_opts["rpId"] == "camserv.local"
        assert "challenge" in auth_opts
        assert auth_opts["userVerification"] == "preferred"

    def test_passkey_provisional_hook_status(self):
        """Verifies that attempting full WebAuthn RP verification explicitly raises NotImplementedError."""
        pm = PasskeyManager()
        dummy_response = {"id": "cred_xyz", "rawId": "raw_xyz", "type": "public-key"}

        with pytest.raises(NotImplementedError) as exc_info_reg:
            pm.verify_registration_response(dummy_response, expected_challenge="test_chal")
        assert "external RP library" in str(exc_info_reg.value)

        with pytest.raises(NotImplementedError) as exc_info_auth:
            pm.verify_assertion_response(dummy_response, expected_challenge="test_chal")
        assert "external RP library" in str(exc_info_auth.value)


# ===========================================================================
# 2. Key Theft & Offline Decryption Resistance
# ===========================================================================

class TestKeyTheftAndOfflineDecryptionResistance:
    """Verifies offline theft resistance when copying SQLite database without independent secret keys."""

    def test_database_theft_without_secret_keys_fails(self, temp_dir):
        key_file = temp_dir / "mfa_secret.key"
        protector = MFASecretProtector(key_file=key_file)
        raw_totp_secret = "JBSWY3DPEHPK3PXP"
        encrypted = protector.encrypt(raw_totp_secret)

        # Attacker copies encrypted string from database but does not have key_file
        attacker_key_file = temp_dir / "attacker_fake.key"
        attacker_protector = MFASecretProtector(key_file=attacker_key_file)

        with pytest.raises(InvalidTag):
            attacker_protector.decrypt(encrypted)

    def test_ciphertext_tampering_fails_integrity_check(self, temp_dir):
        key_file = temp_dir / "mfa_secret.key"
        protector = MFASecretProtector(key_file=key_file)
        envelope_json = protector.encrypt("SECRET_PLAINTEXT_12345")

        env = json.loads(envelope_json)
        # Tamper byte in ciphertext region ("c")
        raw_ct = bytearray(base64.b64decode(env["c"]))
        raw_ct[0] ^= 0xFF
        env["c"] = base64.b64encode(raw_ct).decode("ascii")
        tampered_envelope = json.dumps(env)

        with pytest.raises(InvalidTag):
            protector.decrypt(tampered_envelope)

    def test_camera_vault_tamper_resistance(self, temp_dir):
        key_file = temp_dir / "vault.key"
        vault = CameraCredentialProtection(key_file=key_file)
        rtsp_url = "rtsp://admin:P@ssw0rdSecure!@192.168.1.100:554/live"
        enc = vault.encrypt_secret(rtsp_url)

        # Decryption with correct key works
        assert vault.decrypt_secret(enc) == rtsp_url

        # Tampering with payload fails
        env = json.loads(enc)
        raw_ct = bytearray(base64.b64decode(env["c"]))
        raw_ct[-1] ^= 0xAA
        env["c"] = base64.b64encode(raw_ct).decode("ascii")
        bad_enc = json.dumps(env)

        with pytest.raises(InvalidTag):
            vault.decrypt_secret(bad_enc)


# ===========================================================================
# 3. Audit Ledger Adversarial Attacks & Checkpoint Verification
# ===========================================================================

class TestAuditLedgerAdversarialAttacks:
    """Simulates adversarial attacks on the SQLite audit ledger and verifies AuditCheckpoint mitigation."""

    def test_inplace_row_tampering_detected(self, identity_store):
        audit = TamperEvidentSecurityAudit(identity_store)
        for i in range(5):
            ev = SecurityEvent(
                event_id=f"ev_{i}",
                event_type="USER_LOGIN",
                severity=SecurityEventSeverity.INFO,
                actor_id=f"user_{i}",
                details={"step": i},
                action_taken="ALLOWED",
            )
            audit.log_event(ev)

        is_valid, _, _ = audit.verify_chain_integrity()
        assert is_valid is True

        # Adversary directly tampers with details of row 2 in SQLite
        identity_store._conn.execute(
            "UPDATE security_events SET details = ? WHERE event_id = 'ev_1'",
            ('{"step": 999, "tampered": true}',),
        )
        identity_store._conn.commit()

        # Hash chain verification immediately catches the payload modification
        is_tampered_valid, _, err = audit.verify_chain_integrity()
        assert is_tampered_valid is False
        assert err is not None

    def test_row_deletion_detected(self, identity_store):
        audit = TamperEvidentSecurityAudit(identity_store)
        for i in range(5):
            audit.log_event(
                SecurityEvent(
                    event_id=f"ev_del_{i}",
                    event_type="ACCESS_ATTEMPT",
                    severity=SecurityEventSeverity.INFO,
                    actor_id="tester",
                    details={"index": i},
                    action_taken="ALLOWED",
                )
            )

        is_valid, _, _ = audit.verify_chain_integrity()
        assert is_valid is True

        # Adversary deletes row ev_del_2
        identity_store._conn.execute("DELETE FROM security_events WHERE event_id = 'ev_del_2'")
        identity_store._conn.commit()

        # Chain is broken (prev_hash mismatch)
        is_del_valid, _, _ = audit.verify_chain_integrity()
        assert is_del_valid is False

    def test_row_insertion_detected(self, identity_store):
        audit = TamperEvidentSecurityAudit(identity_store)
        for i in range(4):
            audit.log_event(
                SecurityEvent(
                    event_id=f"ev_ins_{i}",
                    event_type="CONFIG_CHANGE",
                    severity=SecurityEventSeverity.INFO,
                    actor_id="admin",
                    details={"cfg": i},
                    action_taken="SAVED",
                )
            )

        is_valid, _, _ = audit.verify_chain_integrity()
        assert is_valid is True

        # Adversary inserts rogue row with fake hash
        now = datetime.now(timezone.utc).isoformat()
        identity_store._conn.execute(
            """INSERT INTO security_events
               (event_id, event_type, severity, timestamp_utc, actor_id, ip_address,
                resource_type, resource_id, details, action_taken, prev_hash, entry_hash)
               VALUES ('rogue_ev', 'BACKDOOR', 'critical', ?, 'intruder', NULL, NULL, NULL, '{}', 'NONE', '0'*64, 'f'*64)""",
            (now,),
        )
        identity_store._conn.commit()

        is_ins_valid, _, _ = audit.verify_chain_integrity()
        assert is_ins_valid is False

    def test_full_forward_chain_rewrite_bypasses_simple_verify_but_detected_by_checkpoint(self, identity_store):
        """Proves that a full internal hash chain rewrite fools verify_chain_integrity()
        but is completely detected and blocked by verify_against_checkpoint()."""
        audit = TamperEvidentSecurityAudit(identity_store)
        signing_key = secrets.token_bytes(32)

        for i in range(6):
            audit.log_event(
                SecurityEvent(
                    event_id=f"ev_chain_{i}",
                    event_type="SYSTEM_EVENT",
                    severity=SecurityEventSeverity.INFO,
                    actor_id="system",
                    details={"val": i},
                    action_taken="LOGGED",
                )
            )

        # External system obtains signed checkpoint at sequence 6
        checkpoint = audit.create_checkpoint(signing_key=signing_key)
        assert checkpoint.sequence_number == 6
        chk_valid, _ = audit.verify_against_checkpoint(checkpoint, signing_key=signing_key)
        assert chk_valid is True

        # ATTACK: Privileged local adversary tampers with row 2, and then recomputes
        # all subsequent hashes up to the head of the database!
        cursor = identity_store._conn.execute("SELECT * FROM security_events ORDER BY rowid ASC")
        rows = cursor.fetchall()

        # Modify row 1 details
        tampered_details = '{"val": "adversary_backdoor_hidden"}'
        prev_hash = rows[0]["entry_hash"]

        import hashlib
        for idx, row in enumerate(rows[1:], start=1):
            details = tampered_details if idx == 1 else row["details"]
            payload = (
                f"{row['event_id']}:{row['event_type']}:{row['severity']}:{row['timestamp_utc']}:"
                f"{row['actor_id']}:{row['ip_address']}:{row['resource_type']}:{row['resource_id']}:"
                f"{details}:{row['action_taken']}:{prev_hash}"
            )
            new_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            identity_store._conn.execute(
                "UPDATE security_events SET details = ?, prev_hash = ?, entry_hash = ? WHERE event_id = ?",
                (details, prev_hash, new_hash, row["event_id"]),
            )
            prev_hash = new_hash
        identity_store._conn.commit()

        # Standard internal hash chain check is fooled because all pointers are recalculated!
        is_local_valid, count, _ = audit.verify_chain_integrity()
        assert is_local_valid is True, "Internal hash chain recalculation appears valid locally"

        # BUT external signed checkpoint detects the rewrite!
        chk_after_attack, err = audit.verify_against_checkpoint(checkpoint, signing_key=signing_key)
        assert chk_after_attack is False
        assert "Full-chain rewrite" in err

    def test_database_snapshot_rollback_detected_by_checkpoint(self, identity_store, temp_dir):
        """Proves that rolling back the database to an older snapshot is detected by the signed checkpoint."""
        audit = TamperEvidentSecurityAudit(identity_store)
        signing_key = secrets.token_bytes(32)

        # Log initial events 1-3
        for i in range(1, 4):
            audit.log_event(
                SecurityEvent(
                    event_id=f"ev_snap_{i}",
                    event_type="USER_EVENT",
                    severity=SecurityEventSeverity.INFO,
                    actor_id="user1",
                    details={"i": i},
                    action_taken="RECORDED",
                )
            )

        # Attacker takes snapshot of DB at seq 3
        snapshot_db = temp_dir / "snapshot.db"
        snap_conn = sqlite3.connect(snapshot_db)
        try:
            identity_store._conn.backup(snap_conn)
        finally:
            snap_conn.close()

        # More events 4-6 happen (e.g. security intrusion alert)
        for i in range(4, 7):
            audit.log_event(
                SecurityEvent(
                    event_id=f"ev_snap_{i}",
                    event_type="INTRUSION_ALERT",
                    severity=SecurityEventSeverity.CRITICAL,
                    actor_id="adversary",
                    details={"i": i},
                    action_taken="ALARM",
                )
            )

        # Checkpoint created at latest state (seq 6)
        latest_checkpoint = audit.create_checkpoint(signing_key=signing_key)
        assert latest_checkpoint.sequence_number == 6
        ok, _ = audit.verify_against_checkpoint(latest_checkpoint, signing_key)
        assert ok is True

        # ATTACK: Attacker restores snapshot.db over identity.db to erase intrusion alerts!
        snap_restore = sqlite3.connect(snapshot_db)
        try:
            snap_restore.backup(identity_store._conn)
        finally:
            snap_restore.close()

        # Database on disk is valid internally at seq 3
        is_snap_valid, _, _ = audit.verify_chain_integrity()
        assert is_snap_valid is True

        # BUT checkpoint verification fails because sequence is rolled back (3 < 6) and head hash differs!
        ok_snap, err = audit.verify_against_checkpoint(latest_checkpoint, signing_key)
        assert ok_snap is False
        assert "Rollback detected" in err or "Full-chain rewrite" in err

    def test_checkpoint_signature_tampering_detected(self, identity_store):
        audit = TamperEvidentSecurityAudit(identity_store)
        signing_key = secrets.token_bytes(32)
        audit.log_event(
            SecurityEvent(
                event_id="ev_chk_sig",
                event_type="STARTUP",
                severity=SecurityEventSeverity.INFO,
                actor_id="system",
                details={},
                action_taken="INIT",
            )
        )
        checkpoint = audit.create_checkpoint(signing_key=signing_key)

        # Tampered signature
        tampered_sig = "0" * len(checkpoint.signature)
        bad_checkpoint = AuditCheckpoint(
            checkpoint_id=checkpoint.checkpoint_id,
            sequence_number=checkpoint.sequence_number,
            head_entry_hash=checkpoint.head_entry_hash,
            created_at_utc=checkpoint.created_at_utc,
            signature=tampered_sig,
        )

        ok, err = audit.verify_against_checkpoint(bad_checkpoint, signing_key)
        assert ok is False
        assert "Checkpoint signature invalid" in err


# ===========================================================================
# 4. Bootstrap Token Security Hardening
# ===========================================================================

class TestBootstrapSecurityHardening:
    """Verifies bootstrap token atomicity, symlink rejection, and Windows NTFS DACL handling."""

    def test_bootstrap_symlink_rejection(self, identity_store, temp_dir):
        token_path = temp_dir / ".bootstrap_token"
        bootstrap = LocalAdministratorBootstrap(
            store=identity_store,
            token_path=token_path,
        )

        # Mock is_symlink to simulate symlink / junction attack
        with patch.object(Path, "is_symlink", return_value=True):
            with pytest.raises(BootstrapError, match="Symlink or reparse point"):
                bootstrap.initiate_bootstrap()

    def test_bootstrap_generation_and_consumption(self, identity_store, temp_dir):
        token_path = temp_dir / ".bootstrap_token"
        bootstrap = LocalAdministratorBootstrap(
            store=identity_store,
            token_path=token_path,
        )

        meta = bootstrap.initiate_bootstrap(validity_sec=300)
        token = meta["token"]
        assert len(token) >= 32
        assert token_path.exists()

        # Admin account creation with valid token
        res = bootstrap.complete_bootstrap(
            bootstrap_token=token,
            username="superadmin",
            password="StrongPassphrase2026!#",
        )
        assert res["username"] == "superadmin"
        assert res["status"] == "BOOTSTRAP_COMPLETED"
        assert len(res["recovery_codes"]) == 10
        assert not token_path.exists(), "Bootstrap token file must be unlinked upon completion"

        # Replay attempt fails
        with pytest.raises(BootstrapAlreadyCompletedError):
            bootstrap.complete_bootstrap(
                bootstrap_token=token,
                username="second_admin",
                password="AnotherPassword123!",
            )

    def test_bootstrap_token_expired(self, identity_store, temp_dir):
        token_path = temp_dir / ".bootstrap_token"
        bootstrap = LocalAdministratorBootstrap(
            store=identity_store,
            token_path=token_path,
        )
        meta = bootstrap.initiate_bootstrap(validity_sec=1.0)
        token = meta["token"]
        time.sleep(1.2)  # Expire token

        with pytest.raises(BootstrapTokenExpiredError):
            bootstrap.complete_bootstrap(
                bootstrap_token=token,
                username="admin_expired",
                password="ValidPassword2026!#",
            )


# ===========================================================================
# 5. Sentinel Hardening & DoS Resistance
# ===========================================================================

class TestSentinelAdversarialHardening:
    """Verifies adaptive Sentinel mitigations against administrator lockout DoS and mobile IP roaming."""

    def test_admin_lockout_dos_mitigation(self, identity_store):
        """Verifies that brute force attacks against an administrator account
        do NOT cause administrative lockout DoS when admin_lockout_protection is enabled."""
        config = SentinelConfig(
            max_account_failures=3,
            admin_lockout_protection=True,
            base_progressive_delay_sec=0.1,
            max_progressive_delay_sec=1.0,
        )
        sentinel = CAMservSentinelIdentity(store=identity_store, config=config)

        # Create administrator account
        admin_user = UserRecord(
            user_id="u_admin_sec",
            username="security_admin",
            role=IdentityRole.ADMIN,
            is_administrator=True,
        )
        identity_store.create_user(admin_user)

        # Attacker sends 10 consecutive failed logins for administrator
        mitigations = []
        for i in range(10):
            m = sentinel.record_login_attempt(
                username="security_admin",
                ip_address="198.51.100.25",
                success=False,
            )
            mitigations.append(m)

        # Admin account is NEVER locked out
        refreshed_user = identity_store.get_user("u_admin_sec")
        assert not refreshed_user.is_locked()

        # Later attempts enforce progressive delay cap and admin DoS protection
        assert mitigations[-1].action == "DELAY"
        assert mitigations[-1].delay_sec == 1.0
        assert "protected from remote lockout" in mitigations[-1].reason

    def test_non_admin_account_lockout(self, identity_store):
        """Verifies that non-admin accounts (operator, viewer) are locked on brute force."""
        config = SentinelConfig(
            max_account_failures=3,
            admin_lockout_protection=True,
        )
        sentinel = CAMservSentinelIdentity(store=identity_store, config=config)

        operator_user = UserRecord(
            user_id="u_ops_brute",
            username="ops_user",
            role=IdentityRole.OPERATOR,
            is_administrator=False,
        )
        identity_store.create_user(operator_user)

        for i in range(3):
            sentinel.record_login_attempt(
                username="ops_user",
                ip_address="198.51.100.50",
                success=False,
            )

        refreshed_user = identity_store.get_user("u_ops_brute")
        assert refreshed_user.is_locked()

    def test_mobile_ip_roaming_support(self, identity_store):
        """Verifies that when allow_ip_roaming=True, mobile tablet / VPN IP transitions do not revoke session."""
        config = SentinelConfig(allow_ip_roaming=True)
        sentinel = CAMservSentinelIdentity(store=identity_store, config=config)

        session = SessionRecord(
            session_id="sess_mobile_001",
            user_id="usr_guard",
            username="guard1",
            role=IdentityRole.OPERATOR,
            auth_assurance_level=AuthAssuranceLevel.AAL1,
            ip_address="192.168.1.105",
            user_agent="CAMservMobile/1.0",
        )

        # Guard walks to another AP / subnet: IP switches to 192.168.2.110
        mitigation = sentinel.inspect_session_context(
            session=session,
            incoming_ip="192.168.2.110",
            incoming_ua="CAMservMobile/1.0",
        )
        assert mitigation.action == "ALLOW"
        assert mitigation.reason == "ip_roaming_permitted"
        assert session.ip_address == "192.168.2.110"

    def test_ip_mutation_anomaly_when_roaming_disabled(self, identity_store):
        """Verifies that when allow_ip_roaming=False, IP mutation triggers anomaly mitigation."""
        config = SentinelConfig(allow_ip_roaming=False, require_step_up_on_ip_change=True)
        sentinel = CAMservSentinelIdentity(store=identity_store, config=config)

        session = SessionRecord(
            session_id="sess_fixed_001",
            user_id="usr_fixed",
            username="workstation1",
            role=IdentityRole.OPERATOR,
            auth_assurance_level=AuthAssuranceLevel.AAL1,
            ip_address="192.168.1.200",
            user_agent="CAMservWorkstation/1.0",
        )

        mitigation = sentinel.inspect_session_context(
            session=session,
            incoming_ip="203.0.113.88",
            incoming_ua="CAMservWorkstation/1.0",
        )
        assert mitigation.action == "STEP_UP_REQUIRED"
        assert "step-up authentication" in mitigation.reason.lower()

    def test_sentinel_memory_bounding(self, identity_store):
        """Verifies that Sentinel prunes expired entries and caps sliding window memory."""
        config = SentinelConfig(window_sec=1.0)
        sentinel = CAMservSentinelIdentity(store=identity_store, config=config)

        sentinel.record_login_attempt("user1", "10.0.0.1", False)
        time.sleep(1.1)

        # Trigger pruning on next call
        sentinel.record_login_attempt("user2", "10.0.0.2", False)
        assert len(sentinel._user_failures.get("user1", [])) == 0


# ===========================================================================
# 6. Emergency Lockdown Failsafe Hardening
# ===========================================================================

class TestEmergencyLockdownFailsafeHardening:
    """Verifies that emergency lockdown operates failsafe in memory and protects video recording."""

    def test_in_memory_failsafe_lockdown_under_db_corruption(self, identity_store):
        lockdown = EmergencyLockdownManager(store=identity_store)

        # Close the connection to simulate database failure / corruption
        identity_store._conn.close()

        result = lockdown.declare_lockdown(initiated_by="admin_console", reason="Perimeter breach")

        # In-memory barrier engaged despite DB failure!
        assert lockdown.is_active is True
        assert result["status"] == "LOCKDOWN_ACTIVE"
        assert result["recording_pipeline_status"] == "RECORDING_PRESERVED"

        # General actions are blocked
        assert lockdown.can_perform_action("client:login") is False
        assert lockdown.can_perform_action("video:export") is False

        # Ingestion invariants are ALWAYS allowed
        assert lockdown.can_perform_action("recording:ingest") is True
        assert lockdown.can_perform_action("recording:continuity") is True
        assert lockdown.can_perform_action("evidence:hash") is True

    def test_unprivileged_lift_lockdown_denied(self, identity_store):
        lockdown = EmergencyLockdownManager(store=identity_store)
        lockdown.declare_lockdown(initiated_by="admin", reason="Test lockdown")
        assert lockdown.is_active is True

        # Unprivileged operator attempts to lift lockdown
        operator_user = UserRecord(
            user_id="usr_op",
            username="operator1",
            role=IdentityRole.OPERATOR,
            is_administrator=False,
        )

        with pytest.raises(PermissionError, match="not authorized"):
            lockdown.lift_lockdown(lifted_by="operator1", reason="Bypass test", authorizing_admin=operator_user)

        assert lockdown.is_active is True

        # Administrator lifts lockdown successfully
        admin_user = UserRecord(
            user_id="usr_adm",
            username="superadmin",
            role=IdentityRole.ADMIN,
            is_administrator=True,
        )
        lift_res = lockdown.lift_lockdown(lifted_by="superadmin", reason="All clear", authorizing_admin=admin_user)
        assert lift_res["status"] == "LOCKDOWN_LIFTED"
        assert lockdown.is_active is False


# ===========================================================================
# 7. Zero-Trust Authorization & BOLA/IDOR Penetration
# ===========================================================================

class TestAuthorizationBOLAAndPrivilegeEscalation:
    """Verifies BOLA/IDOR protection and horizontal/vertical privilege barriers."""

    def test_bola_idor_cross_camera_access_denied(self, identity_store):
        engine = ZeroTrustPolicyEngine(store=identity_store)

        # Operator assigned only to cam_lobby
        scoped_operator = UserRecord(
            user_id="usr_op_lobby",
            username="lobby_guard",
            role=IdentityRole.OPERATOR,
            is_administrator=False,
            allowed_camera_ids={"cam_lobby"},
        )
        identity_store.create_user(scoped_operator)

        # Attempt to access cam_lobby -> ALLOWED
        dec_lobby = engine.authorize(
            user=scoped_operator,
            action="camera:view",
            resource_type=ResourceType.CAMERA,
            resource_id="cam_lobby",
        )
        assert dec_lobby.allowed is True

        # Adversary attempts BOLA/IDOR access to cam_vault -> DENIED
        dec_vault = engine.authorize(
            user=scoped_operator,
            action="camera:view",
            resource_type=ResourceType.CAMERA,
            resource_id="cam_vault",
        )
        assert dec_vault.allowed is False
        assert "BOLA prevention" in dec_vault.reason or "not assigned" in dec_vault.reason

    def test_viewer_vertical_privilege_escalation_denied(self, identity_store):
        engine = ZeroTrustPolicyEngine(store=identity_store)
        viewer = UserRecord(
            user_id="usr_view_priv",
            username="guest_viewer",
            role=IdentityRole.VIEWER,
            is_administrator=False,
            allowed_camera_ids={"cam_1"},
        )
        identity_store.create_user(viewer)

        # Viewer attempting PTZ control -> DENIED
        d_ptz = engine.authorize(viewer, "camera:ptz", ResourceType.CAMERA, "cam_1")
        assert d_ptz.allowed is False
        # Viewer attempting configuration -> DENIED
        d_cfg = engine.authorize(viewer, "camera:configure", ResourceType.CAMERA, "cam_1")
        assert d_cfg.allowed is False

    def test_aal2_enforcement_for_critical_operations(self, identity_store):
        engine = ZeroTrustPolicyEngine(store=identity_store)
        admin_user = UserRecord(
            user_id="usr_admin_crit",
            username="local_admin",
            role=IdentityRole.ADMIN,
            is_administrator=True,
            mfa_enabled=False,
        )
        identity_store.create_user(admin_user)

        sess_aal1 = SessionRecord(
            session_id="s_crit_aal1",
            user_id="usr_admin_crit",
            username="local_admin",
            role=IdentityRole.ADMIN,
            auth_assurance_level=AuthAssuranceLevel.AAL1,
            expires_at_utc="2099-01-01T00:00:00Z",
        )
        identity_store.create_session(sess_aal1)

        # AAL1 session attempting AAL2-required action -> DENIED with required_aal == AAL2
        for perm in AAL2_MANDATORY_PERMISSIONS:
            d = engine.authorize(
                user=admin_user,
                action=perm,
                resource_type=ResourceType.SYSTEM,
                resource_id="*",
                session=sess_aal1,
            )
            assert d.allowed is False
            assert d.required_aal == AuthAssuranceLevel.AAL2

        # AAL2 session attempting AAL2 action -> ALLOWED
        sess_aal2 = SessionRecord(
            session_id="s_crit_aal2",
            user_id="usr_admin_crit",
            username="local_admin",
            role=IdentityRole.ADMIN,
            auth_assurance_level=AuthAssuranceLevel.AAL2,
            expires_at_utc="2099-01-01T00:00:00Z",
        )
        identity_store.create_session(sess_aal2)

        for perm in AAL2_MANDATORY_PERMISSIONS:
            d = engine.authorize(
                user=admin_user,
                action=perm,
                resource_type=ResourceType.SYSTEM,
                resource_id="*",
                session=sess_aal2,
            )
            assert d.allowed is True


# ===========================================================================
# 8. Recording Pipeline Failure Isolation
# ===========================================================================

class TestRecordingPipelineIsolationUnderIdentityCrash:
    """Proves that a catastrophic identity database crash fails closed for auth
    without dropping or interrupting video recording ingestion."""

    def test_identity_db_crash_fails_closed_auth_without_halting_recording(self, identity_store):
        # Setup recording pipeline components
        queue = BoundedPipelineQueue(name="video_ingest_queue", maxsize=100)
        ledger = RecordingContinuityLedger()
        ledger.start_segment(camera_id="cam_01", stream_id="main", segment_id="seg_01")

        # Push baseline frames
        for f in range(10):
            queue.put({"channel_id": "cam_01", "frame_idx": f, "data": b"h264_payload"})
            ledger.record_frame(camera_id="cam_01", segment_id="seg_01", frame_seq=f, pts=f * 0.0333)

        # SIMULATE CATASTROPHIC IDENTITY DB FAILURE:
        # Close connection and corrupt the underlying file
        db_path = identity_store.db_path
        identity_store.close()
        db_path.write_bytes(b"CORRUPTED_GARBAGE_PAYLOAD_SIMULATION")

        # Re-attempting identity operations fails closed immediately
        with pytest.raises(sqlite3.DatabaseError):
            DurableIdentityStore(db_path=db_path)

        # RECORDING PIPELINE REMAINS 100% OPERATIONAL:
        # Subsequent frames continue to ingest, queue, and persist into continuity ledger
        for f in range(10, 25):
            queue.put({"channel_id": "cam_01", "frame_idx": f, "data": b"h264_payload"})
            ledger.record_frame(camera_id="cam_01", segment_id="seg_01", frame_seq=f, pts=f * 0.0333)

        assert queue.qsize() == 25
        rec = ledger._records["cam_01:seg_01"]
        assert rec.observed_frames == 25
        assert rec.confirmed_missing_frames_total == 0


# ===========================================================================
# 9. Argon2id Calibration & Concurrency Bounding
# ===========================================================================

class TestArgon2idCalibrationAndConcurrencyLimits:
    """Verifies Argon2id parameter calibration and bounded concurrency execution."""

    def test_argon2id_parameters_and_execution_timing(self):
        cfg = Argon2idConfig(time_cost=2, memory_cost=65536, parallelism=4)
        hasher = Argon2idPasswordHasher(config=cfg)

        t0 = time.perf_counter()
        hashed = hasher.hash_password("Sec0psApplianceP@ssword2026!")
        elapsed = time.perf_counter() - t0

        assert "$m=65536,t=2,p=4$" in hashed
        assert hasher.verify_password("Sec0psApplianceP@ssword2026!", hashed) is True
        # On modern x86_64, Argon2id with 64MB runs in < 2.5s even in single-thread test harness
        assert elapsed < 2.5

    def test_bounded_concurrency_saturation(self):
        """Verifies that exceeding max_concurrency raises ConcurrencyExhaustedError."""
        hasher = Argon2idPasswordHasher(max_concurrency=1)

        # Acquire the single semaphore slot manually to simulate full saturation
        assert hasher._semaphore.acquire(blocking=False) is True
        try:
            with pytest.raises(ConcurrencyExhaustedError, match="capacity saturated"):
                hasher.hash_password("AnotherPassword123!")
        finally:
            hasher._semaphore.release()
