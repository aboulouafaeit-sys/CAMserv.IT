"""
camserv.security.identity.session
=================================

Stateful, revocable, rotatable local session management for CAMserv.
Provides session fixation resistance, idle and absolute timeout enforcement,
concurrency limits, and step-up elevation.
"""

from __future__ import annotations

import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from camserv.security.identity.models import (
    AuthAssuranceLevel,
    IdentityRole,
    SecurityEvent,
    SecurityEventSeverity,
    SessionRecord,
    UserRecord,
)
from camserv.security.identity.store import DurableIdentityStore

logger = structlog.get_logger(__name__)


class SessionError(Exception):
    """Base exception for session management failures."""


class SessionExpiredError(SessionError):
    """Raised when an operation is attempted on an expired session."""


class SessionRevokedError(SessionError):
    """Raised when an operation is attempted on a revoked session."""


class SessionManager:
    """Manages stateful local client sessions with proactive timeouts and fixation defense."""

    def __init__(
        self,
        store: DurableIdentityStore,
        idle_timeout_sec: float = 1800.0,      # 30 minutes
        absolute_timeout_sec: float = 43200.0,  # 12 hours
        max_concurrent_sessions: int = 5,
        lockdown_manager: Any | None = None,
    ) -> None:
        self.store = store
        self.idle_timeout_sec = idle_timeout_sec
        self.absolute_timeout_sec = absolute_timeout_sec
        self.max_concurrent_sessions = max_concurrent_sessions
        self.lockdown_manager = lockdown_manager
        self._lock = threading.RLock()

    def set_lockdown_manager(self, lockdown_manager: Any) -> None:
        """Dynamically bind emergency lockdown manager."""
        self.lockdown_manager = lockdown_manager

    def create_session(
        self,
        user: UserRecord,
        auth_assurance_level: AuthAssuranceLevel = AuthAssuranceLevel.AAL1,
        ip_address: str = "127.0.0.1",
        user_agent: str = "local_client",
    ) -> SessionRecord:
        """Create a new session, enforcing concurrent session limits and lockdown barriers."""
        with self._lock:
            # Emergency lockdown check: non-admin logins blocked
            if self.lockdown_manager and self.lockdown_manager.is_active:
                role_str = getattr(user.role, "value", str(user.role))
                if role_str != "admin" and not user.is_administrator:
                    raise SessionError("Cannot create client session: emergency appliance lockdown is active")

            # Enforce max concurrent sessions by revoking oldest if limit exceeded
            active_sessions = self.store.list_active_sessions_for_user(user.user_id)
            if len(active_sessions) >= self.max_concurrent_sessions:
                # Active sessions sorted newest to oldest; revoke from the end
                for old_sess in active_sessions[self.max_concurrent_sessions - 1 :]:
                    self.store.revoke_session(old_sess.session_id, reason="concurrent_limit_exceeded")

            session_id = f"sess_{secrets.token_hex(24)}"
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=self.absolute_timeout_sec)

            session = SessionRecord(
                session_id=session_id,
                user_id=user.user_id,
                username=user.username,
                role=user.role,
                auth_assurance_level=auth_assurance_level,
                created_at_utc=now.isoformat(),
                last_activity_utc=now.isoformat(),
                expires_at_utc=expires_at.isoformat(),
                ip_address=ip_address,
                user_agent=user_agent,
                is_revoked=False,
            )

            self.store.create_session(session)
            return session

    def validate_and_touch(self, session_id: str) -> SessionRecord:
        """Validate session state against revocation, idle timeout, and absolute expiration.

        Refreshes last_activity_utc if valid.
        """
        session = self.store.get_session(session_id)
        if not session:
            raise SessionRevokedError("Session not found or has been purged")

        if session.is_revoked:
            raise SessionRevokedError(f"Session has been revoked: {session.revocation_reason or 'unspecified'}")

        # Emergency appliance lockdown check
        if self.lockdown_manager and self.lockdown_manager.is_active:
            role_str = getattr(session.role, "value", str(session.role))
            if role_str != "admin":
                raise SessionRevokedError("Emergency appliance lockdown active: client sessions suspended")

        if not session.is_active(
            idle_timeout_sec=self.idle_timeout_sec,
            absolute_timeout_sec=self.absolute_timeout_sec,
        ):
            # Mark session as revoked due to timeout
            self.store.revoke_session(session_id, reason="session_timeout")
            raise SessionExpiredError("Session has expired due to inactivity or absolute lifetime")

        # Update last activity timestamp
        self.store.touch_session(session_id)
        session.last_activity_utc = datetime.now(timezone.utc).isoformat()
        return session

    def rotate_session(
        self,
        old_session_id: str,
        user: UserRecord,
        new_aal: AuthAssuranceLevel | None = None,
        reason: str = "privilege_elevation_or_rotation",
    ) -> SessionRecord:
        """Session fixation defense: atomically revoke old session and issue a fresh session."""
        with self._lock:
            old_session = self.store.get_session(old_session_id)
            ip_address = old_session.ip_address if old_session else "127.0.0.1"
            user_agent = old_session.user_agent if old_session else "local_client"
            aal = new_aal or (old_session.auth_assurance_level if old_session else AuthAssuranceLevel.AAL1)

            # Revoke old session
            if old_session:
                self.store.revoke_session(old_session_id, reason=reason)

            # Create new session
            new_session = self.create_session(
                user=user,
                auth_assurance_level=aal,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return new_session

    def step_up_session(
        self,
        session_id: str,
        user: UserRecord,
        new_aal: AuthAssuranceLevel = AuthAssuranceLevel.AAL2,
    ) -> SessionRecord:
        """Elevate an existing session's assurance level with session rotation."""
        return self.rotate_session(
            old_session_id=session_id,
            user=user,
            new_aal=new_aal,
            reason="step_up_authentication",
        )

    def revoke_session(self, session_id: str, reason: str = "user_logout") -> bool:
        """Revoke a specific session immediately."""
        return self.store.revoke_session(session_id, reason=reason)

    def revoke_all_sessions(self, user_id: str, reason: str = "security_reset") -> int:
        """Revoke all active sessions for a user."""
        return self.store.revoke_all_user_sessions(user_id, reason=reason)
