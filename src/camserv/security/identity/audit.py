"""
camserv.security.identity.audit
===============================

Tamper-evident, cryptographically hash-chained security audit subsystem.
Provides SHA-256 hash chaining, entry immutability verification, and forensic export.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import structlog

from camserv.security.identity.models import SecurityEvent, SecurityEventSeverity
from camserv.security.identity.store import DurableIdentityStore

logger = structlog.get_logger(__name__)

GENESIS_HASH = "GENESIS_SECURITY_AUDIT_HASH_PHASE26_00000000"


class TamperEvidentSecurityAudit:
    """Tamper-evident security event ledger with forward hash chaining."""

    def __init__(self, store: DurableIdentityStore) -> None:
        self.store = store

    def log_event(self, event: SecurityEvent) -> SecurityEvent:
        """Record a security event into the hash chain."""
        return self.store.record_security_event(event)

    def verify_chain_integrity(self) -> tuple[bool, int, str | None]:
        """Verify the cryptographic hash chain of all recorded security events.

        Returns (is_valid, verified_count, error_message).
        """
        with self.store._lock:
            cursor = self.store._conn.execute(
                "SELECT * FROM security_events ORDER BY rowid ASC"
            )
            rows = cursor.fetchall()
            if not rows:
                return (True, 0, None)

            expected_prev = GENESIS_HASH
            for idx, r in enumerate(rows):
                prev_hash = r["prev_hash"]
                entry_hash = r["entry_hash"]

                if prev_hash != expected_prev:
                    err = (
                        f"Hash chain broken at row {idx} (event_id={r['event_id']}): "
                        f"expected prev_hash '{expected_prev}', got '{prev_hash}'"
                    )
                    logger.critical("audit_chain_integrity_violation", error=err)
                    return (False, idx, err)

                # Recompute hash
                details_json = r["details"]
                # In sqlite it was stored as json string
                payload = (
                    f"{r['event_id']}:{r['event_type']}:{r['severity']}:{r['timestamp_utc']}:"
                    f"{r['actor_id']}:{r['ip_address']}:{r['resource_type']}:{r['resource_id']}:"
                    f"{details_json}:{r['action_taken']}:{prev_hash}"
                )
                computed = hashlib.sha256(payload.encode("utf-8")).hexdigest()

                if computed != entry_hash:
                    err = (
                        f"Tampering detected at row {idx} (event_id={r['event_id']}): "
                        f"payload hash '{computed}' does not match recorded entry_hash '{entry_hash}'"
                    )
                    logger.critical("audit_record_tampering_detected", error=err)
                    return (False, idx, err)

                expected_prev = entry_hash

            return (True, len(rows), None)

    def export_jsonl(self, export_path: str | Path) -> int:
        """Export verified audit trail to a standalone JSONL file with hash chain metadata."""
        valid, count, err = self.verify_chain_integrity()
        if not valid:
            raise RuntimeError(f"Cannot export tampered audit log: {err}")

        path = Path(export_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with self.store._lock:
            cursor = self.store._conn.execute("SELECT * FROM security_events ORDER BY rowid ASC")
            rows = cursor.fetchall()

            with open(path, "w", encoding="utf-8") as f:
                for r in rows:
                    entry = {
                        "event_id": r["event_id"],
                        "event_type": r["event_type"],
                        "severity": r["severity"],
                        "timestamp_utc": r["timestamp_utc"],
                        "actor_id": r["actor_id"],
                        "ip_address": r["ip_address"],
                        "resource_type": r["resource_type"],
                        "resource_id": r["resource_id"],
                        "details": json.loads(r["details"]) if r["details"] else {},
                        "action_taken": r["action_taken"],
                        "prev_hash": r["prev_hash"],
                        "entry_hash": r["entry_hash"],
                    }
                    f.write(json.dumps(entry) + "\n")

        return count
