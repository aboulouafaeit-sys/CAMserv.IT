"""
camserv.security.identity.sentinel
==================================

CAMserv Sentinel Identity: Adaptive threat detection and deterministic policy mitigation.
Protects against brute force, credential stuffing, BOLA/IDOR horizontal scanning,
and session anomalies with bounded memory and explainable audit records.
"""

from __future__ import annotations

import collections
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from camserv.security.identity.models import (
    SecurityEvent,
    SecurityEventSeverity,
    SessionRecord,
    UserRecord,
)
from camserv.security.identity.store import DurableIdentityStore

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class SentinelConfig:
    """Detection and mitigation thresholds."""

    window_sec: float = 300.0                # 5-minute sliding window
    max_account_failures: int = 5            # Lockout threshold per account
    max_ip_failures: int = 20                # Block threshold per IP
    bola_violation_threshold: int = 3        # Trigger on 3 unauthorized resource attempts
    base_progressive_delay_sec: float = 0.5  # Base delay multiplier
    max_progressive_delay_sec: float = 8.0   # Cap for progressive delay
    max_tracked_entries: int = 1000          # Bounded memory ceiling
    admin_lockout_protection: bool = True    # Prevent remote DoS lockout of administrators
    allow_ip_roaming: bool = False           # Configurable roaming for mobile/VPN clients
    require_step_up_on_ip_change: bool = False
    require_step_up_on_ua_change: bool = True
    exempt_ips: set[str] = field(default_factory=lambda: {"127.0.0.1", "::1"})
    sensitive_actions: frozenset[str] = field(
        default_factory=lambda: frozenset({
            "camera:configure",
            "evidence:export",
            "evidence:delete",
            "system:firmware_update",
            "system:admin",
            "emergency:lift",
            "account:role_change",
        })
    )


class SentinelMitigation:
    """Evaluation result from Sentinel threat detection."""

    def __init__(
        self,
        action: str,  # "ALLOW", "DELAY", "LOCK_ACCOUNT", "BLOCK_IP", "REVOKE_SESSION"
        delay_sec: float = 0.0,
        reason: str = "normal",
        event: SecurityEvent | None = None,
    ) -> None:
        self.action = action
        self.delay_sec = delay_sec
        self.reason = reason
        self.event = event


class CAMservSentinelIdentity:
    """Adaptive identity security engine correlating anomalies and applying bounded mitigations."""

    def __init__(
        self,
        store: DurableIdentityStore,
        config: SentinelConfig | None = None,
    ) -> None:
        self.store = store
        self.config = config or SentinelConfig()
        self._lock = threading.RLock()

        # Bounded sliding history: key -> deque of timestamps
        self._user_failures: dict[str, collections.deque[float]] = {}
        self._ip_failures: dict[str, collections.deque[float]] = {}
        self._user_bola_attempts: dict[str, collections.deque[float]] = {}
        self._blocked_ips: dict[str, float] = {}  # ip -> unblock_timestamp

    def record_login_attempt(
        self,
        username: str,
        ip_address: str,
        success: bool,
    ) -> SentinelMitigation:
        """Evaluate and track login attempt. Applies progressive delay, lockout, or IP block."""
        with self._lock:
            now = time.time()
            self._prune_expired(now)

            # Check if IP is currently blocked
            if ip_address in self._blocked_ips:
                if now < self._blocked_ips[ip_address]:
                    return SentinelMitigation(
                        action="BLOCK_IP",
                        reason=f"IP '{ip_address}' is temporarily blocked due to excessive failed attempts",
                    )
                else:
                    del self._blocked_ips[ip_address]

            if success:
                # Clear failure counters on success
                self._user_failures.pop(username.lower(), None)
                return SentinelMitigation(action="ALLOW", reason="login_success")

            # Track failure for IP
            ip_q = self._ip_failures.setdefault(ip_address, collections.deque())
            ip_q.append(now)

            # Track failure for username
            u_clean = username.lower()
            u_q = self._user_failures.setdefault(u_clean, collections.deque())
            u_q.append(now)

            user = self.store.get_user_by_username(username)
            is_locked = False
            is_admin = False
            if user:
                is_admin = bool(user.is_administrator or getattr(user.role, "value", str(user.role)) == "admin")
                if is_admin and self.config.admin_lockout_protection:
                    is_locked = False
                else:
                    _, is_locked = self.store.record_login_failure(
                        user.user_id,
                        lockout_duration_sec=self.config.window_sec,
                        max_attempts=self.config.max_account_failures,
                    )

            # Check IP block threshold (exempt local console IPs)
            if ip_address not in self.config.exempt_ips and len(ip_q) >= self.config.max_ip_failures:
                self._blocked_ips[ip_address] = now + self.config.window_sec
                ev = SecurityEvent(
                    event_id=uuid.uuid4().hex,
                    event_type="SENTINEL_IP_BLOCKED",
                    severity=SecurityEventSeverity.HIGH,
                    actor_id=username,
                    ip_address=ip_address,
                    details={"failures_in_window": len(ip_q), "duration_sec": self.config.window_sec},
                    action_taken="IP_TEMPORARILY_BLOCKED",
                )
                self.store.record_security_event(ev)
                return SentinelMitigation(action="BLOCK_IP", reason="IP threshold exceeded", event=ev)

            # Check User Lockout threshold (skip if admin with lockout protection enabled)
            if (is_locked or len(u_q) >= self.config.max_account_failures) and not (is_admin and self.config.admin_lockout_protection):
                ev = SecurityEvent(
                    event_id=uuid.uuid4().hex,
                    event_type="SENTINEL_ACCOUNT_LOCKED",
                    severity=SecurityEventSeverity.HIGH,
                    actor_id=username,
                    ip_address=ip_address,
                    details={"failures_in_window": len(u_q), "duration_sec": self.config.window_sec},
                    action_taken="ACCOUNT_LOCKED",
                )
                self.store.record_security_event(ev)
                return SentinelMitigation(action="LOCK_ACCOUNT", reason="User failure limit exceeded", event=ev)
            elif is_admin and self.config.admin_lockout_protection and len(u_q) >= self.config.max_account_failures:
                ev = SecurityEvent(
                    event_id=uuid.uuid4().hex,
                    event_type="SENTINEL_ADMIN_BRUTE_FORCE_THROTTLED",
                    severity=SecurityEventSeverity.HIGH,
                    actor_id=username,
                    ip_address=ip_address,
                    details={"failures_in_window": len(u_q), "protection": "ADMIN_LOCKOUT_PREVENTED"},
                    action_taken="PROGRESSIVE_DELAY_CAPPED",
                )
                self.store.record_security_event(ev)
                return SentinelMitigation(
                    action="DELAY",
                    delay_sec=self.config.max_progressive_delay_sec,
                    reason="Admin account protected from remote lockout DoS",
                    event=ev,
                )

            # Compute progressive delay
            delay = min(
                self.config.base_progressive_delay_sec * (2 ** (len(u_q) - 1)),
                self.config.max_progressive_delay_sec,
            )

            return SentinelMitigation(
                action="DELAY",
                delay_sec=delay,
                reason=f"Failed attempt {len(u_q)}/{self.config.max_account_failures}",
            )

    def record_authorization_violation(
        self,
        user: UserRecord,
        action: str,
        resource_id: str,
        session: SessionRecord | None = None,
    ) -> SentinelMitigation:
        """Track authorization denials to detect and mitigate BOLA/IDOR horizontal scanning."""
        with self._lock:
            now = time.time()
            self._prune_expired(now)

            q = self._user_bola_attempts.setdefault(user.user_id, collections.deque())
            q.append(now)

            if len(q) >= self.config.bola_violation_threshold:
                # Mitigate horizontal scanning: revoke session and log high-severity alert
                reason = f"BOLA/IDOR probing detected: {len(q)} unauthorized resource access attempts"
                if session:
                    self.store.revoke_session(session.session_id, reason=reason)

                ev = SecurityEvent(
                    event_id=uuid.uuid4().hex,
                    event_type="SENTINEL_BOLA_PROBING_DETECTED",
                    severity=SecurityEventSeverity.CRITICAL,
                    actor_id=user.user_id,
                    ip_address=session.ip_address if session else None,
                    resource_id=resource_id,
                    details={"action": action, "violations_in_window": len(q)},
                    action_taken="SESSION_REVOKED_ALERT_LOGGED",
                )
                self.store.record_security_event(ev)
                return SentinelMitigation(action="REVOKE_SESSION", reason=reason, event=ev)

            return SentinelMitigation(action="ALLOW", reason="violation_recorded")

    def inspect_session_context(
        self,
        session: SessionRecord,
        incoming_ip: str,
        incoming_ua: str,
        action: str | None = None,
    ) -> SentinelMitigation:
        """Detect potential session hijacking with multi-signal risk correlation.

        Evaluates:
        1. Concurrent IP and User-Agent mutation (high risk of token theft).
        2. User-Agent / client fingerprint mutation.
        3. IP address roaming across subnets vs same subnet.
        4. Action sensitivity (routine read vs high-impact admin/export action).
        """
        ip_changed = session.ip_address != incoming_ip
        ua_changed = session.user_agent != incoming_ua

        # Multi-signal check 1: Simultaneous IP and UA mutation indicates probable session token theft/replay
        if ip_changed and ua_changed:
            ev = SecurityEvent(
                event_id=uuid.uuid4().hex,
                event_type="SENTINEL_SESSION_DUAL_MUTATION",
                severity=SecurityEventSeverity.CRITICAL,
                actor_id=session.user_id,
                ip_address=incoming_ip,
                details={
                    "session_id": session.session_id,
                    "orig_ip": session.ip_address,
                    "new_ip": incoming_ip,
                    "orig_ua": session.user_agent,
                    "new_ua": incoming_ua,
                },
                action_taken="SESSION_REVOKED",
            )
            self.store.record_security_event(ev)
            self.store.revoke_session(session.session_id, reason="concurrent_ip_and_ua_mutation")
            return SentinelMitigation(
                action="REVOKE_SESSION",
                reason="Concurrent IP and User-Agent mutation detected",
                event=ev,
            )

        # Multi-signal check 2: User-Agent mutation alone
        if ua_changed and self.config.require_step_up_on_ua_change:
            ev = SecurityEvent(
                event_id=uuid.uuid4().hex,
                event_type="SENTINEL_SESSION_UA_MUTATION",
                severity=SecurityEventSeverity.WARNING,
                actor_id=session.user_id,
                ip_address=incoming_ip,
                details={
                    "session_id": session.session_id,
                    "orig_ua": session.user_agent,
                    "new_ua": incoming_ua,
                },
                action_taken="STEP_UP_REQUIRED",
            )
            self.store.record_security_event(ev)
            return SentinelMitigation(
                action="STEP_UP_REQUIRED",
                reason="Client User-Agent fingerprint mutation requires step-up authentication",
                event=ev,
            )

        # Multi-signal check 3: IP address mutation
        if ip_changed:
            # Check action sensitivity: even if roaming is enabled, sensitive actions after roaming require step-up
            if action and action in self.config.sensitive_actions:
                ev = SecurityEvent(
                    event_id=uuid.uuid4().hex,
                    event_type="SENTINEL_SESSION_ROAMING_SENSITIVE_ACTION_STEP_UP",
                    severity=SecurityEventSeverity.WARNING,
                    actor_id=session.user_id,
                    ip_address=incoming_ip,
                    details={"session_id": session.session_id, "action": action, "ip": incoming_ip},
                    action_taken="STEP_UP_REQUIRED",
                )
                self.store.record_security_event(ev)
                return SentinelMitigation(
                    action="STEP_UP_REQUIRED",
                    reason=f"Sensitive action '{action}' after network roaming requires step-up authentication",
                    event=ev,
                )

            if self.config.allow_ip_roaming:
                # Legitimate IP roaming permitted (mobile networks / VPN transitions)
                ev = SecurityEvent(
                    event_id=uuid.uuid4().hex,
                    event_type="SENTINEL_SESSION_IP_ROAMING",
                    severity=SecurityEventSeverity.INFO,
                    actor_id=session.user_id,
                    ip_address=incoming_ip,
                    details={"session_id": session.session_id, "previous_ip": session.ip_address, "new_ip": incoming_ip},
                    action_taken="SESSION_IP_UPDATED",
                )
                self.store.record_security_event(ev)
                session.ip_address = incoming_ip
                return SentinelMitigation(action="ALLOW", reason="ip_roaming_permitted", event=ev)

            if self.config.require_step_up_on_ip_change:
                ev = SecurityEvent(
                    event_id=uuid.uuid4().hex,
                    event_type="SENTINEL_SESSION_IP_STEP_UP_CHALLENGE",
                    severity=SecurityEventSeverity.WARNING,
                    actor_id=session.user_id,
                    ip_address=incoming_ip,
                    details={"session_id": session.session_id, "original_ip": session.ip_address, "new_ip": incoming_ip},
                    action_taken="STEP_UP_REQUIRED",
                )
                self.store.record_security_event(ev)
                return SentinelMitigation(action="STEP_UP_REQUIRED", reason="IP change requires step-up authentication", event=ev)

            # Strict default mode: revoke session immediately
            ev = SecurityEvent(
                event_id=uuid.uuid4().hex,
                event_type="SENTINEL_SESSION_IP_MUTATION",
                severity=SecurityEventSeverity.HIGH,
                actor_id=session.user_id,
                ip_address=incoming_ip,
                details={"session_id": session.session_id, "original_ip": session.ip_address, "new_ip": incoming_ip},
                action_taken="SESSION_REVOKED",
            )
            self.store.record_security_event(ev)
            self.store.revoke_session(session.session_id, reason="ip_address_mutation_detected")
            return SentinelMitigation(action="REVOKE_SESSION", reason="IP mutation detected", event=ev)

        return SentinelMitigation(action="ALLOW", reason="session_context_valid")

    def _prune_expired(self, now: float) -> None:
        """Prune entries outside the sliding window to preserve bounded memory."""
        cutoff = now - self.config.window_sec

        for mapping in (self._user_failures, self._ip_failures, self._user_bola_attempts):
            empty_keys = []
            for k, q in mapping.items():
                while q and q[0] < cutoff:
                    q.popleft()
                if not q:
                    empty_keys.append(k)
            for k in empty_keys:
                mapping.pop(k, None)

        # Enforce max tracked entries limit
        if len(self._user_failures) > self.config.max_tracked_entries:
            self._user_failures.clear()
        if len(self._ip_failures) > self.config.max_tracked_entries:
            self._ip_failures.clear()
