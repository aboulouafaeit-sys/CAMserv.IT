"""
camserv.security.identity
=========================

Local-First Zero-Trust Identity, Authentication, Authorization & Account Protection.
"""

from camserv.security.identity.audit import (
    GENESIS_HASH,
    TamperEvidentSecurityAudit,
)
from camserv.security.identity.authorization import (
    AAL2_MANDATORY_PERMISSIONS,
    ROLE_BASE_PERMISSIONS,
    AuthorizationDecision,
    AuthorizationError,
    StepUpRequiredError,
    ZeroTrustPolicyEngine,
)
from camserv.security.identity.bootstrap import (
    BootstrapAlreadyCompletedError,
    BootstrapError,
    BootstrapTokenExpiredError,
    InvalidBootstrapTokenError,
    LocalAdministratorBootstrap,
)
from camserv.security.identity.emergency import (
    PERMITTED_LOCKDOWN_ACTIONS,
    EmergencyLockdownManager,
)
from camserv.security.identity.mfa import (
    InvalidMFACodeError,
    MFAError,
    MFASecretProtector,
    PasskeyChallenge,
    PasskeyManager,
    ReplayAttackError,
    TOTPConfig,
    TOTPManager,
    generate_recovery_codes,
    hash_recovery_code,
)
from camserv.security.identity.models import (
    AccountStatus,
    AuthAssuranceLevel,
    IdentityRole,
    MFAType,
    ResourceScope,
    ResourceType,
    SecurityEvent,
    SecurityEventSeverity,
    SessionRecord,
    UserRecord,
)
from camserv.security.identity.password import (
    Argon2idConfig,
    Argon2idPasswordHasher,
    ConcurrencyExhaustedError,
    PasswordPolicy,
    PasswordPolicyError,
    hash_password,
    needs_rehash,
    validate_password_policy,
    verify_password,
)
from camserv.security.identity.secrets import (
    CameraCredentialProtection,
    redact_sensitive_data,
    redact_url,
)
from camserv.security.identity.sentinel import (
    CAMservSentinelIdentity,
    SentinelConfig,
    SentinelMitigation,
)
from camserv.security.identity.session import (
    SessionError,
    SessionExpiredError,
    SessionManager,
    SessionRevokedError,
)
from camserv.security.identity.store import (
    DurableIdentityStore,
)

__all__ = [
    # Models
    "AccountStatus",
    "IdentityRole",
    "ResourceType",
    "AuthAssuranceLevel",
    "MFAType",
    "SecurityEventSeverity",
    "ResourceScope",
    "UserRecord",
    "SessionRecord",
    "SecurityEvent",
    # Password
    "Argon2idConfig",
    "PasswordPolicy",
    "Argon2idPasswordHasher",
    "hash_password",
    "verify_password",
    "needs_rehash",
    "validate_password_policy",
    "PasswordPolicyError",
    "ConcurrencyExhaustedError",
    # Store
    "DurableIdentityStore",
    # Bootstrap
    "LocalAdministratorBootstrap",
    "BootstrapError",
    "BootstrapAlreadyCompletedError",
    "InvalidBootstrapTokenError",
    "BootstrapTokenExpiredError",
    # MFA
    "TOTPConfig",
    "MFASecretProtector",
    "TOTPManager",
    "PasskeyChallenge",
    "PasskeyManager",
    "generate_recovery_codes",
    "hash_recovery_code",
    "MFAError",
    "ReplayAttackError",
    "InvalidMFACodeError",
    # Authorization
    "ZeroTrustPolicyEngine",
    "AuthorizationDecision",
    "AuthorizationError",
    "StepUpRequiredError",
    "AAL2_MANDATORY_PERMISSIONS",
    "ROLE_BASE_PERMISSIONS",
    # Session
    "SessionManager",
    "SessionError",
    "SessionExpiredError",
    "SessionRevokedError",
    # Sentinel
    "CAMservSentinelIdentity",
    "SentinelConfig",
    "SentinelMitigation",
    # Audit
    "TamperEvidentSecurityAudit",
    "GENESIS_HASH",
    # Secrets
    "CameraCredentialProtection",
    "redact_url",
    "redact_sensitive_data",
    # Emergency
    "EmergencyLockdownManager",
    "PERMITTED_LOCKDOWN_ACTIONS",
]
