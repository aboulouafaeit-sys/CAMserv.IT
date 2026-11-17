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
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from camserv.security.identity.models import SecurityEvent, SecurityEventSeverity
from camserv.security.identity.store import DurableIdentityStore

logger = structlog.get_logger(__name__)

GENESIS_HASH = "GENESIS_SECURITY_AUDIT_HASH_PHASE26_00000000"


class CheckpointSequenceRegressionError(ValueError):
    """Raised when an incoming checkpoint attempts to roll back or regress sequence number."""

    pass


class CheckpointStoreMissingError(RuntimeError):
    """Raised when external checkpoint store is missing while identity ledger contains historical records."""

    pass


class CheckpointCorruptedError(RuntimeError):
    """Raised when external checkpoint store file is corrupted, malformed, or tampered."""

    pass


@dataclass(slots=True)
class AuditCheckpoint:
    """Signed external checkpoint anchoring the security audit hash-chain head."""

    checkpoint_id: str
    sequence_number: int  # row count
    head_entry_hash: str
    created_at_utc: str
    signature: str
    algorithm: str = "HMAC-SHA256"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditCheckpoint:
        if "algorithm" not in data:
            data = dict(data)
            data["algorithm"] = "HMAC-SHA256"
        return cls(**data)


class ExternalCheckpointStore:
    """Durable, independent local trust anchor store for audit checkpoints outside SQLite database.

    Enforces strict sequence monotonicity to detect and block rollback attacks,
    coordinated database snapshot restorations, and missing checkpoint generations.
    """

    def __init__(self, store_path: str | Path = "data/checkpoints/trust_anchor.json") -> None:
        self.store_path = Path(store_path)
        self._lock = threading.RLock()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    def save_checkpoint(
        self,
        checkpoint: AuditCheckpoint,
        allow_equal_sequence: bool = False,
    ) -> None:
        """Persist a signed checkpoint. Enforces sequence monotonicity to defeat snapshot rollback attacks."""
        with self._lock:
            latest = self.get_latest_checkpoint()
            if latest is not None:
                if checkpoint.sequence_number < latest.sequence_number:
                    raise CheckpointSequenceRegressionError(
                        f"Monotonicity violation: attempted to store checkpoint at sequence "
                        f"{checkpoint.sequence_number}, but latest external trust anchor is at sequence "
                        f"{latest.sequence_number}. Snapshot rollback attack detected!"
                    )
                if (
                    not allow_equal_sequence
                    and checkpoint.sequence_number == latest.sequence_number
                    and checkpoint.head_entry_hash != latest.head_entry_hash
                ):
                    raise CheckpointSequenceRegressionError(
                        f"Divergent head hash at sequence {checkpoint.sequence_number}: expected "
                        f"'{latest.head_entry_hash}', got '{checkpoint.head_entry_hash}'"
                    )

            checkpoints = self.get_all_checkpoints()
            if checkpoints and checkpoints[-1].checkpoint_id == checkpoint.checkpoint_id:
                return

            checkpoints.append(checkpoint)

            # Atomic write to external trust anchor file
            temp_path = self.store_path.with_suffix(".tmp")
            data = [c.to_dict() for c in checkpoints]
            temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            temp_path.replace(self.store_path)

            logger.info(
                "external_checkpoint_stored",
                checkpoint_id=checkpoint.checkpoint_id,
                sequence=checkpoint.sequence_number,
                algorithm=checkpoint.algorithm,
            )

    def get_latest_checkpoint(self) -> AuditCheckpoint | None:
        """Retrieve the most recent trusted checkpoint."""
        with self._lock:
            checkpoints = self.get_all_checkpoints()
            return checkpoints[-1] if checkpoints else None

    def get_all_checkpoints(self) -> list[AuditCheckpoint]:
        """Retrieve all checkpoints in sequence order."""
        with self._lock:
            if not self.store_path.exists():
                return []
            try:
                content = self.store_path.read_text(encoding="utf-8").strip()
                if not content:
                    raise CheckpointCorruptedError(
                        f"External checkpoint store at '{self.store_path}' is empty or truncated"
                    )
                raw_list = json.loads(content)
                if not isinstance(raw_list, list):
                    raise CheckpointCorruptedError(
                        f"External checkpoint store at '{self.store_path}' root must be a JSON array"
                    )
                return [AuditCheckpoint.from_dict(item) for item in raw_list]
            except Exception as exc:
                if isinstance(exc, CheckpointCorruptedError):
                    raise
                logger.error(
                    "external_checkpoint_store.read_error",
                    path=str(self.store_path),
                    error=str(exc),
                )
                raise CheckpointCorruptedError(
                    f"External checkpoint store at '{self.store_path}' could not be parsed: {exc}"
                ) from exc

    def verify_store_monotonicity(self) -> tuple[bool, str | None]:
        """Verify that all externally held checkpoints have non-decreasing sequence numbers."""
        with self._lock:
            checkpoints = self.get_all_checkpoints()
            last_seq = -1
            for c in checkpoints:
                if c.sequence_number < last_seq:
                    return (
                        False,
                        f"Monotonicity break in external store at checkpoint {c.checkpoint_id}: "
                        f"sequence {c.sequence_number} < previous {last_seq}",
                    )
                last_seq = c.sequence_number
            return (True, None)


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

    def create_checkpoint(
        self,
        signing_key: bytes | None = None,
        private_key: Ed25519PrivateKey | None = None,
    ) -> AuditCheckpoint:
        """Create a cryptographically signed checkpoint of the current audit chain head.

        Supports symmetric HMAC-SHA256 or asymmetric Ed25519 signing.
        """
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

        if private_key is not None:
            # Asymmetric Ed25519 signature
            sig_bytes = private_key.sign(payload.encode("utf-8"))
            signature = sig_bytes.hex()
            algorithm = "Ed25519"
        else:
            # Symmetric HMAC-SHA256 signature
            key = signing_key or b"camserv-default-internal-audit-checkpoint-key-v1"
            signature = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
            algorithm = "HMAC-SHA256"

        return AuditCheckpoint(
            checkpoint_id=cid,
            sequence_number=count,
            head_entry_hash=head_hash,
            created_at_utc=now_utc,
            signature=signature,
            algorithm=algorithm,
        )

    def verify_against_checkpoint(
        self,
        checkpoint: AuditCheckpoint,
        signing_key: bytes | None = None,
        public_key: Ed25519PublicKey | None = None,
    ) -> tuple[bool, str | None]:
        """Verify that current database state matches an externally held signed checkpoint.

        Detects full-chain recalculation and historical database rollback attacks.
        Supports both HMAC-SHA256 and Ed25519 verification.
        """
        # 1. Verify checkpoint signature
        payload = f"{checkpoint.checkpoint_id}:{checkpoint.sequence_number}:{checkpoint.head_entry_hash}:{checkpoint.created_at_utc}"

        if checkpoint.algorithm == "Ed25519":
            if public_key is None:
                return (False, "Ed25519 public key required to verify Ed25519 checkpoint")
            try:
                sig_bytes = bytes.fromhex(checkpoint.signature)
                public_key.verify(sig_bytes, payload.encode("utf-8"))
            except (InvalidSignature, ValueError) as exc:
                return (False, f"Ed25519 checkpoint signature invalid or forged: {exc}")
        else:
            key = signing_key or b"camserv-default-internal-audit-checkpoint-key-v1"
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

    def create_and_persist_checkpoint(
        self,
        external_store: ExternalCheckpointStore,
        signing_key: bytes | None = None,
        private_key: Ed25519PrivateKey | None = None,
    ) -> AuditCheckpoint:
        """Create a checkpoint and atomically anchor it into an independent external store."""
        checkpoint = self.create_checkpoint(signing_key=signing_key, private_key=private_key)
        external_store.save_checkpoint(checkpoint)
        return checkpoint

    def verify_against_external_store(
        self,
        external_store: ExternalCheckpointStore,
        signing_key: bytes | None = None,
        public_key: Ed25519PublicKey | None = None,
    ) -> tuple[bool, str | None]:
        """Verify the current database against the latest checkpoint held in the external store.

        Detects missing/deleted checkpoint stores, rollback attacks, and divergent chains.
        """
        with self.store._lock:
            cursor = self.store._conn.execute("SELECT COUNT(*) AS count FROM security_events")
            row = cursor.fetchone()
            db_count = row["count"] if row else 0

        latest = external_store.get_latest_checkpoint()
        if latest is None:
            if db_count > 0:
                raise CheckpointStoreMissingError(
                    f"External checkpoint store at '{external_store.store_path}' is missing or empty, "
                    f"but database contains {db_count} audit events. Potential state tampering or checkpoint deletion attack!"
                )
            return (True, None)

        return self.verify_against_checkpoint(latest, signing_key=signing_key, public_key=public_key)

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
