"""
camserv.deploy.updater
======================

Signed Over-The-Air (OTA) software update engine, Ed25519 manifest verification,
channel gating (Stable/Testing/Dev), version compatibility checking, and atomic rollback.
"""

from __future__ import annotations

import enum
import hashlib
import json
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
from cryptography.hazmat.primitives.asymmetric import ed25519

logger = structlog.get_logger(__name__)


class DeploymentChannel(str, enum.Enum):
    """Staged rollout channels."""

    STABLE = "stable"
    TESTING = "testing"
    DEVELOPMENT = "development"


class UpdateSignatureError(PermissionError):
    """Raised when an update package lacks a valid cryptographic release signature."""


class VersionIncompatibilityError(ValueError):
    """Raised when the host version is incompatible with the update package."""


class PackageIntegrityError(ValueError):
    """Raised when payload file SHA-256 hash does not match the signed manifest."""


@dataclass(slots=True)
class UpdatePackageManifest:
    """Cryptographically signed release metadata manifest."""

    package_id: str
    target_version: str
    minimum_supported_version: str
    channel: DeploymentChannel
    files: list[dict[str, Any]]
    created_at: float = field(default_factory=time.time)
    signature_hex: str = ""

    def compute_signing_bytes(self) -> bytes:
        """Compute canonical byte string for Ed25519 signature verification."""
        files_canonical = json.dumps(self.files, sort_keys=True)
        files_hash = hashlib.sha256(files_canonical.encode("utf-8")).hexdigest()

        canonical_str = (
            f"UPDATE_V1|{self.package_id}|{self.target_version}|"
            f"{self.minimum_supported_version}|{self.channel.value}|"
            f"{int(self.created_at)}|{files_hash}"
        )
        return canonical_str.encode("utf-8")

    def sign(self, private_key: ed25519.Ed25519PrivateKey) -> None:
        """Sign manifest with official release authority private key."""
        sig = private_key.sign(self.compute_signing_bytes())
        self.signature_hex = sig.hex()

    def verify(self, public_key_hex: str) -> bool:
        """Verify manifest signature against a trusted release authority public key."""
        if not self.signature_hex:
            return False
        try:
            pub_key = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
            pub_key.verify(bytes.fromhex(self.signature_hex), self.compute_signing_bytes())
            return True
        except Exception as e:
            logger.warning("updater.signature_verification_failed", error=str(e))
            return False


class SignedUpdateManager:
    """
    Manages generation, validation, staged application, and atomic rollback
    of signed OTA update bundles.
    """

    def __init__(self, trusted_release_keys: list[str]) -> None:
        self.trusted_release_keys = trusted_release_keys

    @classmethod
    def create_update_package(
        cls,
        payload_files: dict[str, bytes],
        manifest: UpdatePackageManifest,
        signing_key: ed25519.Ed25519PrivateKey,
        output_pkg_path: Path | str,
    ) -> Path:
        """Build and cryptographically sign an update bundle (.camserv-upd / .zip)."""
        pkg_path = Path(output_pkg_path)
        pkg_path.parent.mkdir(parents=True, exist_ok=True)

        # Compute files metadata list
        files_meta = []
        for rel_path, data in payload_files.items():
            f_hash = hashlib.sha256(data).hexdigest()
            files_meta.append({"path": rel_path, "sha256": f_hash, "size": len(data)})

        manifest.files = files_meta
        manifest.sign(signing_key)

        with zipfile.ZipFile(str(pkg_path), "w", zipfile.ZIP_DEFLATED) as zf:
            # Write payload files
            for rel_path, data in payload_files.items():
                zf.writestr(f"payload/{rel_path}", data)

            # Write manifest JSON
            manifest_dict = {
                "package_id": manifest.package_id,
                "target_version": manifest.target_version,
                "minimum_supported_version": manifest.minimum_supported_version,
                "channel": manifest.channel.value,
                "files": manifest.files,
                "created_at": manifest.created_at,
                "signature_hex": manifest.signature_hex,
            }
            zf.writestr("manifest.json", json.dumps(manifest_dict, indent=2))

        logger.info("updater.package_created", package_id=manifest.package_id, path=str(pkg_path))
        return pkg_path

    def verify_and_stage_package(
        self,
        pkg_path: Path | str,
        current_version: str,
        allowed_channel: DeploymentChannel = DeploymentChannel.STABLE,
    ) -> UpdatePackageManifest:
        """
        Verify cryptographic release signature, version compatibility,
        channel authorization, and payload integrity before extraction.
        """
        p = Path(pkg_path)
        if not p.exists():
            raise FileNotFoundError(f"Update package '{pkg_path}' not found.")

        with zipfile.ZipFile(str(p), "r") as zf:
            if "manifest.json" not in zf.namelist():
                raise UpdateSignatureError("Malformed package: Missing 'manifest.json'.")

            manifest_data = json.loads(zf.read("manifest.json").decode("utf-8"))

            manifest = UpdatePackageManifest(
                package_id=manifest_data["package_id"],
                target_version=manifest_data["target_version"],
                minimum_supported_version=manifest_data["minimum_supported_version"],
                channel=DeploymentChannel(manifest_data["channel"]),
                files=manifest_data["files"],
                created_at=manifest_data["created_at"],
                signature_hex=manifest_data.get("signature_hex", ""),
            )

            # 1. Verify channel
            if manifest.channel != allowed_channel and allowed_channel == DeploymentChannel.STABLE:
                raise ValueError(
                    f"Channel mismatch: Device is on '{allowed_channel.value}' but update is '{manifest.channel.value}'."
                )

            # 2. Version compatibility check
            if not self._is_version_compatible(current_version, manifest.minimum_supported_version):
                raise VersionIncompatibilityError(
                    f"Host version '{current_version}' is below required minimum '{manifest.minimum_supported_version}'."
                )

            # 3. Cryptographic signature check against trusted keys
            signature_valid = False
            for pub_key in self.trusted_release_keys:
                if manifest.verify(pub_key):
                    signature_valid = True
                    break

            if not signature_valid:
                logger.critical("updater.untrusted_package_rejected", package_id=manifest.package_id)
                raise UpdateSignatureError(
                    "CRITICAL SECURITY REJECTION: Update package signature is invalid or not signed by a trusted release authority."
                )

            # 4. Verify SHA-256 digest of each payload file and reject path traversal
            manifest_paths = set()
            for f_entry in manifest.files:
                f_path = f_entry["path"]
                if ".." in f_path or f_path.startswith("/") or f_path.startswith("\\"):
                    logger.critical("updater.path_traversal_manifest_rejected", path=f_path)
                    raise PackageIntegrityError(f"Security error: Path traversal detected in manifest path '{f_path}'.")

                manifest_paths.add(f"payload/{f_path}")
                arc_name = f"payload/{f_path}"
                if arc_name not in zf.namelist():
                    raise PackageIntegrityError(f"Missing file in archive: {f_path}")

                content = zf.read(arc_name)
                calc_hash = hashlib.sha256(content).hexdigest()
                if calc_hash != f_entry["sha256"]:
                    logger.critical("updater.checksum_mismatch", path=f_entry["path"])
                    raise PackageIntegrityError(f"Checksum mismatch for '{f_entry['path']}': Tampered payload detected.")

            # Ensure no unexpected or malicious unmanifested payload entries exist
            for name in zf.namelist():
                if name.startswith("payload/") and name != "payload/":
                    if name not in manifest_paths:
                        logger.critical("updater.unmanifested_payload_rejected", file=name)
                        raise PackageIntegrityError(f"Security error: Unmanifested file in payload archive: '{name}'.")

        logger.info("updater.package_verified_successfully", package_id=manifest.package_id)
        return manifest

    def apply_update_with_atomic_rollback(
        self,
        pkg_path: Path | str,
        target_dir: Path | str,
        backup_dir: Path | str,
        simulate_post_health_fail: bool = False,
    ) -> bool:
        """
        Extract verified package. If post-install health check fails,
        atomically rolls back to the previous snapshot.
        """
        dest = Path(target_dir).resolve()
        b_dir = Path(backup_dir).resolve()
        dest.mkdir(parents=True, exist_ok=True)
        b_dir.mkdir(parents=True, exist_ok=True)

        # Snapshot existing target before extraction
        snapshot_id = int(time.time())
        snapshot_dest = b_dir / f"snapshot_{snapshot_id}"
        if dest.exists() and any(dest.iterdir()):
            shutil.copytree(dest, snapshot_dest)

        try:
            with zipfile.ZipFile(str(pkg_path), "r") as zf:
                for name in zf.namelist():
                    if name.startswith("payload/") and name != "payload/":
                        rel_path = name[len("payload/"):]
                        out_path = (dest / rel_path).resolve()

                        # Enforce path containment to prevent Zip Slip directory escapes
                        try:
                            out_path.relative_to(dest)
                        except ValueError:
                            logger.critical("updater.zip_slip_blocked", path=rel_path)
                            raise PackageIntegrityError(
                                f"CRITICAL SECURITY REJECTION: Zip Slip path traversal attempted: '{rel_path}'."
                            )

                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        out_path.write_bytes(zf.read(name))

            # Simulate post-installation health probe
            if simulate_post_health_fail:
                raise RuntimeError("Simulated post-install service crash during health check.")

            logger.info("updater.update_applied_successfully", target=str(dest))
            return True

        except Exception as e:
            logger.critical("updater.health_check_failed_rolling_back", error=str(e))
            # Atomic rollback: Restore from snapshot
            if snapshot_dest.exists():
                shutil.rmtree(dest)
                shutil.copytree(snapshot_dest, dest)
                logger.warning("updater.rollback_completed", restored_from=str(snapshot_dest))
            return False

    @staticmethod
    def _is_version_compatible(current_ver: str, min_ver: str) -> bool:
        """Compare semver strings (major.minor.patch)."""
        def parse_v(v: str) -> tuple[int, ...]:
            parts = v.strip().lstrip("v").split(".")
            return tuple(int(p) if p.isdigit() else 0 for p in parts[:3])

        return parse_v(current_ver) >= parse_v(min_ver)
