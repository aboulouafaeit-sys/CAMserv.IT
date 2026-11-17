"""Authentication, authorization (RBAC), and session management.

Provides :class:`AuthManager`:
  * JWT access and refresh token issuance & verification.
  * Service-to-service API key authentication.
  * Cryptographic password hashing (Argon2 / PBKDF2-HMAC-SHA256).
  * Role-Based Access Control (RBAC) with role hierarchy and granular permissions.
  * Brute force defense: automatic temporary lockout after repeated failures.
  * Per-identity sliding window rate limiting.
  * Role & permission verification decorators / dependencies for FastAPI.
"""

from __future__ import annotations

import enum
import functools
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import jwt
import structlog
from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, SecurityScopes

logger = structlog.get_logger(__name__)

# Re-use HTTPBearer for FastAPI OpenAPI integration
bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Roles & Permissions
# ---------------------------------------------------------------------------

class Role(str, enum.Enum):
    """User roles for CAMserv RBAC."""

    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"
    AUDITOR = "auditor"


ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.ADMIN: {"*"},
    Role.OPERATOR: {
        "cameras:read",
        "cameras:write",
        "detections:read",
        "events:read",
        "events:write",
        "tracks:read",
        "alerts:read",
        "alerts:write",
        "analytics:read",
        "system:read",
    },
    Role.VIEWER: {
        "cameras:read",
        "detections:read",
        "events:read",
        "tracks:read",
        "analytics:read",
        "system:read",
    },
    Role.AUDITOR: {
        "cameras:read",
        "detections:read",
        "events:read",
        "tracks:read",
        "analytics:read",
        "audit:read",
        "system:read",
    },
}


@dataclass(slots=True)
class UserIdentity:
    """Authenticated caller identity."""

    subject: str  # username or service name
    role: Role
    permissions: set[str]
    is_api_key: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def has_permission(self, permission: str) -> bool:
        """Check if identity possesses required permission."""
        if "*" in self.permissions or f"{self.role.value}:*" in self.permissions:
            return True
        if permission in self.permissions:
            return True
        # Wildcard prefix check e.g. "cameras:*"
        domain = permission.split(":")[0] + ":*"
        return domain in self.permissions

    @property
    def user_id(self) -> str:
        """Alias user_id to subject for identity compatibility."""
        return self.subject


# ---------------------------------------------------------------------------
# Password Hashing Utilities
# ---------------------------------------------------------------------------

def hash_password(password: str, salt: bytes | None = None) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with 100,000 iterations.

    Format: `pbkdf2_sha256$100000$<hex_salt>$<hex_hash>`
    """
    if salt is None:
        salt = secrets.token_bytes(16)
    iterations = 100_000
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${derived.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time password hash verification supporting RFC 9106 Argon2id and PBKDF2."""
    if hashed.startswith("$argon2id$"):
        try:
            from camserv.security.identity.password import verify_password as v_argon2id
            return v_argon2id(password, hashed)
        except Exception:
            return False
    try:
        parts = hashed.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected = bytes.fromhex(parts[3])
        derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(derived, expected)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Rate Limiting & Lockout Trackers
# ---------------------------------------------------------------------------

class BruteForceProtector:
    """Tracks failed login attempts and enforces temporary account lockout."""

    def __init__(self, max_failures: int = 5, lockout_seconds: int = 900) -> None:
        self.max_failures = max_failures
        self.lockout_seconds = lockout_seconds
        # key -> (failure_count, lockout_until_timestamp)
        self._failures: dict[str, tuple[int, float]] = {}

    def is_locked(self, key: str) -> bool:
        """Check if key is currently locked out."""
        entry = self._failures.get(key)
        if not entry:
            return False
        count, lockout_until = entry
        if time.time() < lockout_until:
            return True
        # Lockout expired
        if count >= self.max_failures:
            del self._failures[key]
        return False

    def record_failure(self, key: str) -> bool:
        """Record a failure. Returns True if now locked out."""
        now = time.time()
        count, lockout_until = self._failures.get(key, (0, 0.0))
        count += 1
        if count >= self.max_failures:
            lockout_until = now + self.lockout_seconds
            self._failures[key] = (count, lockout_until)
            logger.warning("auth.brute_force_lockout", key=key, duration_s=self.lockout_seconds)
            return True
        self._failures[key] = (count, 0.0)
        return False

    def record_success(self, key: str) -> None:
        """Reset failures upon successful login."""
        self._failures.pop(key, None)


class RateLimiter:
    """Sliding-window request rate limiter per identifier."""

    def __init__(self, limit_per_minute: int = 300) -> None:
        self.limit = limit_per_minute
        # key -> list of timestamp floats
        self._history: dict[str, list[float]] = {}

    def check_rate_limit(self, key: str) -> bool:
        """Returns True if within rate limit, False if exceeded."""
        now = time.time()
        window_start = now - 60.0
        timestamps = self._history.get(key, [])
        # Prune old
        valid = [t for t in timestamps if t > window_start]
        if len(valid) >= self.limit:
            self._history[key] = valid
            return False
        valid.append(now)
        self._history[key] = valid
        return True


# ---------------------------------------------------------------------------
# AuthManager
# ---------------------------------------------------------------------------

class AuthManager:
    """Enterprise authentication and authorization manager for CAMserv."""

    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        access_token_expire_minutes: int = 30,
        refresh_token_expire_days: int = 7,
        issuer: str = "camserv",
        max_login_failures: int = 5,
        lockout_minutes: int = 15,
        rate_limit_rpm: int = 300,
    ) -> None:
        if len(secret_key) < 32:
            raise ValueError("JWT secret key must be at least 32 characters")
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.access_expire = timedelta(minutes=access_token_expire_minutes)
        self.refresh_expire = timedelta(days=refresh_token_expire_days)
        self.issuer = issuer

        # In-memory user store for demo/standalone operation: username -> (hash, Role)
        self._users: dict[str, tuple[str, Role]] = {}
        # In-memory API keys: api_key -> (service_name, Role)
        self._api_keys: dict[str, tuple[str, Role]] = {}
        # Active sessions: session_id -> {sub, role, created_at, last_active}
        self._sessions: dict[str, dict[str, Any]] = {}

        self.protector = BruteForceProtector(
            max_failures=max_login_failures,
            lockout_seconds=lockout_minutes * 60,
        )
        self.rate_limiter = RateLimiter(limit_per_minute=rate_limit_rpm)

    # ---------------------------------------------------------------------------
    # User & Key Registration
    # ---------------------------------------------------------------------------

    def add_user(self, username: str, password_hash: str, role: Role) -> None:
        """Register or update a user."""
        self._users[username] = (password_hash, role)

    def create_api_key(self, service_name: str, role: Role) -> str:
        """Generate a cryptographically random API key for a service."""
        key = f"cs_{secrets.token_urlsafe(32)}"
        self._api_keys[key] = (service_name, role)
        logger.info("auth.api_key_created", service=service_name, role=role.value)
        return key

    # ---------------------------------------------------------------------------
    # Token Generation & Validation
    # ---------------------------------------------------------------------------

    def create_access_token(
        self,
        subject: str,
        role: Role | str,
        additional_claims: dict[str, Any] | None = None,
    ) -> str:
        """Generate a signed JWT access token."""
        now = datetime.now(timezone.utc)
        role_str = role.value if hasattr(role, "value") else str(role)
        payload: dict[str, Any] = {
            "iss": self.issuer,
            "sub": subject,
            "role": role_str,
            "type": "access",
            "iat": now,
            "exp": now + self.access_expire,
            "jti": secrets.token_hex(16),
        }
        if additional_claims:
            payload.update(additional_claims)
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def create_refresh_token(self, subject: str, role: Role) -> str:
        """Generate a long-lived JWT refresh token."""
        now = datetime.now(timezone.utc)
        payload = {
            "iss": self.issuer,
            "sub": subject,
            "role": role.value,
            "type": "refresh",
            "iat": now,
            "exp": now + self.refresh_expire,
            "jti": secrets.token_hex(16),
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def verify_token(self, token: str, expected_type: str = "access") -> dict[str, Any]:
        """Decode and validate JWT token claims."""
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                issuer=self.issuer,
            )
            token_type = payload.get("type")
            if token_type != expected_type:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid token type: expected {expected_type}, got {token_type}",
                )
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token signature has expired",
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Token validation failed: {str(exc)}",
            )

    # ---------------------------------------------------------------------------
    # Credential Authentication
    # ---------------------------------------------------------------------------

    def authenticate_credentials(self, username: str, password: str) -> UserIdentity | None:
        """Verify user credentials with brute-force lockout protection."""
        if self.protector.is_locked(username):
            logger.warning("auth.login_attempt_locked", username=username)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Account temporarily locked due to repeated authentication failures.",
            )

        user_data = self._users.get(username)
        if not user_data:
            self.protector.record_failure(username)
            return None

        pwd_hash, role = user_data
        if not verify_password(password, pwd_hash):
            locked = self.protector.record_failure(username)
            if locked:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Account locked due to too many failed attempts.",
                )
            return None

        self.protector.record_success(username)
        permissions = ROLE_PERMISSIONS.get(role, set())
        return UserIdentity(subject=username, role=role, permissions=permissions)

    def authenticate_api_key(self, api_key: str) -> UserIdentity | None:
        """Authenticate service-to-service API key."""
        entry = self._api_keys.get(api_key)
        if not entry:
            return None
        service_name, role = entry
        permissions = ROLE_PERMISSIONS.get(role, set())
        return UserIdentity(
            subject=service_name,
            role=role,
            permissions=permissions,
            is_api_key=True,
        )

    # ---------------------------------------------------------------------------
    # Session Management
    # ---------------------------------------------------------------------------

    def create_session(self, identity: UserIdentity) -> str:
        """Create a trackable session ID."""
        session_id = secrets.token_urlsafe(32)
        now = time.time()
        self._sessions[session_id] = {
            "sub": identity.subject,
            "role": identity.role.value,
            "created_at": now,
            "last_active": now,
        }
        return session_id

    def terminate_session(self, session_id: str) -> bool:
        """Terminate an active session."""
        return self._sessions.pop(session_id, None) is not None

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get session data and update last_active."""
        sess = self._sessions.get(session_id)
        if sess:
            sess["last_active"] = time.time()
        return sess

    # ---------------------------------------------------------------------------
    # FastAPI Authentication Dependency
    # ---------------------------------------------------------------------------

    async def get_current_user(
        self,
        creds: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    ) -> UserIdentity:
        """FastAPI dependency: resolves caller identity from Bearer token or API key."""
        if not creds:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication credentials were not provided",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = creds.credentials

        # First check API key prefix "cs_"
        if token.startswith("cs_"):
            identity = self.authenticate_api_key(token)
            if not identity:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid API key",
                )
        else:
            payload = self.verify_token(token, expected_type="access")
            sub = payload.get("sub", "unknown")
            role_str = payload.get("role", Role.VIEWER.value)
            role = Role(role_str) if role_str in Role._value2member_map_ else Role.VIEWER
            permissions = ROLE_PERMISSIONS.get(role, set())
            identity = UserIdentity(subject=sub, role=role, permissions=permissions)

        # Enforce rate limiting per identity
        if not self.rate_limiter.check_rate_limit(identity.subject):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please slow down your requests.",
            )

        return identity


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> UserIdentity:
    """FastAPI dependency: resolves caller identity from app.state.auth_manager."""
    auth_manager: AuthManager = getattr(request.app.state, "auth_manager")
    return await auth_manager.get_current_user(creds)


# ---------------------------------------------------------------------------
# RBAC Decorators & Dependencies
# ---------------------------------------------------------------------------

def require_role(*allowed_roles: Role) -> Callable[..., Any]:
    """Dependency factory checking that caller has at least one of the allowed roles."""

    def _role_checker(identity: UserIdentity = Depends(get_current_user)) -> UserIdentity:
        if identity.role not in allowed_roles and identity.role != Role.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires one of roles: {[r.value for r in allowed_roles]}",
            )
        return identity

    return _role_checker


def require_permission(permission: str) -> Callable[..., Any]:
    """Dependency factory checking that caller has specific permission."""

    def _permission_checker(identity: UserIdentity = Depends(get_current_user)) -> UserIdentity:
        if not identity.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires permission: '{permission}'",
            )
        return identity

    return _permission_checker
