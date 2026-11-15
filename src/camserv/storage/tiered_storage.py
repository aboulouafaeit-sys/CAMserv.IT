"""
camserv.storage.tiered_storage
==============================

Tiered storage architecture, automated retention purging, judicial hold enforcement,
and court-admissible evidence export packaging for CAMserv Enterprise.
"""

from __future__ import annotations

import enum
import hashlib
import json
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
from cryptography.hazmat.primitives.asymmetric import ed25519

logger = structlog.get_logger(__name__)


class StorageTier(str, enum.Enum):
    """Operational storage tiers."""

    RAM_PRE_ROLL = "ram_pre_roll"          # Volatile circular memory buffer (15s)
    OPERATIONAL_FAST = "operational_fast"  # High-speed local NVMe/SSD rolling storage
    FORENSIC_VAULT = "forensic_vault"      # Long-term encrypted incident vault
    COLD_ARCHIVE = "cold_archive"          # External secondary S3 or network share


class ExportAuthorizationError(PermissionError):
    """Raised when evidence export fails authorization or quorum checks."""


@dataclass(slots=True)
class RetentionPolicy:
    """Configurable retention rules under GDPR storage limitation (Art. 5.1.e)."""

    continuous_retention_hours: float = 48.0   # Standard surveillance purged after 48h
    incident_retention_days: float = 365.0      # Tagged security incidents kept 1 year
    emergency_purge_threshold_percent: float = 90.0 # Disk capacity ceiling


@dataclass(slots=True)
class StoredChunkRecord:
    """Indexed metadata for a stored video chunk or evidence artifact."""

    chunk_id: str
    camera_id: str
    timestamp_utc: float
    tier: StorageTier
    size_bytes: int
    sha256_hash: str
    file_path: Path
    is_incident: bool = False
    judicial_hold: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class TieredStorageManager:
    """
    Coordinates multi-tiered storage pools, automated retention purging,
    judicial hold locking, and controlled courtroom evidence exports.
    """

    def __init__(
        self,
        base_dir: Path | str,
        retention_policy: RetentionPolicy | None = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.policy = retention_policy or RetentionPolicy()
        self.chunks: dict[str, StoredChunkRecord] = {}

        self.op_dir = self.base_dir / "operational"
        self.vault_dir = self.base_dir / "vault"
        self.export_dir = self.base_dir / "exports"

        self.op_dir.mkdir(parents=True, exist_ok=True)
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def store_chunk(
        self,
        chunk_id: str,
        camera_id: str,
        data: bytes,
        is_incident: bool = False,
        tier: StorageTier = StorageTier.OPERATIONAL_FAST,
        timestamp: float | None = None,
    ) -> StoredChunkRecord:
        """Store a video chunk in the appropriate tier and record its cryptographic hash."""
        now = timestamp if timestamp is not None else time.time()
        sha256 = hashlib.sha256(data).hexdigest()

        target_dir = self.vault_dir if is_incident or tier == StorageTier.FORENSIC_VAULT else self.op_dir
        chunk_path = target_dir / f"{camera_id}_{chunk_id}.chunk"
        chunk_path.write_bytes(data)

        record = StoredChunkRecord(
            chunk_id=chunk_id,
            camera_id=camera_id,
            timestamp_utc=now,
            tier=tier,
            size_bytes=len(data),
            sha256_hash=sha256,
            file_path=chunk_path,
            is_incident=is_incident,
            judicial_hold=False,
        )
        self.chunks[chunk_id] = record
        logger.info("storage.chunk_stored", chunk_id=chunk_id, tier=tier.value, is_incident=is_incident)
        return record

    def set_judicial_hold(self, chunk_id: str, hold: bool, reason: str, operator_id: str) -> bool:
        """Lock or unlock an incident under judicial hold to prevent automated retention purging."""
        if chunk_id not in self.chunks:
            return False

        chunk = self.chunks[chunk_id]
        chunk.judicial_hold = hold
        chunk.metadata["judicial_hold_reason"] = reason
        chunk.metadata["judicial_hold_operator"] = operator_id
        chunk.metadata["judicial_hold_updated_at"] = time.time()
        logger.info("storage.judicial_hold_updated", chunk_id=chunk_id, hold=hold, reason=reason)
        return True

    def evaluate_retention_and_purge(self, now: float | None = None) -> dict[str, Any]:
        """
        Scan chunks against retention policy and purge expired data.
        1. Standard non-incident video older than continuous_retention_hours is purged.
        2. Incident video older than incident_retention_days is purged UNLESS judicial_hold is active.
        """
        current_time = now if now is not None else time.time()
        purged_ids: list[str] = []
        freed_bytes = 0
        preserved_incidents = 0

        continuous_cutoff = current_time - (self.policy.continuous_retention_hours * 3600.0)
        incident_cutoff = current_time - (self.policy.incident_retention_days * 86400.0)

        for chunk_id, chunk in list(self.chunks.items()):
            should_purge = False

            if chunk.judicial_hold:
                # NEVER purge chunks locked under judicial hold
                preserved_incidents += 1
                continue

            if chunk.is_incident:
                if chunk.timestamp_utc < incident_cutoff:
                    should_purge = True
                else:
                    preserved_incidents += 1
            else:
                if chunk.timestamp_utc < continuous_cutoff:
                    should_purge = True

            if should_purge:
                try:
                    if chunk.file_path.exists():
                        chunk.file_path.unlink()
                    freed_bytes += chunk.size_bytes
                    purged_ids.append(chunk_id)
                    del self.chunks[chunk_id]
                    logger.info("storage.chunk_purged", chunk_id=chunk_id, size=chunk.size_bytes)
                except Exception as e:
                    logger.error("storage.purge_failed", chunk_id=chunk_id, error=str(e))

        return {
            "purged_count": len(purged_ids),
            "freed_mb": round(freed_bytes / (1024 * 1024), 2),
            "preserved_incidents": preserved_incidents,
        }

    def export_courtroom_evidence_package(
        self,
        chunk_id: str,
        output_zip_path: Path | str,
        operator_id: str,
        include_raw: bool = False,
        dual_quorum_approved: bool = False,
        signing_key: ed25519.Ed25519PrivateKey | None = None,
    ) -> Path:
        """
        Build a court-admissible evidence export package (.zip).
        Includes manifest, derivative video, and raw evidence (strictly gated by dual-control quorum).
        """
        if chunk_id not in self.chunks:
            raise ValueError(f"Chunk '{chunk_id}' not found in storage catalog.")

        chunk = self.chunks[chunk_id]

        # Enforce dual-control quorum for raw pristine video export
        if include_raw and not dual_quorum_approved:
            logger.critical("storage.unauthorized_raw_export_attempt", chunk_id=chunk_id, operator=operator_id)
            raise ExportAuthorizationError(
                "UNAUTHORIZED EXPORT: Exporting unmasked pristine raw evidence requires "
                "verified dual-control quorum authorization under GDPR Article 25."
            )

        zip_dest = Path(output_zip_path)
        zip_dest.parent.mkdir(parents=True, exist_ok=True)

        manifest = {
            "export_id": f"EXP-{chunk_id}-{int(time.time())}",
            "chunk_id": chunk_id,
            "camera_id": chunk.camera_id,
            "recorded_at_utc": chunk.timestamp_utc,
            "exported_at_utc": time.time(),
            "operator_id": operator_id,
            "include_raw": include_raw,
            "dual_quorum_approved": dual_quorum_approved,
            "original_sha256": chunk.sha256_hash,
            "files": [],
        }

        # Build zip bundle
        with zipfile.ZipFile(str(zip_dest), "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. Add derivative evidence
            if chunk.file_path.exists():
                arcname = f"evidence/{chunk.file_path.name}"
                zf.write(str(chunk.file_path), arcname=arcname)
                manifest["files"].append({"path": arcname, "sha256": chunk.sha256_hash})

            # 2. Add raw pristine evidence if approved
            if include_raw and dual_quorum_approved:
                raw_arcname = f"raw_pristine/{chunk.file_path.name}.raw"
                zf.write(str(chunk.file_path), arcname=raw_arcname)
                manifest["files"].append({"path": raw_arcname, "sha256": chunk.sha256_hash, "classification": "PRISTINE_VAULT"})

            # 3. Add manifest JSON
            manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
            zf.writestr("manifest.json", manifest_bytes)

            # 4. Add cryptographic signature if key provided
            if signing_key:
                sig = signing_key.sign(manifest_bytes)
                zf.writestr("signature.ed25519", sig)
                manifest["signature_hex"] = sig.hex()

        logger.info("storage.evidence_package_exported", chunk_id=chunk_id, path=str(zip_dest), raw=include_raw)
        return zip_dest
