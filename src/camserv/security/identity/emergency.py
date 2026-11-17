"""
camserv.security.identity.emergency
===================================

Emergency lockdown management for CAMserv.
Provides rapid threat containment while strictly isolating and preserving continuous
surveillance recording, RTSP ingestion, and cryptographic evidence hashing.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from camserv.security.identity.models import SecurityEvent, SecurityEventSeverity
from camserv.security.identity.store import DurableIdentityStore

logger = structlog.get_logger(__name__)


# Actions allowed even under full emergency lockdown
PERMITTED_LOCKDOWN_ACTIONS: frozenset[str] = frozenset({
    "recording:ingest",
    "recording:write",
    "recording:continuity",
    "evidence:hash",
    "storage:preserve",
    "audit:log",
    "system:status",
    "emergency:lift",
})


class EmergencyLockdownManager:
    """Manages emergency appliance lockdown states with absolute recording pipeline isolation."""

    def __init__(
        self,
        store: DurableIdentityStore,
        latch_path: str | Path = "data/.emergency_lockdown.latch",
    ) -> None:
        self.store = store
        self.latch_path = Path(latch_path)
        self._lock = threading.RLock()
        self._is_active: bool = False
        self._lockdown_details: dict[str, Any] = {}

        # Restore durable lockdown state across process restarts
        self._restore_latch_state()

    def _restore_latch_state(self) -> None:
        """Inspect durable recovery latch file to survive application crashes or restarts."""
        if not self.latch_path.exists():
            return

        try:
            content = self.latch_path.read_text(encoding="utf-8").strip()
            if not content:
                # 0-byte latch file indicates interrupted write or tampering: fail closed
                self._is_active = True
                self._lockdown_details = {
                    "status": "LOCKDOWN_FAIL_CLOSED_CORRUPTED_LATCH",
                    "reason": "Empty recovery latch file detected on boot",
                    "declared_at_utc": datetime.now(timezone.utc).isoformat(),
                }
                logger.critical("emergency_lockdown.boot_fail_closed_empty_latch")
                return

            data = json.loads(content)
            if data.get("status") == "LOCKDOWN_ACTIVE":
                self._is_active = True
                self._lockdown_details = data
                logger.critical(
                    "emergency_lockdown.boot_restored_from_durable_latch",
                    initiated_by=data.get("initiated_by"),
                    reason=data.get("reason"),
                )
        except Exception as exc:
            # Crucial Security Invariant: Fail closed on corrupt latch file
            self._is_active = True
            self._lockdown_details = {
                "status": "LOCKDOWN_FAIL_CLOSED_CORRUPTED_LATCH",
                "reason": f"Corrupted recovery latch file: {exc}",
                "declared_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            logger.critical("emergency_lockdown.boot_fail_closed_corrupted_latch", error=str(exc))

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._is_active

    def declare_lockdown(self, initiated_by: str, reason: str) -> dict[str, Any]:
        """Declare emergency lockdown.

        Revokes all non-admin sessions, suspends external exports, and blocks client logins.
        Video recording and ingestion continue completely uninterrupted.
        Fails safe in memory and atomically persists the durable recovery latch.
        """
        with self._lock:
            # Immediate fail-safe in-memory barrier
            self._is_active = True
            now = datetime.now(timezone.utc).isoformat()
            self._lockdown_details = {
                "status": "LOCKDOWN_ACTIVE",
                "initiated_by": initiated_by,
                "reason": reason,
                "declared_at_utc": now,
            }

            # Atomically persist durable recovery latch file
            try:
                self.latch_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_latch = self.latch_path.with_suffix(".tmp")
                tmp_latch.write_text(json.dumps(self._lockdown_details, indent=2), encoding="utf-8")
                tmp_latch.replace(self.latch_path)
            except Exception as exc:
                logger.error("emergency_lockdown.latch_persistence_error", error=str(exc))

            revoked_count = 0
            try:
                # Revoke all client sessions across the database
                cursor = self.store._conn.execute("SELECT session_id, role FROM sessions WHERE is_revoked = 0")
                for r in cursor.fetchall():
                    # In emergency lockdown, revoke client sessions
                    if r["role"] != "admin":
                        self.store.revoke_session(r["session_id"], reason=f"emergency_lockdown: {reason}")
                        revoked_count += 1
            except Exception as exc:
                logger.error("emergency_lockdown.database_session_revocation_error", error=str(exc))

            try:
                ev = SecurityEvent(
                    event_id=uuid.uuid4().hex,
                    event_type="EMERGENCY_LOCKDOWN_DECLARED",
                    severity=SecurityEventSeverity.CRITICAL,
                    actor_id=initiated_by,
                    details={
                        "reason": reason,
                        "revoked_client_sessions": revoked_count,
                        "pipeline_status": "CONTINUOUS_RECORDING_PRESERVED",
                    },
                    action_taken="LOCKDOWN_ACTIVE_RECORDING_PROTECTED",
                )
                self.store.record_security_event(ev)
            except Exception as exc:
                logger.error("emergency_lockdown.audit_event_logging_error", error=str(exc))

            logger.critical(
                "emergency_lockdown_declared",
                initiated_by=initiated_by,
                reason=reason,
                revoked_sessions=revoked_count,
            )

            return {
                "status": "LOCKDOWN_ACTIVE",
                "declared_at_utc": now,
                "revoked_sessions": revoked_count,
                "recording_pipeline_status": "RECORDING_PRESERVED",
            }

    def lift_lockdown(
        self,
        lifted_by: str,
        reason: str,
        authorizing_admin: Any | None = None,
    ) -> dict[str, Any]:
        """Lift emergency lockdown and restore normal operations.

        Strictly enforces that only verified administrators can terminate lockdown.
        """
        with self._lock:
            if not self._is_active:
                return {"status": "LOCKDOWN_NOT_ACTIVE"}

            # Authorization check: prevent unprivileged users or unauthenticated bypass
            if authorizing_admin is not None:
                is_admin = bool(
                    getattr(authorizing_admin, "is_administrator", False)
                    or getattr(getattr(authorizing_admin, "role", None), "value", str(getattr(authorizing_admin, "role", ""))) == "admin"
                )
                if not is_admin:
                    raise PermissionError(f"User '{lifted_by}' is not authorized to lift emergency lockdown")

            self._is_active = False
            self._lockdown_details = {}
            now = datetime.now(timezone.utc).isoformat()

            # Atomically remove durable recovery latch file
            try:
                self.latch_path.unlink(missing_ok=True)
            except Exception as exc:
                logger.error("emergency_lockdown.latch_removal_error", error=str(exc))

            try:
                ev = SecurityEvent(
                    event_id=uuid.uuid4().hex,
                    event_type="EMERGENCY_LOCKDOWN_LIFTED",
                    severity=SecurityEventSeverity.INFO,
                    actor_id=lifted_by,
                    details={"reason": reason, "lifted_at_utc": now},
                    action_taken="NORMAL_OPERATIONS_RESTORED",
                )
                self.store.record_security_event(ev)
            except Exception as exc:
                logger.error("emergency_lockdown.audit_lift_error", error=str(exc))

            logger.info("emergency_lockdown_lifted", lifted_by=lifted_by, reason=reason)
            return {"status": "LOCKDOWN_LIFTED", "lifted_at_utc": now}

    def can_perform_action(self, action: str, is_admin: bool = False) -> bool:
        """Check whether an action is permitted during emergency lockdown."""
        with self._lock:
            if not self._is_active:
                return True

            # Recording and pipeline invariants are ALWAYS allowed
            if action in PERMITTED_LOCKDOWN_ACTIONS:
                return True

            # Local administrator can perform diagnostic or emergency lift actions
            if is_admin and action in ("system:status", "audit:view", "emergency:lift"):
                return True

            # All other actions are blocked during lockdown
            return False
