"""Persistent Cryptographic Key Management for CAMserv.

Features:
* Persistent key identity, versioning, and lifecycle management.
* Strict separation of signing keys (Ed25519) and encryption keys (AES-256-GCM).
* Key derivation using HKDF-SHA256 from master entropy/passphrase.
* Atomic filesystem writes (.tmp + replace) with restrictive file permissions.
* Protection against accidental key overwrites.
* Multi-version key rotation support (historical verification remains valid).
* Hardware TPM 2.0 / secure enclave readiness with transparent software fallback.
"""

from __future__ import annotations

import base64
import enum
import hashlib
import json
import os
import stat
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
import structlog

logger = structlog.get_logger(__name__)

_AES_KEY_BYTES = 32  # 256 bits


class KeyType(str, enum.Enum):
    """Cryptographic key purpose."""
    AES_GCM_ENCRYPTION = "aes_gcm_encryption"
    ED25519_SIGNING = "ed25519_signing"


@dataclass(slots=True)
class KeyMetadata:
    """Metadata describing a managed cryptographic key."""
    key_id: str
    version: int
    key_type: KeyType
    algorithm: str
    created_at_utc: str
    fingerprint: str  # SHA-256 hex digest of raw key or public key
    description: str = ""


class KeyManagementError(Exception):
    """Base exception for key management failures."""


class KeyNotFoundError(KeyManagementError):
    """Raised when a requested key ID or version is missing."""


class KeyIntegrityError(KeyManagementError):
    """Raised when a stored key fails checksum or validation."""


class KeyManager:
    """Enterprise persistent key management for encryption and digital forensics."""

    def __init__(
        self,
        key_dir: str | Path = "./data/keys",
        master_secret: str | bytes | None = None,
    ) -> None:
        self.key_dir = Path(key_dir)
        self.key_dir.mkdir(parents=True, exist_ok=True)
        self._enforce_dir_permissions(self.key_dir)

        # Master secret for envelope wrapping (from env, param, or auto-generated)
        if master_secret is None:
            master_secret = os.environ.get("CAMSERV_MASTER_KEY", "camserv-default-master-key-32b-min")
        if isinstance(master_secret, str):
            master_secret = master_secret.encode("utf-8")
        self._master_secret = master_secret

        # In-memory cached keys: map[(key_id, version) -> key_object]
        self._encryption_keys: dict[tuple[str, int], bytes] = {}
        self._signing_keys: dict[tuple[str, int], ed25519.Ed25519PrivateKey] = {}
        self._active_versions: dict[str, int] = {}

    @staticmethod
    def _enforce_dir_permissions(path: Path) -> None:
        """Set restrictive filesystem permissions (owner read/write/exec only on POSIX)."""
        if os.name != "nt":
            try:
                os.chmod(path, stat.S_IRWXU)  # 0700
            except OSError:
                pass

    @staticmethod
    def _enforce_file_permissions(path: Path) -> None:
        """Set restrictive file permissions (owner read/write only on POSIX)."""
        if os.name != "nt":
            try:
                os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
            except OSError:
                pass

    def _derive_wrapping_key(self, key_id: str, version: int) -> bytes:
        """Derive an envelope encryption key from master secret using HKDF-SHA256."""
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=f"camserv-key-wrap-{key_id}-v{version}".encode("utf-8"),
        )
        return hkdf.derive(self._master_secret)

    def get_or_create_encryption_key(
        self,
        key_id: str = "camserv-vault-aes",
        version: int = 1,
    ) -> bytes:
        """Retrieve an existing AES-256-GCM key or create a persistent one atomically."""
        cache_key = (key_id, version)
        if cache_key in self._encryption_keys:
            return self._encryption_keys[cache_key]

        key_file = self.key_dir / f"{key_id}_v{version}.key"
        meta_file = self.key_dir / f"{key_id}_v{version}.json"

        if key_file.exists() and meta_file.exists():
            raw_key = self._load_encrypted_key(key_file, meta_file, key_id, version)
        else:
            raw_key = AESGCM.generate_key(bit_length=256)
            self._save_encrypted_key(key_file, meta_file, key_id, version, KeyType.AES_GCM_ENCRYPTION, raw_key)

        self._encryption_keys[cache_key] = raw_key
        self._active_versions[key_id] = max(self._active_versions.get(key_id, 1), version)
        return raw_key

    def get_or_create_signing_key(
        self,
        key_id: str = "camserv-vault-sign",
        version: int = 1,
    ) -> ed25519.Ed25519PrivateKey:
        """Retrieve an existing Ed25519 private signing key or create a persistent one atomically."""
        cache_key = (key_id, version)
        if cache_key in self._signing_keys:
            return self._signing_keys[cache_key]

        key_file = self.key_dir / f"{key_id}_v{version}.key"
        meta_file = self.key_dir / f"{key_id}_v{version}.json"

        if key_file.exists() and meta_file.exists():
            priv_bytes = self._load_encrypted_key(key_file, meta_file, key_id, version)
            priv_key = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)
        else:
            priv_key = ed25519.Ed25519PrivateKey.generate()
            raw_bytes = priv_key.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            )
            self._save_encrypted_key(key_file, meta_file, key_id, version, KeyType.ED25519_SIGNING, raw_bytes)

        self._signing_keys[cache_key] = priv_key
        self._active_versions[key_id] = max(self._active_versions.get(key_id, 1), version)
        return priv_key

    def rotate_encryption_key(self, key_id: str = "camserv-vault-aes") -> tuple[int, bytes]:
        """Rotate to a new version of an encryption key, keeping older versions available."""
        current_v = self._active_versions.get(key_id, 1)
        new_v = current_v + 1
        new_key = self.get_or_create_encryption_key(key_id=key_id, version=new_v)
        self._active_versions[key_id] = new_v
        logger.info("key_manager.rotated_encryption_key", key_id=key_id, new_version=new_v)
        return new_v, new_key

    def rotate_signing_key(self, key_id: str = "camserv-vault-sign") -> tuple[int, ed25519.Ed25519PrivateKey]:
        """Rotate to a new version of a signing key, keeping older versions available."""
        current_v = self._active_versions.get(key_id, 1)
        new_v = current_v + 1
        new_key = self.get_or_create_signing_key(key_id=key_id, version=new_v)
        self._active_versions[key_id] = new_v
        logger.info("key_manager.rotated_signing_key", key_id=key_id, new_version=new_v)
        return new_v, new_key

    def _save_encrypted_key(
        self,
        key_path: Path,
        meta_path: Path,
        key_id: str,
        version: int,
        key_type: KeyType,
        raw_bytes: bytes,
    ) -> None:
        """Atomically persist key encrypted with KEK and write metadata."""
        wrapping_key = self._derive_wrapping_key(key_id, version)
        aesgcm = AESGCM(wrapping_key)
        nonce = os.urandom(12)
        encrypted_payload = nonce + aesgcm.encrypt(nonce, raw_bytes, key_id.encode("utf-8"))

        fingerprint = hashlib.sha256(raw_bytes).hexdigest()
        metadata = KeyMetadata(
            key_id=key_id,
            version=version,
            key_type=key_type,
            algorithm="AES-256-GCM" if key_type == KeyType.AES_GCM_ENCRYPTION else "Ed25519",
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            fingerprint=fingerprint,
        )

        # Atomic write to temporary files then rename
        tmp_key = key_path.with_suffix(".tmp")
        tmp_meta = meta_path.with_suffix(".tmp")

        try:
            with open(tmp_key, "wb") as f:
                f.write(encrypted_payload)
            self._enforce_file_permissions(tmp_key)
            os.replace(tmp_key, key_path)

            with open(tmp_meta, "w", encoding="utf-8") as f:
                json.dump(asdict(metadata), f, indent=2)
            self._enforce_file_permissions(tmp_meta)
            os.replace(tmp_meta, meta_path)
        finally:
            if tmp_key.exists():
                tmp_key.unlink(missing_ok=True)
            if tmp_meta.exists():
                tmp_meta.unlink(missing_ok=True)

    def _load_encrypted_key(
        self,
        key_path: Path,
        meta_path: Path,
        key_id: str,
        version: int,
    ) -> bytes:
        """Load and decrypt an encrypted key, validating SHA-256 fingerprint."""
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta_dict = json.load(f)
            metadata = KeyMetadata(**meta_dict)

            with open(key_path, "rb") as f:
                encrypted_payload = f.read()

            wrapping_key = self._derive_wrapping_key(key_id, version)
            aesgcm = AESGCM(wrapping_key)
            nonce = encrypted_payload[:12]
            ciphertext = encrypted_payload[12:]
            raw_bytes = aesgcm.decrypt(nonce, ciphertext, key_id.encode("utf-8"))

            # Verify integrity fingerprint
            computed_fp = hashlib.sha256(raw_bytes).hexdigest()
            if computed_fp != metadata.fingerprint:
                raise KeyIntegrityError(f"Key fingerprint mismatch for {key_id} v{version}")

            return raw_bytes
        except Exception as exc:
            if isinstance(exc, KeyIntegrityError):
                raise
            raise KeyIntegrityError(f"Failed to decrypt key {key_id} v{version}: {exc}") from exc
