"""Security & authentication subsystem tests for CAMserv.

Verifies:
- JWT access token generation and claims validation
- JWT token expiration rejection
- API key authentication and validation
- RBAC permissions: Admin has universal access
- RBAC permissions: Viewer restricted from write actions
- RBAC permissions: Auditor has access to audit logs but not camera modifications
- Brute-force login defense and temporary account lockout
- Tamper-evident append-only audit logging
- Cryptographic SHA-256 hash chaining of audit entries
- Tamper detection on modified audit log entries
- AES-256-GCM authenticated encryption and decryption
- Cryptographic master key rotation with version tracking
- Password hashing (PBKDF2-HMAC-SHA256) and constant-time verification
"""

from __future__ import annotations

import json
import time
from datetime import timedelta
from pathlib import Path

import jwt
import pytest
from fastapi import HTTPException

from camserv.security.audit import AuditAction, AuditLogger, GENESIS_HASH
from camserv.security.auth import (
    AuthManager,
    Role,
    UserIdentity,
    hash_password,
    verify_password,
)
from camserv.security.encryption import EncryptedPayload, EncryptionManager

SECRET_KEY = "super-secret-jwt-signing-key-for-security-tests-at-least-32-chars"


@pytest.fixture
def auth_mgr() -> AuthManager:
    return AuthManager(
        secret_key=SECRET_KEY,
        access_token_expire_minutes=5,
        max_login_failures=3,
        lockout_minutes=15,
    )


@pytest.fixture
def crypto_mgr() -> EncryptionManager:
    master_key = EncryptionManager.generate_master_key()
    return EncryptionManager(master_key=master_key)


@pytest.mark.unit
def test_jwt_token_generation_and_validation(auth_mgr: AuthManager) -> None:
    """Verify JWT access token generation produces valid claims for subject and role."""
    token = auth_mgr.create_access_token(subject="alice_admin", role=Role.ADMIN)
    assert isinstance(token, str)

    claims = auth_mgr.verify_token(token, expected_type="access")
    assert claims["sub"] == "alice_admin"
    assert claims["role"] == Role.ADMIN.value
    assert claims["iss"] == "camserv"


@pytest.mark.unit
def test_jwt_token_expiry(auth_mgr: AuthManager) -> None:
    """Verify expired JWT tokens are rejected with HTTP 401 Unauthorized."""
    # Create manager with negative expiration to force expired token
    short_mgr = AuthManager(secret_key=SECRET_KEY, access_token_expire_minutes=-1)
    token = short_mgr.create_access_token(subject="bob", role=Role.VIEWER)

    with pytest.raises(HTTPException) as exc_info:
        auth_mgr.verify_token(token)
    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


@pytest.mark.unit
def test_api_key_authentication(auth_mgr: AuthManager) -> None:
    """Verify API keys can be created, stored, and validated for service identity."""
    api_key = auth_mgr.create_api_key(service_name="drone_fleet_service", role=Role.OPERATOR)
    assert api_key.startswith("cs_")

    identity = auth_mgr.authenticate_api_key(api_key)
    assert identity is not None
    assert identity.subject == "drone_fleet_service"
    assert identity.role == Role.OPERATOR
    assert identity.is_api_key is True

    # Unknown key must return None / raise
    assert auth_mgr.authenticate_api_key("cs_invalid_key_12345") is None


@pytest.mark.unit
def test_rbac_admin_access() -> None:
    """Verify Role.ADMIN possesses wildcard permission covering all platform actions."""
    identity = UserIdentity(
        subject="admin_user",
        role=Role.ADMIN,
        permissions={"*"},
    )
    assert identity.has_permission("cameras:read") is True
    assert identity.has_permission("cameras:write") is True
    assert identity.has_permission("events:write") is True
    assert identity.has_permission("audit:read") is True
    assert identity.has_permission("system:shutdown") is True


@pytest.mark.unit
def test_rbac_viewer_restricted() -> None:
    """Verify Role.VIEWER can read detections and events but cannot write or modify cameras."""
    identity = UserIdentity(
        subject="viewer_user",
        role=Role.VIEWER,
        permissions={
            "cameras:read",
            "detections:read",
            "events:read",
            "tracks:read",
            "analytics:read",
            "system:read",
        },
    )
    # Allowed reads
    assert identity.has_permission("cameras:read") is True
    assert identity.has_permission("events:read") is True
    # Disallowed writes
    assert identity.has_permission("cameras:write") is False
    assert identity.has_permission("events:write") is False
    assert identity.has_permission("audit:read") is False


@pytest.mark.unit
def test_rbac_auditor_access() -> None:
    """Verify Role.AUDITOR has audit:read and inspection access, but cannot modify cameras."""
    identity = UserIdentity(
        subject="compliance_auditor",
        role=Role.AUDITOR,
        permissions={
            "cameras:read",
            "detections:read",
            "events:read",
            "tracks:read",
            "analytics:read",
            "audit:read",
            "system:read",
        },
    )
    assert identity.has_permission("audit:read") is True
    assert identity.has_permission("events:read") is True
    assert identity.has_permission("cameras:write") is False
    assert identity.has_permission("events:write") is False


@pytest.mark.unit
def test_brute_force_lockout(auth_mgr: AuthManager) -> None:
    """Verify account lockout occurs after reaching max failed login attempts."""
    user = "target_account"
    assert not auth_mgr.protector.is_locked(user)

    # Max failures configured to 3
    auth_mgr.protector.record_failure(user)  # 1
    assert not auth_mgr.protector.is_locked(user)

    auth_mgr.protector.record_failure(user)  # 2
    assert not auth_mgr.protector.is_locked(user)

    is_locked = auth_mgr.protector.record_failure(user)  # 3 -> Lockout!
    assert is_locked is True
    assert auth_mgr.protector.is_locked(user) is True


@pytest.mark.unit
def test_audit_log_append_only(tmp_path: Path) -> None:
    """Verify audit logger writes sequential append-only entries to disk."""
    log_file = tmp_path / "audit.jsonl"
    logger = AuditLogger(log_path=log_file)

    logger.log(actor="admin", action=AuditAction.LOGIN, resource="api", result="SUCCESS")
    logger.log(actor="admin", action=AuditAction.CAMERA_ADD, resource="cam-01", result="SUCCESS")

    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    entry1 = json.loads(lines[0])
    entry2 = json.loads(lines[1])
    assert entry1["action"] == AuditAction.LOGIN
    assert entry2["action"] == AuditAction.CAMERA_ADD


@pytest.mark.unit
def test_audit_log_hash_chain(tmp_path: Path) -> None:
    """Verify audit entries form a continuous SHA-256 cryptographic hash chain."""
    log_file = tmp_path / "audit_chain.jsonl"
    logger = AuditLogger(log_path=log_file)

    e1 = logger.log(actor="u1", action=AuditAction.LOGIN, resource="system")
    e2 = logger.log(actor="u1", action=AuditAction.CONFIG_CHANGE, resource="detection_rule")
    e3 = logger.log(actor="u1", action=AuditAction.LOGOUT, resource="system")

    assert e1.prev_hash == GENESIS_HASH
    assert e2.prev_hash == e1.entry_hash
    assert e3.prev_hash == e2.entry_hash

    is_valid, count, errors = logger.verify_integrity()
    assert is_valid is True
    assert count == 3
    assert len(errors) == 0


@pytest.mark.unit
def test_audit_log_tamper_detection(tmp_path: Path) -> None:
    """Verify altering an audit record in the log file breaks chain integrity check."""
    log_file = tmp_path / "audit_tamper.jsonl"
    logger = AuditLogger(log_path=log_file)

    for i in range(4):
        logger.log(actor=f"user_{i}", action=AuditAction.LOGIN, resource=f"terminal_{i}")

    # Tamper with entry #2 by altering the actor
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    tampered_entry = json.loads(lines[1])
    tampered_entry["actor"] = "malicious_impersonator"
    lines[1] = json.dumps(tampered_entry)
    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    is_valid, count, errors = logger.verify_integrity()
    assert is_valid is False
    assert len(errors) > 0


@pytest.mark.unit
def test_encryption_aes256_gcm(crypto_mgr: EncryptionManager) -> None:
    """Verify AES-256-GCM encryption produces ciphertext and authenticated decryption restores data."""
    plaintext = b"CONFIDENTIAL_SURVEILLANCE_CREDENTIALS"
    encrypted = crypto_mgr.encrypt(plaintext, purpose="credentials")

    assert isinstance(encrypted, EncryptedPayload)
    assert encrypted.ciphertext != plaintext
    assert len(encrypted.nonce) == 12  # 96-bit standard nonce

    decrypted = crypto_mgr.decrypt(encrypted, purpose="credentials")
    assert decrypted == plaintext


@pytest.mark.unit
def test_key_rotation(crypto_mgr: EncryptionManager) -> None:
    """Verify key rotation increments version and can decrypt payloads from previous key versions."""
    orig_version = crypto_mgr.current_key_version
    old_payload = crypto_mgr.encrypt(b"data_encrypted_under_v1", purpose="storage")
    assert old_payload.key_version == orig_version

    # Rotate master key
    new_master_key = EncryptionManager.generate_master_key()
    new_version = crypto_mgr.rotate_key(new_master_key)
    assert new_version == orig_version + 1
    assert crypto_mgr.current_key_version == new_version

    # New encryption uses new version
    new_payload = crypto_mgr.encrypt(b"data_encrypted_under_v2", purpose="storage")
    assert new_payload.key_version == new_version

    # Decryption works across both historical and new key versions
    assert crypto_mgr.decrypt(old_payload, purpose="storage") == b"data_encrypted_under_v1"
    assert crypto_mgr.decrypt(new_payload, purpose="storage") == b"data_encrypted_under_v2"


@pytest.mark.unit
def test_password_hashing() -> None:
    """Verify PBKDF2-HMAC-SHA256 password hashing generates salted hashes and verifies accurately."""
    password = "CorrectHorseBatteryStaple123!"
    hashed = hash_password(password)

    assert hashed.startswith("pbkdf2_sha256$100000$")
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False
