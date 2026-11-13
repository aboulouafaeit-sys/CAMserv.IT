"""Secure tamper-evident evidence storage for security events.

Provides :class:`EvidenceStore`:
  * AES-256-GCM encryption for stored video/image/metadata evidence.
  * SHA-256 cryptographic hash chaining for tamper detection.
  * Integrity verification for individual records or entire chain.
  * Retention management with secure deletion (shredding).
  * Evidence export package generation for legal/compliance investigations.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import structlog

from camserv.security.encryption import EncryptedPayload, EncryptionManager

logger = structlog.get_logger(__name__)

GENESIS_HASH = "0" * 64


@dataclass(slots=True)
class EvidenceRecord:
    """Tamper-evident evidence manifest entry."""

    event_id: str
    camera_id: str
    timestamp: str  # ISO 8601 UTC
    payload_hash: str  # SHA-256 of raw unencrypted artifact
    prev_hash: str  # Hash of previous evidence record in chain
    record_hash: str  # SHA-256 of canonical fields + prev_hash
    encrypted_file: str  # Relative path to encrypted artifact on disk
    key_version: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceRecord":
        return cls(**data)


def compute_record_hash(
    event_id: str,
    camera_id: str,
    timestamp: str,
    payload_hash: str,
    prev_hash: str,
) -> str:
    """Compute deterministic SHA-256 hash for chain validation."""
    content = f"{prev_hash}:{event_id}:{camera_id}:{timestamp}:{payload_hash}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class EvidenceIntegrityError(Exception):
    """Raised when evidence verification fails or tampering is detected."""


class EvidenceStore:
    """Tamper-evident storage engine for incident evidence artifacts.

    All stored files are encrypted with AES-256-GCM and linked in an immutable
    SHA-256 hash chain stored in ``evidence_chain.jsonl``.
    """

    def __init__(
        self,
        base_dir: Path | str,
        encryption_manager: EncryptionManager | None = None,
        master_key: str | None = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.artifacts_dir = self.base_dir / "artifacts"
        self.chain_file = self.base_dir / "evidence_chain.jsonl"

        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

        if encryption_manager is not None:
            self._crypto = encryption_manager
        else:
            key = master_key or os.environ.get("CAMSERV_MASTER_KEY")
            if not key:
                key = EncryptionManager.generate_master_key()
            self._crypto = EncryptionManager(master_key=key)

        self._last_hash = self._read_last_hash()

    def _read_last_hash(self) -> str:
        """Read the hash of the latest record from the chain file."""
        if not self.chain_file.exists():
            return GENESIS_HASH

        last = GENESIS_HASH
        with open(self.chain_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rec = json.loads(line)
                        last = rec.get("record_hash", GENESIS_HASH)
                    except json.JSONDecodeError:
                        continue
        return last

    def store_evidence(
        self,
        event_id: str,
        camera_id: str,
        data: bytes,
        extension: str = "bin",
        metadata: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> EvidenceRecord:
        """Encrypt and store an evidence item, appending it to the hash chain.

        Parameters
        ----------
        event_id:
            Unique ID of the associated security event.
        camera_id:
            Source camera ID.
        data:
            Raw payload bytes (e.g. image, video clip, snapshot).
        extension:
            File extension without dot (e.g. 'jpg', 'mp4', 'json').
        metadata:
            Additional structured metadata to seal with the record.
        timestamp:
            Event timestamp (defaults to current UTC).
        """
        ts_str = (
            timestamp.isoformat()
            if isinstance(timestamp, datetime)
            else datetime.now(timezone.utc).isoformat()
        )

        payload_hash = hashlib.sha256(data).hexdigest()
        prev_hash = self._last_hash
        record_hash = compute_record_hash(
            event_id=event_id,
            camera_id=camera_id,
            timestamp=ts_str,
            payload_hash=payload_hash,
            prev_hash=prev_hash,
        )

        # Encrypt with AES-256-GCM using purpose="evidence"
        encrypted = self._crypto.encrypt(data, purpose="evidence")
        artifact_filename = f"{event_id}_{record_hash[:16]}.{extension}.enc"
        artifact_path = self.artifacts_dir / artifact_filename

        # Write container file: JSON holding nonce, ciphertext, key_version
        artifact_path.write_text(json.dumps(encrypted.to_dict()), encoding="utf-8")

        record = EvidenceRecord(
            event_id=event_id,
            camera_id=camera_id,
            timestamp=ts_str,
            payload_hash=payload_hash,
            prev_hash=prev_hash,
            record_hash=record_hash,
            encrypted_file=artifact_filename,
            key_version=encrypted.key_version,
            metadata=metadata or {},
        )

        # Append to tamper-evident chain log
        with open(self.chain_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict()) + "\n")

        self._last_hash = record_hash

        logger.info(
            "evidence.stored",
            event_id=event_id,
            camera_id=camera_id,
            record_hash=record_hash,
            prev_hash=prev_hash,
        )
        return record

    def retrieve_evidence(self, event_id: str) -> tuple[EvidenceRecord, bytes]:
        """Retrieve and decrypt evidence by event ID.

        Raises :class:`FileNotFoundError` if record or file missing.
        Raises :class:`EvidenceIntegrityError` if decrypted payload hash does not match.
        """
        record: EvidenceRecord | None = None
        if self.chain_file.exists():
            with open(self.chain_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    item = json.loads(line)
                    if item.get("event_id") == event_id:
                        record = EvidenceRecord.from_dict(item)
                        break

        if record is None:
            raise FileNotFoundError(f"Evidence for event {event_id} not found")

        artifact_path = self.artifacts_dir / record.encrypted_file
        if not artifact_path.exists():
            raise FileNotFoundError(f"Evidence artifact file missing: {artifact_path}")

        encrypted_dict = json.loads(artifact_path.read_text(encoding="utf-8"))
        payload = EncryptedPayload.from_dict(encrypted_dict)

        decrypted = self._crypto.decrypt(payload, purpose="evidence")
        actual_hash = hashlib.sha256(decrypted).hexdigest()
        if actual_hash != record.payload_hash:
            raise EvidenceIntegrityError(
                f"Tamper detected! Expected payload hash {record.payload_hash}, got {actual_hash}"
            )

        return record, decrypted

    def verify_record(self, record: EvidenceRecord) -> bool:
        """Verify the integrity of a single record's internal hash."""
        recomputed = compute_record_hash(
            event_id=record.event_id,
            camera_id=record.camera_id,
            timestamp=record.timestamp,
            payload_hash=record.payload_hash,
            prev_hash=record.prev_hash,
        )
        return recomputed == record.record_hash

    def verify_full_chain(self) -> tuple[bool, int, list[str]]:
        """Verify the entire evidence hash chain from genesis.

        Returns (is_valid, record_count, list_of_error_messages).
        """
        if not self.chain_file.exists():
            return True, 0, []

        records: list[EvidenceRecord] = []
        with open(self.chain_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(EvidenceRecord.from_dict(json.loads(line)))

        errors: list[str] = []
        expected_prev = GENESIS_HASH

        for i, rec in enumerate(records):
            if rec.prev_hash != expected_prev:
                errors.append(
                    f"Chain broken at record #{i} (event {rec.event_id}): "
                    f"expected prev_hash {expected_prev}, got {rec.prev_hash}"
                )
            if not self.verify_record(rec):
                errors.append(f"Tamper detected at record #{i} (event {rec.event_id}): record_hash mismatch")

            expected_prev = rec.record_hash

        is_valid = len(errors) == 0
        return is_valid, len(records), errors

    def export_evidence_package(
        self,
        event_ids: Sequence[str],
        output_zip: Path | str,
    ) -> Path:
        """Export decrypted or encrypted evidence artifacts with integrity manifest into a zip archive."""
        out_path = Path(output_zip)
        temp_dir = self.base_dir / f"export_tmp_{datetime.now(timezone.utc).timestamp()}"
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            exported_records: list[dict[str, Any]] = []
            for eid in event_ids:
                try:
                    rec, decrypted_bytes = self.retrieve_evidence(eid)
                    # Write decrypted artifact for investigatory handover
                    raw_name = f"evidence_{rec.event_id}.dat"
                    (temp_dir / raw_name).write_bytes(decrypted_bytes)
                    entry = rec.to_dict()
                    entry["exported_filename"] = raw_name
                    exported_records.append(entry)
                except Exception as exc:
                    logger.warning("evidence.export_skip", event_id=eid, error=str(exc))

            manifest = {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "records_count": len(exported_records),
                "records": exported_records,
                "chain_verified": self.verify_full_chain()[0],
            }
            (temp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            # Zip the folder
            base_name = str(out_path.with_suffix(""))
            archive_path = shutil.make_archive(base_name, "zip", temp_dir)
            return Path(archive_path)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def secure_delete_expired(self, older_than_seconds: float) -> int:
        """Cryptographically shred and delete evidence records older than specified threshold.

        Rewrites the chain file preserving subsequent integrity chain.
        """
        if not self.chain_file.exists():
            return 0

        cutoff = datetime.now(timezone.utc).timestamp() - older_than_seconds
        records: list[EvidenceRecord] = []

        with open(self.chain_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(EvidenceRecord.from_dict(json.loads(line)))

        retained: list[EvidenceRecord] = []
        deleted_count = 0

        for rec in records:
            dt = datetime.fromisoformat(rec.timestamp)
            if dt.timestamp() < cutoff:
                # Shred artifact file
                art_file = self.artifacts_dir / rec.encrypted_file
                if art_file.exists():
                    # Overwrite file with random noise before deleting
                    length = art_file.stat().st_size
                    art_file.write_bytes(os.urandom(length))
                    art_file.unlink(missing_ok=True)
                deleted_count += 1
            else:
                retained.append(rec)

        # Re-chain retained records to maintain contiguous chain integrity
        new_chain: list[EvidenceRecord] = []
        prev_h = GENESIS_HASH
        for rec in retained:
            new_rh = compute_record_hash(
                event_id=rec.event_id,
                camera_id=rec.camera_id,
                timestamp=rec.timestamp,
                payload_hash=rec.payload_hash,
                prev_hash=prev_h,
            )
            updated = EvidenceRecord(
                event_id=rec.event_id,
                camera_id=rec.camera_id,
                timestamp=rec.timestamp,
                payload_hash=rec.payload_hash,
                prev_hash=prev_h,
                record_hash=new_rh,
                encrypted_file=rec.encrypted_file,
                key_version=rec.key_version,
                metadata=rec.metadata,
            )
            new_chain.append(updated)
            prev_h = new_rh

        # Atomically write back chain file
        tmp_chain = self.base_dir / "evidence_chain.jsonl.tmp"
        with open(tmp_chain, "w", encoding="utf-8") as f:
            for r in new_chain:
                f.write(json.dumps(r.to_dict()) + "\n")
        tmp_chain.replace(self.chain_file)
        self._last_hash = prev_h

        logger.info("evidence.purged_expired", deleted=deleted_count, retained=len(retained))
        return deleted_count
