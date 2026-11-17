"""
camserv.storage.isep.evidence_preservation
==========================================

Evidence Preservation Manager for CAMserv ISEP.
Enforces physical and logical isolation of the Evidence Vault from routine retention.
Manages persistent preservation holds (legal, incident, administrative), cryptographic seals,
genuine dual Ed25519 asymmetric signatures, and courtroom-admissible evidence export packaging.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
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
from camserv.storage.isep.preservation_store import PreservationStore

logger = structlog.get_logger(__name__)


class EvidencePreservationError(Exception):
    """Raised when evidence preservation constraints or integrity checks fail."""


class CourtroomBundleVerificationError(EvidencePreservationError):
    """Raised when courtroom evidence package fails cryptographic verification."""


def _set_os_read_only(file_path: Path) -> None:
    """Apply OS-level read-only file attribute to protected vault asset."""
    try:
        if os.name == "nt":
            import ctypes
            FILE_ATTRIBUTE_READONLY = 0x01
            ctypes.windll.kernel32.SetFileAttributesW(str(file_path), FILE_ATTRIBUTE_READONLY)
        else:
            os.chmod(file_path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)  # 0o444
    except Exception as exc:
        logger.warning("isep.set_readonly_attribute_failed", file=str(file_path), error=str(exc))


def _clear_os_read_only(file_path: Path) -> None:
    """Clear OS-level read-only file attribute if file exists."""
    try:
        if not file_path.exists():
            return
        if os.name == "nt":
            import ctypes
            FILE_ATTRIBUTE_NORMAL = 0x80
            ctypes.windll.kernel32.SetFileAttributesW(str(file_path), FILE_ATTRIBUTE_NORMAL)
        else:
            os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)  # 0o644
    except Exception as exc:
        logger.warning("isep.clear_readonly_attribute_failed", file=str(file_path), error=str(exc))


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
        store: PreservationStore | None = None,
    ) -> None:
        self.vault_dir = Path(vault_dir).resolve()
        self.vault_dir.mkdir(parents=True, exist_ok=True)

        self.signer = signer or ForensicSigner()
        db_path = self.vault_dir / "preservation_ledger.sqlite"
        self.store = store or PreservationStore(db_path)

        # Durably restore holds and vault segments from persistent store
        self.holds: dict[str, PreservationHold] = self.store.load_active_holds()
        self.vault_segments: dict[str, RecordingSegmentMetadata] = self.store.load_vault_segments()
        logger.info(
            "isep.evidence_manager.initialized",
            restored_holds=len(self.holds),
            restored_vault_segments=len(self.vault_segments),
        )

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
        Place an immutable, durable preservation hold on a segment or recording.
        Strictly prevents any deletion or retention purging while active.
        """
        hold_id = f"hold_{target_id}_{int(time.time()*1000)}"
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
        self.store.save_hold(hold)
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
            # Check store
            db_released = self.store.release_hold(hold_id, released_by, reason)
            return db_released

        hold.active = False
        db_released = self.store.release_hold(hold_id, released_by, reason)
        logger.info(
            "isep.preservation_hold_released",
            hold_id=hold_id,
            released_by=released_by,
            reason=reason,
        )
        return True

    def is_target_protected(self, target_id: str) -> bool:
        """
        Check whether any active preservation hold covers a segment or recording.
        FAIL-CLOSED: If persistent store checks encounter any database error,
        it evaluates to True to guarantee evidence is never inadvertently deleted.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        # Fast in-memory check
        for hold in self.holds.values():
            if hold.target_id == target_id and hold.active:
                if hold.expires_at is None or hold.expires_at > now_iso:
                    return True

        # Fallback to persistent transactional store with fail-closed guarantee
        return self.store.is_target_protected(target_id)

    def ingest_to_vault(
        self,
        segment: RecordingSegmentMetadata,
        hold_reason: str,
        authorized_by: str,
    ) -> RecordingSegmentMetadata:
        """
        Promote a segment into the protected Evidence Vault.
        Copies the file into vault directory, recalculates SHA-256, marks as vault_sealed,
        applies OS read-only filesystem lock, and persists metadata durably.
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

        # Enforce OS-level read-only file attribute
        _set_os_read_only(vault_file_path)

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
        self.store.save_vault_segment(vault_meta, hold.hold_id)

        logger.info("isep.segment_promoted_to_vault", segment_id=segment.segment_id, path=str(vault_file_path))
        return vault_meta

    def export_courtroom_evidence_bundle(
        self,
        segment_id: str,
        export_dest_dir: Path | str,
        officer_1_id: str,
        officer_2_id: str,
        warrant_ref: str,
        primary_signer: ForensicSigner | None = None,
        secondary_signer: ForensicSigner | None = None,
    ) -> Path:
        """
        Generate a cryptographically signed courtroom evidence zip package with genuine
        dual Ed25519 signatures from two independent private keys.
        Enforces dual-control officer quorum, distinct keys, and court warrant reference.
        """
        if not officer_1_id or not officer_2_id or officer_1_id.strip() == officer_2_id.strip():
            raise PermissionError("Dual-control quorum requires two distinct authorizing officers.")
        if not warrant_ref or not warrant_ref.strip():
            raise PermissionError("Court warrant or judicial incident reference is mandatory.")

        p_signer = primary_signer or self.signer
        s_signer = secondary_signer or ForensicSigner()

        # Reject duplicate public keys (must have two distinct private keys!)
        p_pub = p_signer.export_public_key_pem().strip()
        s_pub = s_signer.export_public_key_pem().strip()
        if p_pub == s_pub:
            raise PermissionError("Dual-control requires two independent cryptographic signing keys. Duplicate public key rejected.")

        segment = self.vault_segments.get(segment_id)
        if not segment:
            raise FileNotFoundError(f"Segment '{segment_id}' not found in Evidence Vault.")

        file_path = Path(segment.file_path).resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"Vault evidence file missing from disk: {file_path}")

        export_dir = Path(export_dest_dir).resolve()
        export_dir.mkdir(parents=True, exist_ok=True)
        bundle_name = f"courtroom_evidence_{segment.camera_id}_{segment.segment_id}_{int(time.time()*1000)}.zip"
        bundle_path = export_dir / bundle_name

        p_key_id = hashlib.sha256(p_pub.encode("utf-8")).hexdigest()[:16]
        s_key_id = hashlib.sha256(s_pub.encode("utf-8")).hexdigest()[:16]

        # Build canonical manifest
        manifest = {
            "canonical_version": "2.0",
            "evidence_package_version": "2.0",
            "segment_id": segment.segment_id,
            "camera_id": segment.camera_id,
            "start_time_utc": segment.start_time_utc,
            "end_time_utc": segment.end_time_utc,
            "file_name": file_path.name,
            "file_size_bytes": segment.file_size_bytes,
            "sha256_digest": segment.sha256_hash,
            "authorization": {
                "officer_primary": officer_1_id,
                "officer_secondary": officer_2_id,
                "warrant_ref": warrant_ref,
                "exported_at": datetime.now(timezone.utc).isoformat(),
            },
            "signers": {
                "primary": {
                    "officer_id": officer_1_id,
                    "algorithm": "Ed25519",
                    "key_id": p_key_id,
                },
                "secondary": {
                    "officer_id": officer_2_id,
                    "algorithm": "Ed25519",
                    "key_id": s_key_id,
                },
            },
        }

        manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
        sig_primary = p_signer.sign(manifest_bytes)
        sig_secondary = s_signer.sign(manifest_bytes)

        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(file_path, arcname=file_path.name)
            zf.writestr("manifest.json", manifest_bytes)
            zf.writestr("signature_primary.ed25519.sig", sig_primary)
            zf.writestr("signature_secondary.ed25519.sig", sig_secondary)
            zf.writestr("public_key_primary.pem", p_pub.encode("utf-8"))
            zf.writestr("public_key_secondary.pem", s_pub.encode("utf-8"))
            # Backwards-compatibility aliases
            zf.writestr("signature.ed25519.sig", sig_primary)
            zf.writestr("public_key.pem", p_pub.encode("utf-8"))

        logger.info("isep.courtroom_bundle_exported", bundle=str(bundle_path), segment_id=segment_id)
        return bundle_path


def verify_ed25519_signature(data: bytes, signature: bytes, public_key_pem: str) -> bool:
    """Verify arbitrary binary payload against Ed25519 signature and PEM public key."""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519

        pub_key = serialization.load_pem_public_key(public_key_pem.strip().encode("utf-8"))
        if not isinstance(pub_key, ed25519.Ed25519PublicKey):
            return False
        pub_key.verify(signature, data)
        return True
    except Exception:
        return False


def verify_courtroom_bundle(bundle_path: Path | str) -> dict[str, Any]:
    """
    Independently inspect and cryptographically verify a courtroom evidence package.
    Validates:
      1. ZIP package container integrity.
      2. Absence of private keys.
      3. Exact video file SHA-256 match against manifest.
      4. Dual distinct Ed25519 public keys.
      5. Primary signature cryptographic validity over manifest.
      6. Secondary signature cryptographic validity over manifest.
      7. Dual distinct officer identities.
    """
    bp = Path(bundle_path).resolve()
    if not bp.is_file():
        raise FileNotFoundError(f"Courtroom bundle file not found: {bp}")

    with zipfile.ZipFile(bp, "r") as zf:
        namelist = zf.namelist()

        # Check for private keys (strictly forbidden)
        for name in namelist:
            if "private" in name.lower() or name.endswith(".key"):
                raise CourtroomBundleVerificationError(f"Security violation: bundle contains private key artifact: {name}")

        required_files = [
            "manifest.json",
            "signature_primary.ed25519.sig",
            "signature_secondary.ed25519.sig",
            "public_key_primary.pem",
            "public_key_secondary.pem",
        ]
        for req in required_files:
            if req not in namelist:
                raise CourtroomBundleVerificationError(f"Missing mandatory evidence artifact in bundle: {req}")

        # 1. Read manifest
        manifest_bytes = zf.read("manifest.json")
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except Exception as exc:
            raise CourtroomBundleVerificationError(f"Corrupt manifest.json in bundle: {exc}") from exc

        video_name = manifest.get("file_name")
        if not video_name or video_name not in namelist:
            raise CourtroomBundleVerificationError(f"Video file '{video_name}' referenced in manifest not found in package.")

        # 2. Verify video SHA-256
        video_bytes = zf.read(video_name)
        calc_sha256 = hashlib.sha256(video_bytes).hexdigest()
        expected_sha256 = manifest.get("sha256_digest")
        if calc_sha256 != expected_sha256:
            raise CourtroomBundleVerificationError(
                f"Video payload checksum mismatch: expected {expected_sha256}, calculated {calc_sha256}."
            )

        # 3. Read signatures and public keys
        sig_primary = zf.read("signature_primary.ed25519.sig")
        sig_secondary = zf.read("signature_secondary.ed25519.sig")
        pub_primary_pem = zf.read("public_key_primary.pem").decode("utf-8").strip()
        pub_secondary_pem = zf.read("public_key_secondary.pem").decode("utf-8").strip()

        # 4. Reject identical public keys
        if pub_primary_pem == pub_secondary_pem:
            raise CourtroomBundleVerificationError("Cryptographic dual-control violation: primary and secondary public keys are identical.")

        # 5. Check distinct officer identities
        auth = manifest.get("authorization", {})
        off_1 = auth.get("officer_primary")
        off_2 = auth.get("officer_secondary")
        if not off_1 or not off_2 or off_1 == off_2:
            raise CourtroomBundleVerificationError("Dual-control quorum violation: officer identities must be distinct.")

        # 6. Verify signatures
        primary_valid = verify_ed25519_signature(manifest_bytes, sig_primary, pub_primary_pem)
        if not primary_valid:
            raise CourtroomBundleVerificationError("Primary Ed25519 signature verification failed.")

        secondary_valid = verify_ed25519_signature(manifest_bytes, sig_secondary, pub_secondary_pem)
        if not secondary_valid:
            raise CourtroomBundleVerificationError("Secondary Ed25519 signature verification failed.")

        return {
            "is_valid": True,
            "segment_id": manifest.get("segment_id"),
            "camera_id": manifest.get("camera_id"),
            "file_name": video_name,
            "sha256_digest": calc_sha256,
            "officer_primary": off_1,
            "officer_secondary": off_2,
            "warrant_ref": auth.get("warrant_ref"),
            "primary_key_id": hashlib.sha256(pub_primary_pem.encode()).hexdigest()[:16],
            "secondary_key_id": hashlib.sha256(pub_secondary_pem.encode()).hexdigest()[:16],
            "verification_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
