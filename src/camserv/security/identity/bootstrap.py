"""
camserv.security.identity.bootstrap
===================================

Secure, zero-default-credential first administrator bootstrap for CAMserv.
Requires physical/console access to the appliance host to retrieve a time-limited,
high-entropy, single-use bootstrap token.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog

from camserv.security.identity.models import (
    AccountStatus,
    IdentityRole,
    MFAType,
    ResourceScope,
    ResourceType,
    SecurityEvent,
    SecurityEventSeverity,
    UserRecord,
)
from camserv.security.identity.mfa import (
    MFASecretProtector,
    TOTPManager,
    generate_recovery_codes,
    hash_recovery_code,
)
from camserv.security.identity.password import (
    Argon2idPasswordHasher,
    PasswordPolicyError,
)
from camserv.security.identity.store import DurableIdentityStore

logger = structlog.get_logger(__name__)


class BootstrapError(Exception):
    """Base exception for bootstrap process failures."""


class BootstrapAlreadyCompletedError(BootstrapError):
    """Raised when bootstrap is attempted on an already initialized CAMserv installation."""


class InvalidBootstrapTokenError(BootstrapError):
    """Raised when the provided bootstrap token is incorrect or invalid."""


class BootstrapTokenExpiredError(BootstrapError):
    """Raised when the bootstrap token has expired."""


class LocalAdministratorBootstrap:
    """Manages the one-time, time-limited bootstrap for the primary local administrator."""

    def __init__(
        self,
        store: DurableIdentityStore,
        hasher: Argon2idPasswordHasher | None = None,
        totp_manager: TOTPManager | None = None,
        token_path: str | Path = "data/.bootstrap_token",
    ) -> None:
        self.store = store
        self.hasher = hasher or Argon2idPasswordHasher()
        self.totp_manager = totp_manager or TOTPManager()
        self.token_path = Path(token_path)

    def is_bootstrap_needed(self) -> bool:
        """Check whether initial administrator bootstrap is required."""
        if self.store.is_bootstrapped():
            return False
        return self.store.count_administrators() == 0

    def initiate_bootstrap(self, validity_sec: float = 900.0) -> dict[str, Any]:
        """Generate and securely persist a one-time bootstrap token on the local filesystem.

        Returns token metadata.
        """
        if not self.is_bootstrap_needed():
            raise BootstrapAlreadyCompletedError("CAMserv has already been bootstrapped with a local administrator")

        # Generate 256-bit cryptographically secure token
        token = secrets.token_hex(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=validity_sec)
        expires_at_iso = expires_at.isoformat()

        # Save to database
        self.store.store_bootstrap_token(token_hash, expires_at_iso)

        # Write to local file with restricted permissions
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.token_path, "w", encoding="utf-8") as f:
            f.write(f"{token}\n")

        try:
            os.chmod(self.token_path, 0o600)
        except Exception:
            pass

        self.store.record_security_event(
            SecurityEvent(
                event_id=uuid.uuid4().hex,
                event_type="BOOTSTRAP_TOKEN_GENERATED",
                severity=SecurityEventSeverity.WARNING,
                actor_id="system",
                ip_address="127.0.0.1",
                details={
                    "token_file": str(self.token_path),
                    "validity_sec": validity_sec,
                    "expires_at_utc": expires_at_iso,
                },
                action_taken="GENERATED_AND_PERSISTED",
            )
        )

        logger.info(
            "bootstrap_token_generated",
            token_file=str(self.token_path),
            expires_at=expires_at_iso,
        )

        return {
            "token": token,
            "token_path": str(self.token_path),
            "expires_at_utc": expires_at_iso,
        }

    def complete_bootstrap(
        self,
        bootstrap_token: str,
        username: str,
        password: str,
        full_name: str = "Local Administrator",
        email: str | None = None,
    ) -> dict[str, Any]:
        """Complete the one-time administrator bootstrap process.

        Validates the token, enforces password policy, hashes with Argon2id,
        provisions mandatory TOTP MFA and recovery codes, and deletes the token file.
        """
        if not self.is_bootstrap_needed():
            raise BootstrapAlreadyCompletedError("CAMserv has already been bootstrapped with a local administrator")

        token_data = self.store.get_bootstrap_token()
        if not token_data:
            raise InvalidBootstrapTokenError("No active bootstrap token found; run initiate_bootstrap first")

        # Verify token expiration
        now = datetime.now(timezone.utc)
        try:
            exp = datetime.fromisoformat(token_data["expires_at_utc"])
            if now > exp:
                self.store.invalidate_bootstrap_token()
                self._shred_token_file()
                raise BootstrapTokenExpiredError("Bootstrap token has expired; generate a new token via local console")
        except ValueError:
            raise InvalidBootstrapTokenError("Malformed bootstrap token expiration metadata")

        # Verify token in constant time
        candidate_hash = hashlib.sha256(bootstrap_token.strip().encode("utf-8")).hexdigest()
        if not hmac.compare_digest(candidate_hash, token_data["token_hash"]):
            self.store.record_security_event(
                SecurityEvent(
                    event_id=uuid.uuid4().hex,
                    event_type="BOOTSTRAP_FAILED_INVALID_TOKEN",
                    severity=SecurityEventSeverity.CRITICAL,
                    actor_id=username,
                    details={"reason": "token_mismatch"},
                    action_taken="REJECTED",
                )
            )
            raise InvalidBootstrapTokenError("Invalid bootstrap token")

        # Validate password policy
        valid, violations = self.hasher.validate_password(password, username)
        if not valid:
            raise PasswordPolicyError(violations)

        # Hash password using Argon2id
        password_hash = self.hasher.hash_password(password, validate_policy=False)

        user_id = f"admin_{uuid.uuid4().hex[:12]}"
        admin_user = UserRecord(
            user_id=user_id,
            username=username.strip(),
            role=IdentityRole.ADMIN,
            status=AccountStatus.ACTIVE,
            full_name=full_name.strip(),
            email=email.strip() if email else None,
            mfa_enabled=True,
            mfa_type=MFAType.TOTP,
            is_administrator=True,
            requires_password_change=False,
            allowed_camera_ids={"*"},
        )

        # Generate TOTP Secret & Recovery Codes
        totp_secret = self.totp_manager.generate_secret()
        encrypted_totp = self.totp_manager.protector.encrypt(totp_secret)
        provisioning_uri = self.totp_manager.get_provisioning_uri(username, totp_secret)

        recovery_codes = generate_recovery_codes(10)
        code_hashes = [hash_recovery_code(c) for c in recovery_codes]

        # Persist Admin User, Credentials, and Recovery Codes atomically
        self.store.create_user(admin_user, password_hash=password_hash)
        self.store.set_totp_credential(
            user_id=user_id,
            encrypted_secret=encrypted_totp,
            digits=self.totp_manager.config.digits,
            interval_sec=self.totp_manager.config.interval_sec,
            algorithm=self.totp_manager.config.algorithm,
        )
        self.store.store_recovery_codes(user_id=user_id, code_hashes=code_hashes)

        # Assign full wildcard scope
        scope = ResourceScope(
            scope_id=f"scope_{uuid.uuid4().hex[:8]}",
            user_id=user_id,
            resource_type=ResourceType.SYSTEM,
            resource_id="*",
            permissions={"*"},
            granted_by="bootstrap",
        )
        self.store.add_resource_scope(scope)

        # Finalize bootstrap in store and shred token
        self.store.set_bootstrapped(user_id)
        self.store.invalidate_bootstrap_token()
        self._shred_token_file()

        self.store.record_security_event(
            SecurityEvent(
                event_id=uuid.uuid4().hex,
                event_type="BOOTSTRAP_COMPLETED_SUCCESS",
                severity=SecurityEventSeverity.INFO,
                actor_id=user_id,
                details={"username": username, "mfa_type": "totp", "scopes": ["system:*"]},
                action_taken="ADMINISTRATOR_ENROLLED",
            )
        )

        logger.info("bootstrap_completed_successfully", admin_user_id=user_id, username=username)

        return {
            "user_id": user_id,
            "username": username,
            "totp_secret": totp_secret,
            "provisioning_uri": provisioning_uri,
            "recovery_codes": recovery_codes,
            "status": "BOOTSTRAP_COMPLETED",
        }

    def _shred_token_file(self) -> None:
        """Securely overwrite and remove the bootstrap token file."""
        if self.token_path.exists():
            try:
                size = self.token_path.stat().st_size
                with open(self.token_path, "wb") as f:
                    f.write(os.urandom(max(size, 64)))
                    f.flush()
                self.token_path.unlink()
            except Exception as exc:
                logger.warning("failed_to_shred_bootstrap_token_file", error=str(exc))
