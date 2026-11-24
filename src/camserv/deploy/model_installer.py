"""
camserv.deploy.model_installer
==============================

Signed AI model-weight installation and supply-chain verification.

This module closes the model supply-chain gap (Roadmap Phase 28): model weights are
distributed as an Ed25519-signed bundle and are **only** installed after the manifest
signature is verified against pinned release-authority public keys, every artifact's
SHA-256 and byte size are re-computed, and per-artifact path containment is enforced.

The installer is *fail-closed*: any missing trust anchor, invalid signature, digest
mismatch, path traversal attempt, or unmanifested payload file aborts installation and
leaves no partially-installed artifacts behind (atomic staging + rollback).

Usage:
    camserv-install-models generate --source-dir models/bin \\
        --signing-key-hex <64-hex> --output camserv-models.bundle [--metadata meta.json]

    camserv-install-models install camserv-models.bundle \\
        --target models/bin --trusted-key <64-hex> [--overwrite]

    camserv-install-models verify camserv-models.bundle --trusted-key <64-hex>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

logger = structlog.get_logger(__name__)

MANIFEST_FILENAME = "models.manifest.json"
PAYLOAD_PREFIX = "models/"
_READ_CHUNK = 1 << 20  # 1 MiB streaming hash window
_HEX_KEY_BYTES = 32
_BACKUP_SUFFIX = ".camserv-backup"


class ModelSignatureError(PermissionError):
    """Raised when a model bundle lacks a valid signature from a trusted authority."""


class ModelBundleIntegrityError(ValueError):
    """Raised when an artifact fails SHA-256/size verification or path containment."""


class ModelInstallError(RuntimeError):
    """Raised when verified artifacts cannot be installed atomically."""


def _strip_hex_key(value: str) -> str:
    """Normalize an Ed25519 public key given as hex (with an optional ``0x`` prefix)."""
    cleaned = value.strip().lower()
    if cleaned.startswith("0x"):
        cleaned = cleaned[2:]
    return cleaned


def _validate_public_key_hex(value: str) -> str:
    """Validate a 32-byte Ed25519 public key supplied as 64 hex characters."""
    cleaned = _strip_hex_key(value)
    try:
        raw = bytes.fromhex(cleaned)
    except ValueError as exc:
        raise ModelSignatureError(f"Trusted model key is not valid hex: {exc}") from exc
    if len(raw) != _HEX_KEY_BYTES:
        raise ModelSignatureError(
            f"Trusted model key must be {_HEX_KEY_BYTES} bytes ({_HEX_KEY_BYTES * 2} hex chars), "
            f"got {len(raw)} bytes."
        )
    ed25519.Ed25519PublicKey.from_public_bytes(raw)  # validate curve point encoding
    return cleaned


def load_private_key(
    signing_key_hex: str | None = None,
    signing_key_file: str | Path | None = None,
) -> ed25519.Ed25519PrivateKey:
    """Load an Ed25519 private key from a hex seed (64 hex chars) or a PEM file."""
    if bool(signing_key_hex) == bool(signing_key_file):
        raise ValueError("Provide exactly one of 'signing_key_hex' or 'signing_key_file'.")

    if signing_key_hex:
        raw = bytes.fromhex(_strip_hex_key(signing_key_hex))
        if len(raw) != _HEX_KEY_BYTES:
            raise ValueError(
                f"Signing key hex must be {_HEX_KEY_BYTES} bytes ({_HEX_KEY_BYTES * 2} hex chars)."
            )
        return ed25519.Ed25519PrivateKey.from_private_bytes(raw)

    assert signing_key_file is not None  # narrowed by the XOR check above
    pem = Path(signing_key_file).read_bytes()
    loaded = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(loaded, ed25519.Ed25519PrivateKey):
        raise TypeError("Signing key file is not an Ed25519 private key.")
    return loaded


@dataclass(slots=True)
class ModelArtifact:
    """A single model weight file described by the signed manifest."""

    file_name: str
    sha256: str
    size: int
    name: str = ""
    version: str = ""
    task: str = ""
    license: str = ""
    provenance: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the canonical dictionary form used inside the manifest."""
        return {
            "file_name": self.file_name,
            "sha256": self.sha256,
            "size": self.size,
            "name": self.name,
            "version": self.version,
            "task": self.task,
            "license": self.license,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelArtifact:
        """Rebuild an artifact from its dictionary form."""
        return cls(
            file_name=str(data["file_name"]),
            sha256=str(data["sha256"]).lower(),
            size=int(data["size"]),
            name=str(data.get("name", "")),
            version=str(data.get("version", "")),
            task=str(data.get("task", "")),
            license=str(data.get("license", "")),
            provenance=str(data.get("provenance", "")),
        )


@dataclass(slots=True)
class ModelManifest:
    """Cryptographically signed manifest describing a bundle of model weights."""

    bundle_id: str = "camserv-models"
    models_version: str = ""
    created_at: float = field(default_factory=time.time)
    artifacts: list[ModelArtifact] = field(default_factory=list)
    signature_hex: str = ""

    def compute_signing_bytes(self) -> bytes:
        """Compute the canonical byte string signed by the release authority."""
        artifacts_canonical = [artifact.to_dict() for artifact in self.artifacts]
        artifacts_hash = hashlib.sha256(
            json.dumps(artifacts_canonical, sort_keys=True).encode("utf-8")
        ).hexdigest()
        canonical = (
            f"MODELS_V1|{self.bundle_id}|{self.models_version}|"
            f"{int(self.created_at)}|{artifacts_hash}"
        )
        return canonical.encode("utf-8")

    def sign(self, private_key: ed25519.Ed25519PrivateKey) -> None:
        """Sign the manifest with the release-authority private key."""
        self.signature_hex = private_key.sign(self.compute_signing_bytes()).hex()

    def verify(self, public_key_hex: str) -> bool:
        """Verify the manifest signature against a trusted public key (fail-closed)."""
        if not self.signature_hex:
            return False
        try:
            pub_key = ed25519.Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(_strip_hex_key(public_key_hex))
            )
            pub_key.verify(bytes.fromhex(self.signature_hex), self.compute_signing_bytes())
            return True
        except Exception as exc:
            logger.warning("model_installer.signature_verification_failed", error=str(exc))
            return False

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full manifest, including its signature, to JSON-ready data."""
        return {
            "bundle_id": self.bundle_id,
            "models_version": self.models_version,
            "created_at": self.created_at,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "signature_hex": self.signature_hex,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelManifest:
        """Rebuild a manifest from its serialized dictionary form."""
        return cls(
            bundle_id=str(data.get("bundle_id", "camserv-models")),
            models_version=str(data.get("models_version", "")),
            created_at=float(data.get("created_at", 0.0)),
            artifacts=[ModelArtifact.from_dict(item) for item in data.get("artifacts", [])],
            signature_hex=str(data.get("signature_hex", "")),
        )


class SignedModelInstaller:
    """Verifies and atomically installs Ed25519-signed model-weight bundles."""

    def __init__(self, trusted_model_keys: list[str]) -> None:
        normalized = [
            _validate_public_key_hex(key) for key in trusted_model_keys if key and key.strip()
        ]
        if not normalized:
            raise ValueError(
                "At least one trusted model-authority public key is required (fail-closed)."
            )
        self.trusted_model_keys: list[str] = normalized

    @classmethod
    def from_trust_anchors(cls, anchors: Iterable[Any]) -> SignedModelInstaller:
        """Build an installer from resolved hardware/software trust anchors.

        Anchors are produced by :class:`camserv.security.key_anchor.KeyAnchorResolver`
        (TPM 2.0 / PKCS#11 HSM) and must expose Ed25519 public keys; any other
        algorithm is rejected so the signature scheme cannot be silently downgraded.
        """
        from camserv.security.key_anchor import TrustAnchor

        keys: list[str] = []
        for anchor in anchors:
            if not isinstance(anchor, TrustAnchor):
                raise ModelSignatureError(
                    "Trust anchors must be camserv.security.key_anchor.TrustAnchor instances."
                )
            if not anchor.is_ed25519:
                raise ModelSignatureError(
                    f"Anchor '{anchor.purpose}' uses {anchor.algorithm}; model bundles "
                    "require Ed25519 trust anchors."
                )
            keys.append(anchor.public_key_hex())
        return cls(keys)


    # ------------------------------------------------------------------
    # Bundle creation (release authority side)
    # ------------------------------------------------------------------
    @classmethod
    def create_bundle(
        cls,
        source_files: dict[str, Path],
        manifest: ModelManifest,
        signing_key: ed25519.Ed25519PrivateKey,
        output_bundle_path: str | Path,
        metadata: dict[str, dict[str, str]] | None = None,
    ) -> Path:
        """Build and cryptographically sign a model-weight bundle from local files."""
        if not source_files:
            raise ValueError("At least one model file is required to build a bundle.")

        meta = metadata or {}
        normalized_sources: dict[str, Path] = {}
        artifacts: list[ModelArtifact] = []
        for file_name, src in source_files.items():
            rel = cls._safe_relative_name(file_name)
            if rel in normalized_sources:
                raise ValueError(f"Duplicate model file name after normalization: '{rel}'.")
            path = Path(src)
            if not path.is_file():
                raise FileNotFoundError(f"Model file not found: {src}")
            normalized_sources[rel] = path
            info = meta.get(rel, {})
            if not isinstance(info, dict):
                raise ValueError(f"Metadata for '{rel}' must be a JSON object.")
            artifacts.append(
                ModelArtifact(
                    file_name=rel,
                    sha256=cls._hash_file(path),
                    size=path.stat().st_size,
                    name=str(info.get("name", "")),
                    version=str(info.get("version", "")),
                    task=str(info.get("task", "")),
                    license=str(info.get("license", "")),
                    provenance=str(info.get("provenance", "")),
                )
            )

        manifest.artifacts = artifacts
        manifest.sign(signing_key)

        out = Path(output_bundle_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=".camserv-models-", suffix=".tmp", dir=str(out.parent)
        )
        os.close(tmp_fd)
        tmp_path = Path(tmp_name)
        try:
            with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for artifact in artifacts:
                    zf.write(
                        normalized_sources[artifact.file_name],
                        arcname=PAYLOAD_PREFIX + artifact.file_name,
                    )
                zf.writestr(
                    MANIFEST_FILENAME,
                    json.dumps(manifest.to_dict(), indent=2, sort_keys=True),
                )
            os.replace(tmp_path, out)
        finally:
            tmp_path.unlink(missing_ok=True)

        logger.info(
            "model_installer.bundle_created",
            bundle_id=manifest.bundle_id,
            path=str(out),
            artifacts=len(artifacts),
        )
        return out

    # ------------------------------------------------------------------
    # Verification (appliance side)
    # ------------------------------------------------------------------
    def verify_bundle(self, bundle_path: str | Path) -> ModelManifest:
        """Verify signature, artifact digests/sizes, and path containment of a bundle."""
        bundle = Path(bundle_path)
        if not bundle.is_file():
            raise FileNotFoundError(f"Model bundle not found: {bundle_path}")

        with zipfile.ZipFile(bundle, "r") as zf:
            names = zf.namelist()
            if MANIFEST_FILENAME not in names:
                raise ModelBundleIntegrityError(
                    f"Malformed model bundle: missing '{MANIFEST_FILENAME}'."
                )
            try:
                manifest = ModelManifest.from_dict(
                    json.loads(zf.read(MANIFEST_FILENAME).decode("utf-8"))
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ModelBundleIntegrityError(f"Corrupt '{MANIFEST_FILENAME}': {exc}") from exc

            if not manifest.artifacts:
                raise ModelBundleIntegrityError("Model manifest declares no artifacts.")

            # 1. Fail-closed signature verification against pinned trust anchors.
            if not any(manifest.verify(key) for key in self.trusted_model_keys):
                logger.critical(
                    "model_installer.untrusted_bundle_rejected",
                    bundle_id=manifest.bundle_id,
                    path=str(bundle),
                )
                raise ModelSignatureError(
                    "CRITICAL SECURITY REJECTION: model bundle signature is invalid or not "
                    "signed by a trusted authority."
                )

            # 2. Path containment, presence, size and digest for every artifact.
            expected_members: set[str] = set()
            seen: set[str] = set()
            for artifact in manifest.artifacts:
                rel = self._safe_relative_name(artifact.file_name)
                if rel in seen:
                    raise ModelBundleIntegrityError(
                        f"Duplicate artifact declared in manifest: '{rel}'."
                    )
                seen.add(rel)
                member = PAYLOAD_PREFIX + rel
                expected_members.add(member)
                if member not in names:
                    raise ModelBundleIntegrityError(
                        f"Declared artifact missing from bundle: '{rel}'."
                    )
                actual_size = zf.getinfo(member).file_size
                if actual_size != artifact.size:
                    raise ModelBundleIntegrityError(
                        f"Size mismatch for '{rel}': manifest={artifact.size}, "
                        f"bundle={actual_size}."
                    )
                actual_hash = self._hash_zip_member(zf, member)
                if actual_hash.lower() != artifact.sha256.lower():
                    logger.critical(
                        "model_installer.digest_mismatch",
                        file=rel,
                        expected=artifact.sha256,
                        actual=actual_hash,
                    )
                    raise ModelBundleIntegrityError(
                        f"SHA-256 mismatch for '{rel}': manifest={artifact.sha256}, "
                        f"bundle={actual_hash}."
                    )

            # 3. Reject unmanifested payload files (bundle smuggling defense).
            actual_payload = {
                name
                for name in names
                if name.startswith(PAYLOAD_PREFIX) and not name.endswith("/")
            }
            smuggled = actual_payload - expected_members
            if smuggled:
                logger.critical(
                    "model_installer.unmanifested_payload_rejected",
                    members=sorted(smuggled),
                )
                raise ModelBundleIntegrityError(
                    f"Bundle contains unmanifested payload files: {sorted(smuggled)}"
                )

        logger.info(
            "model_installer.bundle_verified",
            bundle_id=manifest.bundle_id,
            artifacts=len(manifest.artifacts),
        )
        return manifest

    # ------------------------------------------------------------------
    # Atomic installation (appliance side)
    # ------------------------------------------------------------------
    def install(
        self,
        bundle_path: str | Path,
        target_dir: str | Path,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Verify a bundle and install its artifacts atomically into ``target_dir``."""
        manifest = self.verify_bundle(bundle_path)
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        target_root = target.resolve()

        # Pre-flight: enforce overwrite policy and containment before writing anything.
        destinations: dict[str, Path] = {}
        for artifact in manifest.artifacts:
            rel = self._safe_relative_name(artifact.file_name)
            dest = (target / rel).resolve()
            if not dest.is_relative_to(target_root):
                raise ModelBundleIntegrityError(
                    f"Path containment violation for artifact '{rel}'."
                )
            if dest.exists() and not overwrite:
                raise ModelInstallError(
                    f"Refusing to overwrite existing model artifact '{dest}'. "
                    "Pass overwrite=True to replace it."
                )
            destinations[rel] = dest

        staging = Path(tempfile.mkdtemp(prefix=".camserv-models-stage-", dir=str(target)))
        placed: list[Path] = []
        backups: list[tuple[Path, Path]] = []
        try:
            # Stage every artifact on disk and re-verify the digest of the written bytes.
            staged: dict[str, Path] = {}
            with zipfile.ZipFile(Path(bundle_path), "r") as zf:
                for artifact in manifest.artifacts:
                    rel = self._safe_relative_name(artifact.file_name)
                    staged_path = staging / "payload" / rel
                    staged_path.parent.mkdir(parents=True, exist_ok=True)
                    self._extract_verified(
                        zf,
                        PAYLOAD_PREFIX + rel,
                        staged_path,
                        artifact.size,
                        artifact.sha256,
                    )
                    staged[rel] = staged_path

            # Commit with per-file backups so a mid-flight failure can be rolled back.
            for artifact in manifest.artifacts:
                rel = self._safe_relative_name(artifact.file_name)
                dest = destinations[rel]
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    backup = dest.with_name(dest.name + _BACKUP_SUFFIX)
                    os.replace(dest, backup)
                    backups.append((dest, backup))
                os.replace(staged[rel], dest)
                placed.append(dest)
        except Exception as exc:
            self._rollback(placed, backups)
            logger.error("model_installer.install_failed", error=str(exc))
            if isinstance(exc, (ModelSignatureError, ModelBundleIntegrityError, ModelInstallError)):
                raise
            raise ModelInstallError(f"Atomic model installation failed: {exc}") from exc
        else:
            for _, backup in backups:
                backup.unlink(missing_ok=True)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

        result: dict[str, Any] = {
            "bundle_id": manifest.bundle_id,
            "models_version": manifest.models_version,
            "target_dir": str(target),
            "installed": [artifact.file_name for artifact in manifest.artifacts],
            "files": [
                {
                    "file_name": artifact.file_name,
                    "sha256": artifact.sha256,
                    "size": artifact.size,
                }
                for artifact in manifest.artifacts
            ],
        }
        logger.info(
            "model_installer.install_completed",
            bundle_id=manifest.bundle_id,
            target=str(target),
            artifacts=len(result["installed"]),
        )
        return result

    @staticmethod
    def _rollback(placed: list[Path], backups: list[tuple[Path, Path]]) -> None:
        """Remove newly placed artifacts and restore any originals after a failure."""
        for dest in reversed(placed):
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                logger.error("model_installer.rollback_unlink_failed", path=str(dest))
        for dest, backup in reversed(backups):
            try:
                if backup.exists():
                    os.replace(backup, dest)
            except OSError:
                logger.error("model_installer.rollback_restore_failed", path=str(dest))

    def register_into(
        self,
        registry: Any,
        manifest: ModelManifest,
        target_dir: str | Path,
    ) -> list[Any]:
        """Register installed artifacts with a ``camserv.inference.models.ModelRegistry``."""
        from camserv.inference.models import ModelMetadata, ModelTask

        target = Path(target_dir)
        registered: list[Any] = []
        for artifact in manifest.artifacts:
            rel = self._safe_relative_name(artifact.file_name)
            path = target / rel
            if not path.is_file():
                raise ModelInstallError(f"Cannot register missing artifact: '{path}'.")
            try:
                task = ModelTask(artifact.task)
            except ValueError:
                task = ModelTask.OBJECT_DETECTION
            metadata = ModelMetadata(
                name=artifact.name or path.stem,
                version=artifact.version or manifest.models_version or "unversioned",
                task=task,
                framework=path.suffix.lstrip(".") or "onnx",
                file_path=str(path),
                input_shape=(),
                output_shape=[],
                class_names=[],
                sha256_hash=artifact.sha256,
                license=artifact.license or "UNKNOWN",
                provenance=artifact.provenance or manifest.bundle_id,
            )
            registry.register_model(metadata, verify_immediately=True)
            registered.append(metadata)
        return registered

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _safe_relative_name(name: str) -> str:
        """Normalize and validate an artifact path, rejecting traversal and absolutes."""
        if not name or "\x00" in name:
            raise ModelBundleIntegrityError("Artifact name must be a non-empty relative path.")
        normalized = name.replace("\\", "/")
        candidate = Path(normalized)
        if candidate.is_absolute() or normalized.startswith("/") or ".." in candidate.parts:
            raise ModelBundleIntegrityError(f"Unsafe artifact path rejected: '{name}'.")
        parts = [part for part in candidate.parts if part not in ("", ".")]
        if not parts:
            raise ModelBundleIntegrityError(f"Artifact name resolves to an empty path: '{name}'.")
        return "/".join(parts)

    @staticmethod
    def _hash_file(path: Path) -> str:
        """Return the SHA-256 hex digest of a file on disk using bounded memory."""
        hasher = hashlib.sha256()
        with path.open("rb") as fh:
            while chunk := fh.read(_READ_CHUNK):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def _hash_zip_member(zf: zipfile.ZipFile, member: str) -> str:
        """Return the SHA-256 hex digest of a member streamed from a zip archive."""
        hasher = hashlib.sha256()
        with zf.open(member) as fh:
            while chunk := fh.read(_READ_CHUNK):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def _extract_verified(
        zf: zipfile.ZipFile,
        member: str,
        destination: Path,
        expected_size: int,
        expected_sha256: str,
    ) -> None:
        """Stream a member to disk while re-verifying its size and SHA-256 digest."""
        hasher = hashlib.sha256()
        total = 0
        with zf.open(member) as src, destination.open("wb") as out:
            while chunk := src.read(_READ_CHUNK):
                hasher.update(chunk)
                out.write(chunk)
                total += len(chunk)
        if total != expected_size:
            raise ModelBundleIntegrityError(
                f"Size mismatch extracting '{member}': expected {expected_size}, wrote {total}."
            )
        if hasher.hexdigest().lower() != expected_sha256.lower():
            raise ModelBundleIntegrityError(f"SHA-256 mismatch extracting '{member}'.")


# ---------------------------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="camserv-install-models",
        description="Build, verify and install Ed25519-signed CAMserv model-weight bundles.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Build and sign a model-weight bundle.")
    gen.add_argument("--source-dir", required=True, help="Directory containing model weight files.")
    gen.add_argument("--output", required=True, help="Output bundle path.")
    gen.add_argument("--bundle-id", default="camserv-models", help="Logical bundle identifier.")
    gen.add_argument("--models-version", default="", help="Model-set version recorded in manifest.")
    gen.add_argument("--signing-key-hex", default=None, help="Ed25519 seed as 64 hex chars.")
    gen.add_argument("--signing-key-file", default=None, help="PEM Ed25519 private key file.")
    gen.add_argument(
        "--metadata", default=None, help="Optional JSON sidecar with per-file metadata."
    )

    inst = sub.add_parser("install", help="Verify and atomically install a signed bundle.")
    inst.add_argument("bundle", help="Signed model bundle to install.")
    inst.add_argument("--target", required=True, help="Destination model directory.")
    inst.add_argument(
        "--trusted-key", action="append", default=[], help="Trusted public key hex; repeatable."
    )
    inst.add_argument(
        "--trusted-key-file",
        action="append",
        default=[],
        help="File holding a trusted public key hex; repeatable.",
    )
    inst.add_argument("--overwrite", action="store_true", help="Replace existing artifacts.")

    ver = sub.add_parser("verify", help="Verify a signed bundle without installing it.")
    ver.add_argument("bundle")
    ver.add_argument("--trusted-key", action="append", default=[])
    ver.add_argument("--trusted-key-file", action="append", default=[])
    return parser


def _collect_trusted_keys(args: argparse.Namespace) -> list[str]:
    keys = [str(key) for key in (args.trusted_key or [])]
    for path in args.trusted_key_file or []:
        keys.append(Path(path).read_text(encoding="utf-8").strip())
    return keys


def _default_models_version() -> str:
    try:
        from camserv import __version__
    except ImportError:  # pragma: no cover - package metadata present in deployments
        return "unversioned"
    return str(__version__)


def _cmd_generate(args: argparse.Namespace) -> int:
    source_dir = Path(args.source_dir)
    if not source_dir.is_dir():
        print(f"error: source directory not found: {source_dir}", file=sys.stderr)
        return 2
    metadata: dict[str, dict[str, str]] = {}
    if args.metadata:
        loaded = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            print("error: metadata sidecar must contain a JSON object.", file=sys.stderr)
            return 2
        metadata = loaded
    source_files = {
        path.relative_to(source_dir).as_posix(): path
        for path in sorted(source_dir.rglob("*"))
        if path.is_file() and path.name != MANIFEST_FILENAME
    }
    if not source_files:
        print("error: no model files found to bundle.", file=sys.stderr)
        return 2
    signing_key = load_private_key(args.signing_key_hex, args.signing_key_file)
    manifest = ModelManifest(
        bundle_id=args.bundle_id,
        models_version=args.models_version or _default_models_version(),
    )
    bundle = SignedModelInstaller.create_bundle(
        source_files, manifest, signing_key, args.output, metadata=metadata
    )
    print(f"created signed model bundle: {bundle} ({len(source_files)} artifact(s))")
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    installer = SignedModelInstaller(_collect_trusted_keys(args))
    result = installer.install(args.bundle, args.target, overwrite=args.overwrite)
    print(
        f"installed {len(result['installed'])} verified model artifact(s) "
        f"into {result['target_dir']}"
    )
    for entry in result["files"]:
        print(f"  - {entry['file_name']}  sha256={entry['sha256']}  size={entry['size']}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    installer = SignedModelInstaller(_collect_trusted_keys(args))
    manifest = installer.verify_bundle(args.bundle)
    print(
        f"verified bundle '{manifest.bundle_id}' ({len(manifest.artifacts)} artifact(s), "
        f"models_version={manifest.models_version or 'n/a'})"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``camserv-install-models`` console script."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "generate": _cmd_generate,
        "install": _cmd_install,
        "verify": _cmd_verify,
    }
    handler = handlers.get(args.command)
    if handler is None:  # pragma: no cover - argparse enforces the subcommand
        parser.error(f"unknown command: {args.command}")
        return 2
    try:
        return handler(args)
    except (
        ModelSignatureError,
        ModelBundleIntegrityError,
        ModelInstallError,
        ValueError,
        OSError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
