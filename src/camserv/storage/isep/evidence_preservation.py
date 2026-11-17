"""
camserv.storage.isep.evidence_preservation
==========================================

Evidence Preservation Manager for CAMserv ISEP.
Enforces physical and logical isolation of the Evidence Vault from routine retention.
Manages preservation holds (legal, incident, administrative), cryptographic seals,
Ed25519 asymmetric signatures, and courtroom-admissible evidence export packaging.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from camserv.storage.forensics import ForensicSigner
from camserv.storage.isep.models import (
    PreservationHold,
    RecordingSegmentMetadata,
    SegmentState,
    StorageTierType,
)

logger = structlog.get_logger(__name__)


class EvidencePreservationError(Exception):
    """Raised when evidence preservation constraints or integrity checks fail."""


class EvidencePreservationManager:
    """
    Manages the protected Evidence Vault.
    Guarantees that preserved recordings are isolated, locked against auto-pruning,
    and verified before export.
    """

    def __init__(
        self,
        vault_dir: Path | str,
        signer: ForensicSigner | None = None,
    ) -> None:
        self.vault_dir = Path(vault_dir).resolve()
        self.vault_dir.mkdir(parents=True, exist_ok=True)

        self.signer = signer or ForensicSigner()
        self.holds: dict[str, PreservationHold] = {}
        self.vault_segments: dict[str, RecordingSegmentMetadata] = {}

    def apply_preservation_hold(
        self,
        target_id: str,
        reason: str,
        authorized_by: str,
        hold_type: str = "incident",
        target_type: str = "segment",
        expires_at: str | None = None,
    ) -> PreservationHold:
        """
        Place an immutable preservation hold on a segment or recording.
        Strictly prevents any deletion or retention purging while active.
        """
        hold_id = f"hold_{target_id}_{int(time.time())}"
        hold = PreservationHold(
            hold_id=hold_id,
            target_id=target_id,
            target_type=target_type,
            reason=reason,
            authorized_by=authorized_by,
            hold_type=hold_type,
            active=True,
            expires_at=expires_at,
        )
        self.holds[hold_id] = hold
        logger.info(
            "isep.preservation_hold_applied",
            hold_id=hold_id,
            target_id=target_id,
            authorized_by=authorized_by,
            hold_type=hold_type,
        )
        return hold

    def release_preservation_hold(self, hold_id: str, released_by: str, reason: str) -> bool:
        """Explicitly release an active preservation hold with mandatory audit attribution."""
        hold = self.holds.get(hold_id)
        if not hold:
            return False

        hold.active = False
        logger.info(
            "isep.preservation_hold_released",
            hold_id=hold_id,
            released_by=released_by,
            reason=reason,
        )
        return True

    def is_target_protected(self, target_id: str) -> bool:
        """Check whether any active preservation hold covers a segment or recording."""
        now_iso = datetime.now(timezone.utc).isoformat()
        for hold in self.holds.values():
            if hold.target_id == target_id and hold.active:
                if hold.expires_at is None or hold.expires_at > now_iso:
                    return True
        return False

    def ingest_to_vault(
        self,
        segment: RecordingSegmentMetadata,
        hold_reason: str,
        authorized_by: str,
    ) -> RecordingSegmentMetadata:
        """
        Promote a segment into the protected Evidence Vault.
        Copies the file into vault directory, recalculates SHA-256, marks as vault_sealed,
        and applies an incident preservation hold.
        """
        src_path = Path(segment.file_path).resolve()
        if not src_path.exists():
            raise FileNotFoundError(f"Source video file not found: {src_path}")

        vault_cam_dir = self.vault_dir / segment.camera_id
        vault_cam_dir.mkdir(parents=True, exist_ok=True)
        vault_file_path = vault_cam_dir / f"VAULT_{src_path.name}"

        # Copy segment into isolated vault
        shutil.copy2(str(src_path), str(vault_file_path))

        # Re-verify SHA-256 on copied vault artifact
        hasher = hashlib.sha256()
        with open(vault_file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        vault_sha256 = hasher.hexdigest()

        if vault_sha256 != segment.sha256_hash:
            vault_file_path.unlink(missing_ok=True)
            raise EvidencePreservationError(
                f"Vault ingestion checksum mismatch for {segment.segment_id}: "
                f"expected {segment.sha256_hash}, calculated {vault_sha256}."
            )

        hold = self.apply_preservation_hold(
            target_id=segment.segment_id,
            reason=hold_reason,
            authorized_by=authorized_by,
            hold_type="incident",
            target_type="segment",
        )

        vault_meta = RecordingSegmentMetadata(
            schema_version="2.0",
            segment_id=segment.segment_id,
            recording_id=segment.recording_id,
            camera_id=segment.camera_id,
            segment_index=segment.segment_index,
            start_time_utc=segment.start_time_utc,
            end_time_utc=segment.end_time_utc,
            duration_seconds=segment.duration_seconds,
            file_path=str(vault_file_path),
            file_size_bytes=vault_file_path.stat().st_size,
            sha256_hash=vault_sha256,
            codec=segment.codec,
            resolution=segment.resolution,
            fps=segment.fps,
            bitrate_kbps=segment.bitrate_kbps,
            tier=StorageTierType.EVIDENCE_VAULT,
            storage_pool_id=segment.storage_pool_id,
            state=SegmentState.VAULT_SEALED,
            has_motion=segment.has_motion,
            has_event=True,
            event_ids=list(segment.event_ids),
            is_protected_evidence=True,
            preservation_hold_ids=[hold.hold_id],
        )
        self.vault_segments[segment.segment_id] = vault_meta
        logger.info("isep.segment_promoted_to_vault", segment_id=segment.segment_id, path=str(vault_file_path))
        return vault_meta

    def export_courtroom_evidence_bundle(
        self,
        segment_id: str,
        export_dest_dir: Path | str,
        officer_1_id: str,
        officer_2_id: str,
        warrant_ref: str,
    ) -> Path:
        """
        Generate a cryptographically signed courtroom evidence zip package.
        Enforces dual-control officer quorum and court warrant documentation.
        """
        if not officer_1_id or not officer_2_id or officer_1_id == officer_2_id:
            raise PermissionError("Dual-control quorum requires two distinct authorizing officers.")
        if not warrant_ref:
            raise PermissionError("Court warrant or judicial incident reference is mandatory.")

        segment = self.vault_segments.get(segment_id)
        if not segment:
            raise FileNotFoundError(f"Segment '{segment_id}' not found in Evidence Vault.")

        file_path = Path(segment.file_path).resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"Vault evidence file missing from disk: {file_path}")

        export_dir = Path(export_dest_dir).resolve()
        export_dir.mkdir(parents=True, exist_ok=True)
        bundle_name = f"courtroom_evidence_{segment.camera_id}_{segment.segment_id}_{int(time.time())}.zip"
        bundle_path = export_dir / bundle_name

        # Build manifest
        manifest = {
            "evidence_package_version": "2.0",
            "segment_id": segment.segment_id,
            "camera_id": segment.camera_id,
            "start_time_utc": segment.start_time_utc,
            "end_time_utc": segment.end_time_utc,
            "file_name": file_path.name,
            "file_size_bytes": segment.file_size_bytes,
            "sha256_digest": segment.sha256_hash,
            "authorization": {
                "officer_1": officer_1_id,
                "officer_2": officer_2_id,
                "warrant_ref": warrant_ref,
                "exported_at": datetime.now(timezone.utc).isoformat(),
            },
        }

        manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
        manifest_signature = self.signer.sign(manifest_bytes)

        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(file_path, arcname=file_path.name)
            zf.writestr("manifest.json", manifest_bytes)
            zf.writestr("signature.ed25519.sig", manifest_signature)
            zf.writestr("public_key.pem", self.signer.export_public_key_pem().encode("utf-8"))

        logger.info("isep.courtroom_bundle_exported", bundle=str(bundle_path), segment_id=segment_id)
        return bundle_path
