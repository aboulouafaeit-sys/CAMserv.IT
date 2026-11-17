"""
camserv.security.identity.models
================================

Core data models, enums, and interfaces for CAMserv Local-First Zero-Trust Identity,
Authentication, Authorization & Account Protection.
"""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


class AccountStatus(str, enum.Enum):
    """Lifecycle status of a local CAMserv user account."""

    PENDING_BOOTSTRAP = "pending_bootstrap"
    PENDING_ACTIVATION = "pending_activation"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    LOCKED = "locked"
    DEACTIVATED = "deactivated"


class IdentityRole(str, enum.Enum):
    """Primary local role categories."""

    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"
    AUDITOR = "auditor"


class ResourceType(str, enum.Enum):
    """Protected resource categories in CAMserv surveillance operations."""

    CAMERA = "camera"
    STREAM = "stream"
    RECORDING = "recording"
    EVENT = "event"
    EVIDENCE = "evidence"
    EXPORT = "export"
    STORAGE = "storage"
    CONFIG = "config"
    AUDIT = "audit"
    SESSION = "session"
    ACCOUNT = "account"
    SYSTEM = "system"


class AuthAssuranceLevel(str, enum.Enum):
    """Authentication Assurance Level (AAL) following NIST SP 800-63B."""

    AAL1 = "aal1"  # Single-factor (Password only)
    AAL2 = "aal2"  # Multi-factor (Password + TOTP / Recovery Code)
    AAL3 = "aal3"  # Cryptographic hardware key / WebAuthn Passkey


class MFAType(str, enum.Enum):
    """Supported local multi-factor authentication methods."""

    NONE = "none"
    TOTP = "totp"
    PASSKEY = "passkey"
    RECOVERY_CODE = "recovery_code"


class SecurityEventSeverity(str, enum.Enum):
    """Severity classification for Sentinel security events."""

    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(slots=True)
class ResourceScope:
    """Explicit resource assignment scope granting a user access to a specific asset."""

    scope_id: str
    user_id: str
    resource_type: ResourceType
    resource_id: str  # Specific ID (e.g. "cam_front_01") or "*" for wildcard admin scope
    permissions: set[str]  # e.g. {"camera:view", "camera:ptz", "recording:playback"}
    granted_by: str
    granted_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope_id": self.scope_id,
            "user_id": self.user_id,
            "resource_type": self.resource_type.value,
            "resource_id": self.resource_id,
            "permissions": list(self.permissions),
            "granted_by": self.granted_by,
            "granted_at_utc": self.granted_at_utc,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResourceScope:
        return cls(
            scope_id=data["scope_id"],
            user_id=data["user_id"],
            resource_type=ResourceType(data["resource_type"]),
            resource_id=data["resource_id"],
            permissions=set(data.get("permissions", [])),
            granted_by=data.get("granted_by", "system"),
            granted_at_utc=data.get("granted_at_utc", datetime.now(timezone.utc).isoformat()),
        )


@dataclass(slots=True)
class UserRecord:
    """Local user account record representing an Administrator or Individual Client."""

    user_id: str
    username: str
    role: IdentityRole
    status: AccountStatus = AccountStatus.ACTIVE
    full_name: str = ""
    email: str | None = None
    mfa_enabled: bool = False
    mfa_type: MFAType = MFAType.NONE
    created_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_login_utc: str | None = None
    failed_login_count: int = 0
    locked_until_utc: str | None = None
    is_administrator: bool = False
    requires_password_change: bool = False
    allowed_camera_ids: set[str] = field(default_factory=set)

    def is_locked(self) -> bool:
        """Check if account is currently locked out."""
        if self.status == AccountStatus.LOCKED:
            return True
        if self.locked_until_utc:
            try:
                lockout_end = datetime.fromisoformat(self.locked_until_utc)
                if datetime.now(timezone.utc) < lockout_end:
                    return True
            except Exception:
                return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role.value,
            "status": self.status.value,
            "full_name": self.full_name,
            "email": self.email,
            "mfa_enabled": self.mfa_enabled,
            "mfa_type": self.mfa_type.value,
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "last_login_utc": self.last_login_utc,
            "failed_login_count": self.failed_login_count,
            "locked_until_utc": self.locked_until_utc,
            "is_administrator": self.is_administrator,
            "requires_password_change": self.requires_password_change,
            "allowed_camera_ids": list(self.allowed_camera_ids),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserRecord:
        return cls(
            user_id=data["user_id"],
            username=data["username"],
            role=IdentityRole(data["role"]),
            status=AccountStatus(data.get("status", AccountStatus.ACTIVE.value)),
            full_name=data.get("full_name", ""),
            email=data.get("email"),
            mfa_enabled=bool(data.get("mfa_enabled", False)),
            mfa_type=MFAType(data.get("mfa_type", MFAType.NONE.value)),
            created_at_utc=data.get("created_at_utc", datetime.now(timezone.utc).isoformat()),
            updated_at_utc=data.get("updated_at_utc", datetime.now(timezone.utc).isoformat()),
            last_login_utc=data.get("last_login_utc"),
            failed_login_count=int(data.get("failed_login_count", 0)),
            locked_until_utc=data.get("locked_until_utc"),
            is_administrator=bool(data.get("is_administrator", False)),
            requires_password_change=bool(data.get("requires_password_change", False)),
            allowed_camera_ids=set(data.get("allowed_camera_ids", [])),
        )


@dataclass(slots=True)
class SessionRecord:
    """Stateful, revocable local user session."""

    session_id: str
    user_id: str
    username: str
    role: IdentityRole
    auth_assurance_level: AuthAssuranceLevel
    created_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_activity_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at_utc: str = ""
    ip_address: str = "127.0.0.1"
    user_agent: str = "local_client"
    is_revoked: bool = False
    revocation_reason: str | None = None
    step_up_confirmed_at_utc: str | None = None

    def is_active(self, idle_timeout_sec: float = 1800.0, absolute_timeout_sec: float = 43200.0) -> bool:
        """Evaluate session validity against revocation, idle timeout, and absolute expiration."""
        if self.is_revoked:
            return False
        now = datetime.now(timezone.utc)
        try:
            # Check absolute expiration
            if self.expires_at_utc:
                exp = datetime.fromisoformat(self.expires_at_utc)
                if now > exp:
                    return False
            # Check idle timeout
            if self.last_activity_utc:
                last_act = datetime.fromisoformat(self.last_activity_utc)
                if (now - last_act).total_seconds() > idle_timeout_sec:
                    return False
            # Check absolute lifetime from creation
            created = datetime.fromisoformat(self.created_at_utc)
            if (now - created).total_seconds() > absolute_timeout_sec:
                return False
        except Exception:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionRecord:
        return cls(
            session_id=data["session_id"],
            user_id=data["user_id"],
            username=data["username"],
            role=IdentityRole(data["role"]),
            auth_assurance_level=AuthAssuranceLevel(data["auth_assurance_level"]),
            created_at_utc=data.get("created_at_utc", datetime.now(timezone.utc).isoformat()),
            last_activity_utc=data.get("last_activity_utc", datetime.now(timezone.utc).isoformat()),
            expires_at_utc=data.get("expires_at_utc", ""),
            ip_address=data.get("ip_address", "127.0.0.1"),
            user_agent=data.get("user_agent", "local_client"),
            is_revoked=bool(data.get("is_revoked", False)),
            revocation_reason=data.get("revocation_reason"),
            step_up_confirmed_at_utc=data.get("step_up_confirmed_at_utc"),
        )


@dataclass(slots=True)
class SecurityEvent:
    """Auditable security incident or anomaly detected by CAMserv Sentinel."""

    event_id: str
    event_type: str
    severity: SecurityEventSeverity
    timestamp_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    actor_id: str | None = None
    ip_address: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    action_taken: str = "LOGGED"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecurityEvent:
        return cls(
            event_id=data["event_id"],
            event_type=data["event_type"],
            severity=SecurityEventSeverity(data.get("severity", SecurityEventSeverity.INFO.value)),
            timestamp_utc=data.get("timestamp_utc", datetime.now(timezone.utc).isoformat()),
            actor_id=data.get("actor_id"),
            ip_address=data.get("ip_address"),
            resource_type=data.get("resource_type"),
            resource_id=data.get("resource_id"),
            details=data.get("details", {}),
            action_taken=data.get("action_taken", "LOGGED"),
        )
