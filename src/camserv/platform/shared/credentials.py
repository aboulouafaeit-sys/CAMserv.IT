"""
camserv.platform.shared.credentials
===================================

Cross-platform credential protection base implementation.
Provides AES-256-GCM symmetric encryption with HKDF key derivation
for environments where platform-native hardware binding (DPAPI/TPM)
is substituted or used in combination with application master keys.
"""

from __future__ import annotations

import base64
import os
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from camserv.platform.shared.interfaces import PlatformCredentialVault


class StandardSoftwareCredentialVault(PlatformCredentialVault):
    """
    Cross-platform software credential vault using AES-256-GCM.
    Derives encryption keys from master entropy or environment variables.
    """

    def __init__(self, master_key: str | bytes | None = None) -> None:
        if master_key is None:
            raw = os.environ.get("CAMSERV_MASTER_KEY", "camserv-default-master-key-32b-min")
            self._master_bytes = raw.encode("utf-8") if isinstance(raw, str) else raw
        elif isinstance(master_key, str):
            self._master_bytes = master_key.encode("utf-8")
        else:
            self._master_bytes = master_key

    def _derive_key(self, purpose: str) -> bytes:
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=f"camserv-credential-vault-{purpose}".encode("utf-8"),
        )
        return hkdf.derive(self._master_bytes)

    def protect_secret(self, secret_bytes: bytes, description: str = "") -> bytes:
        """Encrypt secret bytes using AES-256-GCM."""
        key = self._derive_key(description or "default")
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, secret_bytes, description.encode("utf-8"))
        # Payload format: 12 bytes nonce + ciphertext
        return nonce + ciphertext

    def unprotect_secret(self, encrypted_bytes: bytes, description: str = "") -> bytes:
        """Decrypt secret bytes using AES-256-GCM."""
        if len(encrypted_bytes) < 12:
            raise ValueError("Invalid encrypted payload length; must be >= 12 bytes.")
        key = self._derive_key(description or "default")
        aesgcm = AESGCM(key)
        nonce = encrypted_bytes[:12]
        ciphertext = encrypted_bytes[12:]
        return aesgcm.decrypt(nonce, ciphertext, description.encode("utf-8"))

    def is_hardware_bound(self) -> bool:
        """Software vault is not hardware-bound."""
        return False
