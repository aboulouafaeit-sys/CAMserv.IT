"""
camserv.nvr.credentials
=======================

Encrypted camera credential vault for CAMserv NVR.
Stores RTSP, ONVIF, and HTTP authentication credentials securely using AES-256-GCM
with versioned encryption keys, preventing exposure of plaintext camera secrets
in configuration files, database dumps, or diagnostic logs.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import structlog
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from camserv.security.encryption import EncryptionManager

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class CameraCredential:
    """Authentication details for a managed camera endpoint."""

    camera_id: str
    username: str
    password: str
    auth_type: str = "digest"  # 'digest', 'basic', 'token'
    onvif_username: str | None = None
    onvif_password: str | None = None
    api_token: str | None = None
    updated_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize credential record."""
        return asdict(self)


class CameraCredentialVault:
    """
    AES-256-GCM encrypted vault governing camera authentication secrets.
    """

    def __init__(
        self,
        vault_path: Path | str = "data/camera_credentials.enc",
        master_key: str | bytes | None = None,
    ) -> None:
        self.vault_path = Path(vault_path)
        self.vault_path.parent.mkdir(parents=True, exist_ok=True)

        if master_key is None:
            env_key = os.environ.get("CAMSERV_MASTER_KEY")
            if env_key:
                self._key_bytes = base64.b64decode(env_key)
            else:
                self._key_bytes = AESGCM.generate_key(bit_length=256)
        elif isinstance(master_key, str):
            self._key_bytes = base64.b64decode(master_key)
        else:
            self._key_bytes = master_key

        self._aesgcm = AESGCM(self._key_bytes)
        self._cache: dict[str, CameraCredential] = {}
        self._load_vault()

    def _load_vault(self) -> None:
        """Decrypt and load credentials from disk if vault file exists."""
        if not self.vault_path.exists():
            return

        try:
            with open(self.vault_path, "rb") as f:
                raw_bytes = f.read()

            if len(raw_bytes) < 12:
                logger.warning("nvr.vault.empty_or_corrupt", path=str(self.vault_path))
                return

            nonce = raw_bytes[:12]
            ciphertext = raw_bytes[12:]
            decrypted = self._aesgcm.decrypt(nonce, ciphertext, None)
            data = json.loads(decrypted.decode("utf-8"))

            for cam_id, cred_dict in data.items():
                self._cache[cam_id] = CameraCredential(**cred_dict)

            logger.info("nvr.vault.loaded", credentials_count=len(self._cache))
        except Exception as exc:
            logger.error("nvr.vault.load_failed", error=str(exc))
            raise ValueError(f"Failed to decrypt camera credential vault: {exc}") from exc

    def _save_vault(self) -> None:
        """Encrypt and atomically persist credentials to disk."""
        data = {cam_id: cred.to_dict() for cam_id, cred in self._cache.items()}
        plaintext = json.dumps(data, indent=2).encode("utf-8")

        nonce = os.urandom(12)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, None)
        payload = nonce + ciphertext

        temp_path = self.vault_path.with_suffix(".tmp")
        with open(temp_path, "wb") as f:
            f.write(payload)

        temp_path.replace(self.vault_path)

    def store_credential(self, credential: CameraCredential) -> None:
        """Store or update camera credentials in the encrypted vault."""
        self._cache[credential.camera_id] = credential
        self._save_vault()
        logger.info("nvr.vault.credential_stored", camera_id=credential.camera_id)

    def get_credential(self, camera_id: str) -> CameraCredential | None:
        """Retrieve decrypted credentials for a given camera ID."""
        return self._cache.get(camera_id)

    def delete_credential(self, camera_id: str) -> bool:
        """Delete credentials for a camera."""
        if camera_id in self._cache:
            del self._cache[camera_id]
            self._save_vault()
            logger.info("nvr.vault.credential_deleted", camera_id=camera_id)
            return True
        return False

    def list_cameras_with_credentials(self) -> list[str]:
        """List all camera IDs that have credentials in the vault."""
        return list(self._cache.keys())
