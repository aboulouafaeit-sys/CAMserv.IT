"""
camserv.security.identity.audit
===============================

Tamper-evident, cryptographically hash-chained security audit subsystem.
Provides SHA-256 hash chaining, entry immutability verification, and forensic export.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from camserv.security.identity.models import SecurityEvent, SecurityEventSeverity
from camserv.security.identity.store import DurableIdentityStore

logger = structlog.get_logger(__name__)

GENESIS_HASH = "GENESIS_SECURITY_AUDIT_HASH_PHASE26_00000000"


@dataclass(slots=True)
class AuditCheckpoint:
    """Signed external checkpoint anchoring the security audit hash-chain head."""

    checkpoint_id: str
    sequence_number: int  # row count
    head_entry_hash: str
    created_at_utc: str
    signature: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditCheckpoint:
        return cls(**data)


class TamperEvidentSecurityAudit:
    """Tamper-evident security event ledger with forward hash chaining and external checkpoints."""

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

    def create_checkpoint(self, signing_key: bytes | None = None) -> AuditCheckpoint:
        """Create a cryptographically signed checkpoint of the current audit chain head."""
        valid, count, err = self.verify_chain_integrity()
        if not valid:
            raise RuntimeError(f"Cannot checkpoint corrupted audit ledger: {err}")

        with self.store._lock:
            cursor = self.store._conn.execute(
                "SELECT entry_hash FROM security_events ORDER BY rowid DESC LIMIT 1"
            )
            row = cursor.fetchone()
            head_hash = row["entry_hash"] if row else GENESIS_HASH

        now_utc = datetime.now(timezone.utc).isoformat()
        cid = f"chk_{secrets.token_hex(8)}"
        payload = f"{cid}:{count}:{head_hash}:{now_utc}"

        key = signing_key or b"camserv-default-internal-audit-checkpoint-key-v1"
        signature = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()

        return AuditCheckpoint(
            checkpoint_id=cid,
            sequence_number=count,
            head_entry_hash=head_hash,
            created_at_utc=now_utc,
            signature=signature,
        )

    def verify_against_checkpoint(
        self,
        checkpoint: AuditCheckpoint,
        signing_key: bytes | None = None,
    ) -> tuple[bool, str | None]:
        """Verify that current database state matches an externally held signed checkpoint.

        Detects full-chain recalculation and historical database rollback attacks.
        """
        # 1. Verify checkpoint signature
        key = signing_key or b"camserv-default-internal-audit-checkpoint-key-v1"
        payload = f"{checkpoint.checkpoint_id}:{checkpoint.sequence_number}:{checkpoint.head_entry_hash}:{checkpoint.created_at_utc}"
        expected_sig = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(checkpoint.signature, expected_sig):
            return (False, "Checkpoint signature invalid or forged")

        # 2. Check row count and head hash at that sequence number
        with self.store._lock:
            cursor = self.store._conn.execute(
                "SELECT entry_hash FROM security_events ORDER BY rowid ASC LIMIT 1 OFFSET ?",
                (max(0, checkpoint.sequence_number - 1),),
            )
            row = cursor.fetchone()
            if not row:
                if checkpoint.sequence_number == 0 and checkpoint.head_entry_hash == GENESIS_HASH:
                    return (True, None)
                return (
                    False,
                    f"Rollback detected: database has fewer rows than checkpoint "
                    f"(expected sequence {checkpoint.sequence_number})"
                )

            current_head_hash = row["entry_hash"]
            if current_head_hash != checkpoint.head_entry_hash:
                return (
                    False,
                    f"Full-chain rewrite or rollback detected: checkpoint head hash '{checkpoint.head_entry_hash}' "
                    f"does not match database entry hash '{current_head_hash}' at sequence {checkpoint.sequence_number}"
                )

        return (True, None)

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
