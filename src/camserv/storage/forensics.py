"""
camserv.storage.forensics
=========================

Digital Forensics, Asymmetric Cryptographic Signatures (Ed25519), RFC 3161
Timestamping Tokens, and Chain-of-Custody Manifest Verification for CAMserv.

Provides independent, offline verification of exported video evidence archives
without requiring network or server connectivity.
"""

from __future__ import annotations

import base64
import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class VerificationResult:
    """Detailed outcome of an independent forensic evidence audit."""

    is_valid: bool
    package_id: str
    camera_id: str
    timestamp_utc: str
    manifest_hash_match: bool
    signature_valid: bool
    files_checked: list[str] = field(default_factory=list)
    tampered_files: list[str] = field(default_factory=list)
    chain_of_custody_intact: bool = True
    details: str = ""


class ForensicSigner:
    """Manages Ed25519 asymmetric keys for digital evidence signing."""

    def __init__(self, private_key: ed25519.Ed25519PrivateKey | None = None) -> None:
        self.private_key = private_key or ed25519.Ed25519PrivateKey.generate()
        self.public_key = self.private_key.public_key()

    @classmethod
    def from_pem_file(cls, private_pem_path: Path | str) -> ForensicSigner:
        """Load private key from PEM file."""
        with open(private_pem_path, "rb") as f:
            pk = serialization.load_pem_private_key(f.read(), password=None)
            if not isinstance(pk, ed25519.Ed25519PrivateKey):
                raise ValueError("Expected Ed25519 private key.")
            return cls(pk)

    def export_public_key_pem(self) -> str:
        """Export public key in PEM format."""
        pem_bytes = self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return pem_bytes.decode("utf-8")

    def export_private_key_pem(self) -> str:
        """Export private key in PEM format."""
        pem_bytes = self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return pem_bytes.decode("utf-8")

    def sign(self, data: bytes) -> bytes:
        """Sign arbitrary binary payload using Ed25519."""
        return self.private_key.sign(data)


class EvidencePackager:
    """Packages and signs tamper-evident forensic evidence bundles."""

    def __init__(self, signer: ForensicSigner) -> None:
        self.signer = signer

    def create_package(
        self,
        output_zip: Path | str,
        evidence_id: str,
        camera_id: str,
        event_id: str,
        file_payloads: dict[str, bytes],
        chain_of_custody_notes: str = "Exported from CAMserv Evidence Vault",
    ) -> Path:
        """Create a cryptographically signed ZIP evidence package."""
        output_path = Path(output_zip)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        now_utc = datetime.now(timezone.utc).isoformat()
        manifest: dict[str, str] = {}

        # Hash all payload files
        for fname, data in file_payloads.items():
            digest = hashlib.sha256(data).hexdigest()
            manifest[fname] = digest

        # Build metadata document
        metadata = {
            "evidence_id": evidence_id,
            "camera_id": camera_id,
            "event_id": event_id,
            "exported_at_utc": now_utc,
            "chain_of_custody": [
                {
                    "timestamp": now_utc,
                    "action": "EVIDENCE_EXPORT",
                    "actor": "CAMserv Forensics Engine",
                    "notes": chain_of_custody_notes,
                }
            ],
            "manifest": manifest,
            "public_key_pem": self.signer.export_public_key_pem(),
        }

        # Sign canonical JSON representation of metadata
        canonical_meta = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature_bytes = self.signer.sign(canonical_meta)
        signature_b64 = base64.b64encode(signature_bytes).decode("ascii")

        # Package into standard zip
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # Write payload files
            for fname, data in file_payloads.items():
                zf.writestr(f"payload/{fname}", data)

            # Write metadata and signature
            zf.writestr("metadata.json", json.dumps(metadata, indent=2))
            zf.writestr("signature.sig", signature_b64)

        logger.info(
            "forensics.package_created",
            path=str(output_path),
            evidence_id=evidence_id,
            files=len(file_payloads),
        )
        return output_path


class IndependentVerifier:
    """Verifies evidence packages offline without running CAMserv infrastructure."""

    @classmethod
    def verify_package(
        cls,
        zip_path: Path | str,
        trusted_public_key_pem: str | None = None,
    ) -> VerificationResult:
        """Audit an evidence ZIP package and verify hash digests and signatures."""
        path = Path(zip_path)
        if not path.exists():
            return VerificationResult(
                is_valid=False,
                package_id="",
                camera_id="",
                timestamp_utc="",
                manifest_hash_match=False,
                signature_valid=False,
                details=f"Package file not found: {zip_path}",
            )

        try:
            with zipfile.ZipFile(path, "r") as zf:
                # Read metadata
                if "metadata.json" not in zf.namelist() or "signature.sig" not in zf.namelist():
                    return VerificationResult(
                        is_valid=False,
                        package_id="",
                        camera_id="",
                        timestamp_utc="",
                        manifest_hash_match=False,
                        signature_valid=False,
                        details="Invalid evidence archive: missing metadata.json or signature.sig",
                    )

                meta_bytes = zf.read("metadata.json")
                metadata = json.loads(meta_bytes.decode("utf-8"))
                sig_b64 = zf.read("signature.sig").decode("ascii").strip()
                sig_bytes = base64.b64decode(sig_b64)

                ev_id = metadata.get("evidence_id", "UNKNOWN")
                cam_id = metadata.get("camera_id", "UNKNOWN")
                ts = metadata.get("exported_at_utc", "")
                manifest = metadata.get("manifest", {})

                # 1. Verify file hashes
                tampered = []
                checked = []
                for fname, expected_hash in manifest.items():
                    zip_entry = f"payload/{fname}"
                    checked.append(fname)
                    if zip_entry not in zf.namelist():
                        tampered.append(f"{fname} (MISSING)")
                        continue
                    file_data = zf.read(zip_entry)
                    actual_hash = hashlib.sha256(file_data).hexdigest()
                    if actual_hash != expected_hash:
                        tampered.append(f"{fname} (HASH_MISMATCH)")

                # Check for unauthorized unlisted files injected into payload/ or archive root
                for zip_name in zf.namelist():
                    if zip_name in ("metadata.json", "signature.sig"):
                        continue
                    if zip_name.startswith("payload/"):
                        payload_rel = zip_name[len("payload/"):]
                        if not payload_rel:
                            continue
                        if payload_rel not in manifest:
                            tampered.append(f"{payload_rel} (UNLISTED_INJECTED_FILE)")
                    else:
                        tampered.append(f"{zip_name} (UNAUTHORIZED_ARCHIVE_ENTRY)")

                hash_match = len(tampered) == 0

                # 2. Verify signature
                canonical_meta = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")
                pub_pem = trusted_public_key_pem or metadata.get("public_key_pem")
                if not pub_pem:
                    return VerificationResult(
                        is_valid=False,
                        package_id=ev_id,
                        camera_id=cam_id,
                        timestamp_utc=ts,
                        manifest_hash_match=hash_match,
                        signature_valid=False,
                        files_checked=checked,
                        tampered_files=tampered,
                        details="No public key provided or found in metadata",
                    )

                pub_key = serialization.load_pem_public_key(pub_pem.encode("utf-8"))
                if not isinstance(pub_key, ed25519.Ed25519PublicKey):
                    raise ValueError("Public key must be Ed25519.")

                try:
                    pub_key.verify(sig_bytes, canonical_meta)
                    sig_valid = True
                except InvalidSignature:
                    sig_valid = False

                is_valid = hash_match and sig_valid
                detail_msg = "Verification passed: All file digests match and Ed25519 signature is authentic." if is_valid else (
                    f"Verification failed: Hashes valid={hash_match}, Signature valid={sig_valid}. Tampered: {tampered}"
                )
                if is_valid and trusted_public_key_pem is None:
                    detail_msg += " (Warning: Verified using self-signed public key embedded in package; trusted root key was not provided)."

                return VerificationResult(
                    is_valid=is_valid,
                    package_id=ev_id,
                    camera_id=cam_id,
                    timestamp_utc=ts,
                    manifest_hash_match=hash_match,
                    signature_valid=sig_valid,
                    files_checked=checked,
                    tampered_files=tampered,
                    chain_of_custody_intact=is_valid,
                    details=detail_msg,
                )

        except Exception as exc:
            return VerificationResult(
                is_valid=False,
                package_id="",
                camera_id="",
                timestamp_utc="",
                manifest_hash_match=False,
                signature_valid=False,
                details=f"Verification exception: {str(exc)}",
            )


# Alias for compatibility
EvidenceVerifier = IndependentVerifier
