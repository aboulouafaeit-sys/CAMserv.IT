"""
camserv.security.audit_trail
============================

Cryptographically sealed audit logging with SHA-256 hash chaining,
field sanitization (zero password/token leakage), and tamper-evident verification.
"""

from __future__ import annotations

import enum
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class AuditAction(str, enum.Enum):
    """Categorized security-relevant operations."""

    USER_LOGIN = "user:login"
    USER_LOGOUT = "user:logout"
    CONFIG_CHANGE = "config:change"
    DEVICE_ENROLL = "device:enroll"
    DEVICE_REVOKE = "device:revoke"
    EVIDENCE_ACCESS = "evidence:access"
    EVIDENCE_EXPORT_DERIVATIVE = "evidence:export_derivative"
    EVIDENCE_EXPORT_RAW = "evidence:export_raw"
    EVENT_REVIEW = "event:review"
    PERMISSION_CHANGE = "permission:change"


@dataclass(slots=True)
class AuditEntry:
    """Immutable audit trail record cryptographically bound to preceding entry."""

    entry_id: str
    timestamp_utc: float
    tenant_id: str
    user_id: str
    action: AuditAction
    resource_id: str
    status: str  # "SUCCESS" or "DENIED"
    ip_address: str
    details: dict[str, Any]
    previous_hash: str
    entry_hash: str = ""

    def compute_hash(self) -> str:
        """Compute SHA-256 digest over canonical entry fields."""
        details_canonical = json.dumps(self.details, sort_keys=True)
        details_hash = hashlib.sha256(details_canonical.encode("utf-8")).hexdigest()

        serialized = (
            f"{self.entry_id}|{int(self.timestamp_utc)}|{self.tenant_id}|{self.user_id}|"
            f"{self.action.value}|{self.resource_id}|{self.status}|{self.ip_address}|"
            f"{details_hash}|{self.previous_hash}"
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Serialize audit entry."""
        return {
            "entry_id": self.entry_id,
            "timestamp_utc": self.timestamp_utc,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "action": self.action.value,
            "resource_id": self.resource_id,
            "status": self.status,
            "ip_address": self.ip_address,
            "details": self.details,
            "previous_hash": self.previous_hash,
            "entry_hash": self.entry_hash,
        }


class SecurityAuditLogger:
    """
    Manages structured, sanitizing, hash-chained security audit trails.
    Preserves audit isolation in test harnesses using in-memory sinks.
    """

    GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

    # Sensitive keys that must be stripped or masked from details
    SENSITIVE_KEYS = {
        "password", "password_hash", "token", "secret", "private_key",
        "raw_video", "raw_frame", "jwt", "auth_header", "pin"
    }

    def __init__(self, in_memory: bool = True) -> None:
        self.in_memory = in_memory
        self.entries: list[AuditEntry] = []
        self._last_hash = self.GENESIS_HASH

    def sanitize_details(self, details: dict[str, Any]) -> dict[str, Any]:
        """Deeply sanitize sensitive credentials, keys, or binary frame payloads across dicts and iterables."""
        sanitized: dict[str, Any] = {}
        for k, v in details.items():
            if any(sens in k.lower() for sens in self.SENSITIVE_KEYS):
                sanitized[k] = "[REDACTED_BY_SECURITY_POLICY]"
            elif isinstance(v, dict):
                sanitized[k] = self.sanitize_details(v)
            elif isinstance(v, (list, tuple, set)):
                sanitized[k] = [
                    self.sanitize_details(item) if isinstance(item, dict)
                    else ("[REDACTED_BY_SECURITY_POLICY]" if any(sens in k.lower() for sens in self.SENSITIVE_KEYS) else item)
                    for item in v
                ]
            elif isinstance(v, bytes):
                sanitized[k] = f"<binary_bytes_len_{len(v)}>"
            else:
                sanitized[k] = v
        return sanitized

    def record_event(
        self,
        tenant_id: str,
        user_id: str,
        action: AuditAction,
        resource_id: str,
        status: str = "SUCCESS",
        details: dict[str, Any] | None = None,
        ip_address: str = "127.0.0.1",
    ) -> AuditEntry:
        """Create and seal a new chained audit entry."""
        sanitized_details = self.sanitize_details(details or {})
        entry_id = uuid.uuid4().hex
        now = time.time()

        entry = AuditEntry(
            entry_id=entry_id,
            timestamp_utc=now,
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            resource_id=resource_id,
            status=status.upper(),
            ip_address=ip_address,
            details=sanitized_details,
            previous_hash=self._last_hash,
        )
        entry.entry_hash = entry.compute_hash()
        self._last_hash = entry.entry_hash
        self.entries.append(entry)

        logger.info(
            "audit.event_recorded",
            action=action.value,
            user_id=user_id,
            tenant_id=tenant_id,
            status=status,
            entry_hash=entry.entry_hash[:16],
        )
        return entry

    @classmethod
    def verify_chain_integrity(cls, entries: list[AuditEntry]) -> bool:
        """Verify unbroken cryptographic SHA-256 Merkle hash chain across entries."""
        if not entries:
            return True

        expected_prev = cls.GENESIS_HASH
        for idx, entry in enumerate(entries):
            # Check previous hash continuity
            if entry.previous_hash != expected_prev:
                logger.error("audit.chain_broken_prev_mismatch", index=idx, expected=expected_prev, got=entry.previous_hash)
                return False

            # Check self hash computation
            recalculated = entry.compute_hash()
            if entry.entry_hash != recalculated:
                logger.error("audit.chain_entry_tampered", index=idx, recorded=entry.entry_hash, recalculated=recalculated)
                return False

            expected_prev = entry.entry_hash

        return True
