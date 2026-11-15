"""Tamper-evident, immutable audit trail for security compliance and oversight.

Provides :class:`AuditLogger`:
  * Cryptographic SHA-256 hash-chained audit log records.
  * Append-only JSON Lines file persistence with rotation support.
  * Captures actor, action, resource, result, timestamp, details, and hash proof.
  * Query interface with multi-field filtering and time-window searches.
  * End-to-end chain verification for compliance audits (GDPR / ISO 27001 / SOC 2).
  * Compliance report export.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Sequence

import structlog

logger = structlog.get_logger(__name__)

GENESIS_HASH = "0" * 64


# Standard audit actions
class AuditAction:
    LOGIN = "login"
    LOGOUT = "logout"
    CONFIG_CHANGE = "config_change"
    EVENT_VERIFICATION = "event_verification"
    DATA_EXPORT = "data_export"
    CAMERA_ADD = "camera_add"
    CAMERA_REMOVE = "camera_remove"
    ALERT_DISMISS = "alert_dismiss"
    ACCESS_REQUEST = "access_request"
    DATA_PURGE = "data_purge"
    ACCESS_DENIED = "access_denied"
    EVIDENCE_SEALED = "evidence_sealed"
    EVIDENCE_EXPORTED = "evidence_exported"
    RECORDING_STARTED = "recording_started"
    RECORDING_STOPPED = "recording_stopped"
    JUDICIAL_HOLD = "judicial_hold"


@dataclass(slots=True)
class AuditEntry:
    """A single immutable, hash-linked audit record."""

    timestamp: str  # ISO 8601 UTC
    actor: str  # username, service, or API key ID
    action: str  # one of AuditAction or custom string
    resource: str  # target entity e.g. "camera:front_gate", "event:evt_123"
    result: str  # "SUCCESS", "FAILURE", "DENIED"
    details: dict[str, Any]
    prev_hash: str
    entry_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditEntry":
        return cls(**data)


def compute_audit_hash(
    timestamp: str,
    actor: str,
    action: str,
    resource: str,
    result: str,
    details: dict[str, Any],
    prev_hash: str,
) -> str:
    """Compute deterministic SHA-256 hash over canonical audit fields."""
    canonical_details = json.dumps(details, sort_keys=True)
    payload = f"{prev_hash}|{timestamp}|{actor}|{action}|{resource}|{result}|{canonical_details}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AuditLogger:
    """Tamper-evident audit logger maintaining a cryptographic SHA-256 hash chain."""

    def __init__(
        self,
        log_path: Path | str = "logs/audit.jsonl",
        max_bytes: int = 50 * 1024 * 1024,  # 50MB before rotation
        max_backups: int = 10,
    ) -> None:
        self.log_path = Path(log_path)
        self.max_bytes = max_bytes
        self.max_backups = max_backups

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._last_hash = self._get_tail_hash()

    def _get_tail_hash(self) -> str:
        """Find hash of latest record or return GENESIS_HASH."""
        if not self.log_path.exists():
            return GENESIS_HASH

        last = GENESIS_HASH
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rec = json.loads(line)
                            last = rec.get("entry_hash", GENESIS_HASH)
                        except json.JSONDecodeError:
                            continue
        except Exception:
            return GENESIS_HASH
        return last

    def log(
        self,
        actor: str,
        action: str,
        resource: str,
        result: str = "SUCCESS",
        details: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> AuditEntry:
        """Log an event to the immutable audit trail.

        Parameters
        ----------
        actor:
            User or service that initiated the action.
        action:
            Action performed (e.g. login, config_change, camera_add).
        resource:
            Identifier of target resource.
        result:
            Outcome ("SUCCESS", "FAILURE", "DENIED").
        details:
            Arbitrary key-value details.
        timestamp:
            Optional override for event time.
        """
        ts_str = (
            timestamp.isoformat()
            if isinstance(timestamp, datetime)
            else datetime.now(timezone.utc).isoformat()
        )
        safe_details = details or {}
        prev_hash = self._last_hash

        entry_hash = compute_audit_hash(
            timestamp=ts_str,
            actor=actor,
            action=action,
            resource=resource,
            result=result,
            details=safe_details,
            prev_hash=prev_hash,
        )

        entry = AuditEntry(
            timestamp=ts_str,
            actor=actor,
            action=action,
            resource=resource,
            result=result,
            details=safe_details,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )

        self._rotate_if_needed()

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict()) + "\n")

        self._last_hash = entry_hash
        logger.info(
            "audit.recorded",
            actor=actor,
            action=action,
            resource=resource,
            result=result,
            hash=entry_hash[:16],
        )
        return entry

    # Alias for audit recording
    record = log

    def _rotate_if_needed(self) -> None:
        """Rotate audit log if size exceeds max_bytes."""
        if not self.log_path.exists():
            return
        try:
            if self.log_path.stat().st_size >= self.max_bytes:
                # Rotate files: audit.jsonl -> audit.jsonl.1 etc.
                for i in range(self.max_backups - 1, 0, -1):
                    src = self.log_path.with_name(f"{self.log_path.name}.{i}")
                    dst = self.log_path.with_name(f"{self.log_path.name}.{i + 1}")
                    if src.exists():
                        src.replace(dst)

                dst1 = self.log_path.with_name(f"{self.log_path.name}.1")
                self.log_path.replace(dst1)
                logger.info("audit.rotated", old=str(self.log_path), new=str(dst1))
        except Exception as exc:
            logger.warning("audit.rotation_failed", error=str(exc))

    def query(
        self,
        actor: str | None = None,
        action: str | None = None,
        resource: str | None = None,
        result: str | None = None,
        start_time: datetime | str | None = None,
        end_time: datetime | str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Query audit log with filters and pagination."""
        if not self.log_path.exists():
            return []

        start_dt = (
            datetime.fromisoformat(start_time)
            if isinstance(start_time, str)
            else start_time
        )
        end_dt = (
            datetime.fromisoformat(end_time)
            if isinstance(end_time, str)
            else end_time
        )

        matches: list[AuditEntry] = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = AuditEntry.from_dict(json.loads(line))
                except Exception:
                    continue

                if actor and entry.actor != actor:
                    continue
                if action and entry.action != action:
                    continue
                if resource and resource not in entry.resource:
                    continue
                if result and entry.result != result:
                    continue

                entry_dt = datetime.fromisoformat(entry.timestamp)
                if start_dt and entry_dt < start_dt:
                    continue
                if end_dt and entry_dt > end_dt:
                    continue

                matches.append(entry)

        # Return latest entries up to limit
        return matches[-limit:]

    def verify_integrity(self, file_path: Path | str | None = None) -> tuple[bool, int, list[str]]:
        """Verify cryptographic integrity of audit log chain.

        Returns (is_valid, record_count, error_messages).
        """
        target = Path(file_path) if file_path else self.log_path
        if not target.exists():
            return True, 0, []

        records: list[AuditEntry] = []
        with open(target, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(AuditEntry.from_dict(json.loads(line)))
                    except Exception as exc:
                        return False, len(records), [f"Corrupted JSON line: {str(exc)}"]

        errors: list[str] = []
        expected_prev = GENESIS_HASH

        for i, rec in enumerate(records):
            if rec.prev_hash != expected_prev:
                errors.append(
                    f"Broken link at record #{i} (timestamp {rec.timestamp}): "
                    f"expected prev_hash {expected_prev}, got {rec.prev_hash}"
                )

            recomputed = compute_audit_hash(
                timestamp=rec.timestamp,
                actor=rec.actor,
                action=rec.action,
                resource=rec.resource,
                result=rec.result,
                details=rec.details,
                prev_hash=rec.prev_hash,
            )
            if recomputed != rec.entry_hash:
                errors.append(
                    f"Tampered record at #{i} (timestamp {rec.timestamp}): "
                    f"recomputed {recomputed} != recorded {rec.entry_hash}"
                )

            expected_prev = rec.entry_hash

        return len(errors) == 0, len(records), errors

    def export_report(
        self,
        output_format: str = "json",
        actor: str | None = None,
        action: str | None = None,
        start_time: datetime | str | None = None,
        end_time: datetime | str | None = None,
    ) -> str:
        """Export audit events as JSON or CSV compliance report."""
        entries = self.query(
            actor=actor,
            action=action,
            start_time=start_time,
            end_time=end_time,
            limit=10_000,
        )
        is_valid, total, errors = self.verify_integrity()

        if output_format.lower() == "csv":
            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(["timestamp", "actor", "action", "resource", "result", "entry_hash", "prev_hash", "details"])
            for e in entries:
                writer.writerow([
                    e.timestamp,
                    e.actor,
                    e.action,
                    e.resource,
                    e.result,
                    e.entry_hash,
                    e.prev_hash,
                    json.dumps(e.details),
                ])
            return output.getvalue()

        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "chain_integrity": {
                "valid": is_valid,
                "total_records": total,
                "errors": errors,
            },
            "records_count": len(entries),
            "records": [e.to_dict() for e in entries],
        }
        return json.dumps(report, indent=2)
