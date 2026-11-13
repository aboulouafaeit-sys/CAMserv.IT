"""Encryption utilities — key management, AES-256-GCM, HKDF, credential vault.

Provides :class:`EncryptionManager` for all cryptographic operations in CAMserv:
  * AES-256-GCM authenticated encryption / decryption of data at rest.
  * Key derivation from a master key via HKDF-SHA256.
  * Key rotation with version tracking.
  * Secure credential vault for device passwords (RTSP, ONVIF, etc.).
  * TLS certificate loading helpers.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.x509 import load_pem_x509_certificate

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_KEY_BYTES = 32  # AES-256
_NONCE_BYTES = 12  # 96-bit nonce for GCM
_HKDF_INFO_PREFIX = b"camserv-v1-"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class EncryptedPayload:
    """Container for an encrypted blob with associated metadata."""

    ciphertext: bytes
    nonce: bytes
    key_version: int
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # -- Serialisation helpers ------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "ciphertext": base64.b64encode(self.ciphertext).decode(),
            "nonce": base64.b64encode(self.nonce).decode(),
            "key_version": self.key_version,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EncryptedPayload":
        return cls(
            ciphertext=base64.b64decode(data["ciphertext"]),
            nonce=base64.b64decode(data["nonce"]),
            key_version=data["key_version"],
            created_at=data.get("created_at", ""),
        )


# ---------------------------------------------------------------------------
# EncryptionManager
# ---------------------------------------------------------------------------
class EncryptionManager:
    """Centralised cryptographic operations for CAMserv.

    Parameters
    ----------
    master_key:
        Base-64-encoded 256-bit master key.  If *None*, the ``CAMSERV_MASTER_KEY``
        environment variable is read.  A :class:`ValueError` is raised when no
        key is available.
    """

    def __init__(self, master_key: str | None = None) -> None:
        raw = master_key or os.environ.get("CAMSERV_MASTER_KEY")
        if not raw:
            raise ValueError(
                "Master key must be provided or set via CAMSERV_MASTER_KEY env var"
            )
        self._master_key: bytes = base64.b64decode(raw)
        if len(self._master_key) != _KEY_BYTES:
            raise ValueError(f"Master key must be {_KEY_BYTES} bytes (got {len(self._master_key)})")

        # Key version tracking — version 1 is the initial master key.
        self._key_versions: dict[int, bytes] = {1: self._master_key}
        self._current_version: int = 1

        logger.info("encryption_manager.init", key_versions=list(self._key_versions.keys()))

    # -- Key derivation -------------------------------------------------------

    def derive_key(self, purpose: str, *, length: int = _KEY_BYTES) -> bytes:
        """Derive a purpose-specific key from the master key via HKDF-SHA256.

        Parameters
        ----------
        purpose:
            Short string identifying the key usage (e.g. ``"evidence"``,
            ``"credential-vault"``).
        length:
            Desired output key length in bytes.
        """
        info = _HKDF_INFO_PREFIX + purpose.encode()
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=length,
            salt=None,
            info=info,
        )
        return hkdf.derive(self._key_versions[self._current_version])

    # -- AES-256-GCM ----------------------------------------------------------

    def encrypt(
        self,
        plaintext: bytes,
        *,
        associated_data: bytes | None = None,
        purpose: str = "general",
    ) -> EncryptedPayload:
        """Encrypt *plaintext* with AES-256-GCM.

        An authenticated-encryption scheme — the returned ciphertext includes
        a 128-bit authentication tag.  Optional *associated_data* is
        authenticated but **not** encrypted.
        """
        key = self.derive_key(purpose)
        nonce = secrets.token_bytes(_NONCE_BYTES)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data)
        return EncryptedPayload(
            ciphertext=ciphertext,
            nonce=nonce,
            key_version=self._current_version,
        )

    def decrypt(
        self,
        payload: EncryptedPayload,
        *,
        associated_data: bytes | None = None,
        purpose: str = "general",
    ) -> bytes:
        """Decrypt an :class:`EncryptedPayload` previously produced by :meth:`encrypt`."""
        if payload.key_version not in self._key_versions:
            raise ValueError(f"Unknown key version {payload.key_version}")

        # Derive the same key used for encryption.
        old_ver = self._current_version
        try:
            self._current_version = payload.key_version
            key = self.derive_key(purpose)
        finally:
            self._current_version = old_ver

        aesgcm = AESGCM(key)
        return aesgcm.decrypt(payload.nonce, payload.ciphertext, associated_data)

    # -- Key rotation ---------------------------------------------------------

    def rotate_key(self, new_master_key: str) -> int:
        """Add a new master key version and make it current.

        Returns the new version number.  Previous versions are retained so that
        data encrypted under older keys can still be decrypted.
        """
        raw = base64.b64decode(new_master_key)
        if len(raw) != _KEY_BYTES:
            raise ValueError(f"New key must be {_KEY_BYTES} bytes (got {len(raw)})")

        new_version = self._current_version + 1
        self._key_versions[new_version] = raw
        self._current_version = new_version
        logger.info("encryption_manager.key_rotated", new_version=new_version)
        return new_version

    @property
    def current_key_version(self) -> int:
        """The active key version number."""
        return self._current_version

    # -- Credential vault -----------------------------------------------------

    def vault_store(self, credentials: dict[str, str], vault_path: Path) -> None:
        """Encrypt and persist a credentials dictionary.

        Stored as a single AES-256-GCM encrypted JSON blob on disk.

        Parameters
        ----------
        credentials:
            Mapping of credential name → secret value.
        vault_path:
            Filesystem path for the encrypted vault file.
        """
        plaintext = json.dumps(credentials, sort_keys=True).encode()
        payload = self.encrypt(plaintext, purpose="credential-vault")
        vault_path.parent.mkdir(parents=True, exist_ok=True)
        vault_path.write_text(json.dumps(payload.to_dict()), encoding="utf-8")
        logger.info("vault.stored", path=str(vault_path), entries=len(credentials))

    def vault_load(self, vault_path: Path) -> dict[str, str]:
        """Decrypt and return the credential vault at *vault_path*."""
        data = json.loads(vault_path.read_text(encoding="utf-8"))
        payload = EncryptedPayload.from_dict(data)
        plaintext = self.decrypt(payload, purpose="credential-vault")
        creds: dict[str, str] = json.loads(plaintext)
        logger.info("vault.loaded", path=str(vault_path), entries=len(creds))
        return creds

    # -- TLS certificate helpers ----------------------------------------------

    @staticmethod
    def load_tls_cert(cert_path: Path) -> Any:
        """Load a PEM-encoded TLS certificate.

        Returns a :class:`cryptography.x509.Certificate` object.
        """
        pem_data = cert_path.read_bytes()
        cert = load_pem_x509_certificate(pem_data)
        logger.info(
            "tls.cert_loaded",
            subject=str(cert.subject),
            not_after=cert.not_valid_after_utc.isoformat(),
        )
        return cert

    @staticmethod
    def load_private_key(key_path: Path, password: bytes | None = None) -> Any:
        """Load a PEM-encoded private key, optionally decrypting with *password*."""
        pem_data = key_path.read_bytes()
        private_key = serialization.load_pem_private_key(pem_data, password=password)
        logger.info("tls.private_key_loaded", path=str(key_path))
        return private_key

    # -- Utility --------------------------------------------------------------

    @staticmethod
    def generate_master_key() -> str:
        """Generate a new random 256-bit master key, base-64-encoded."""
        return base64.b64encode(secrets.token_bytes(_KEY_BYTES)).decode()
