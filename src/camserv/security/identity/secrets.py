"""
camserv.security.identity.secrets
=================================

Camera credential protection, AES-256-GCM encryption at rest, and zero-leakage redaction.
Guarantees camera passwords, RTSP URLs, and ONVIF secrets are never exposed to clients,
logs, or unauthorized services.
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
import structlog

logger = structlog.get_logger(__name__)

REDACTED = "***REDACTED***"

SENSITIVE_KEYS: frozenset[str] = frozenset({
    "password", "passwd", "secret", "token", "auth_token", "access_token",
    "refresh_token", "api_key", "credential", "private_key", "totp_secret",
})


def redact_url(url: str) -> str:
    """Redact embedded credentials in RTSP, HTTP, or other stream URLs.

    Example: `rtsp://admin:supersecret@192.168.1.50:554/h264` -> `rtsp://admin:***REDACTED***@192.168.1.50:554/h264`
    """
    if not url:
        return url

    try:
        parts = urlsplit(url)
        if parts.username or parts.password or ("@" in parts.netloc):
            netloc = parts.netloc
            # Format is username:password@host[:port]
            # Use rsplit to handle '@' in passwords properly
            if "@" in netloc:
                auth_part, host_part = netloc.rsplit("@", 1)
                if ":" in auth_part:
                    user, _ = auth_part.split(":", 1)
                    new_auth = f"{user}:{REDACTED}"
                else:
                    new_auth = REDACTED
                new_netloc = f"{new_auth}@{host_part}"
                return urlunsplit((parts.scheme, new_netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        pass

    # Regex fallback (use greedy user matching until the last @ before host)
    return re.sub(r"://([^:]+):([^@]+)@([a-zA-Z0-9.\-_:]+)", rf"://\1:{REDACTED}@\3", url)


def redact_sensitive_data(obj: Any) -> Any:
    """Recursively redact passwords, tokens, and stream URLs in dictionaries or lists."""
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            if str(k).lower() in SENSITIVE_KEYS:
                cleaned[k] = REDACTED
            elif str(k).lower() in ("url", "rtsp_url", "stream_url") and isinstance(v, str):
                cleaned[k] = redact_url(v)
            else:
                cleaned[k] = redact_sensitive_data(v)
        return cleaned
    elif isinstance(obj, list):
        return [redact_sensitive_data(item) for item in obj]
    elif isinstance(obj, str):
        if "://" in obj and ("@" in obj):
            return redact_url(obj)
        return obj
    return obj


class CameraCredentialProtection:
    """Dedicated vault protecting camera passwords and RTSP URLs using AES-256-GCM."""

    def __init__(
        self,
        master_key: bytes | None = None,
        key_file: str | Path | None = None,
    ) -> None:
        if master_key is not None:
            raw_master = master_key
        else:
            path = Path(key_file or "data/secrets/camera_vault.key")
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                with open(path, "rb") as f:
                    raw_master = f.read()
            else:
                raw_master = secrets.token_bytes(32)
                with open(path, "wb") as f:
                    f.write(raw_master)
                try:
                    os.chmod(path, 0o600)
                except Exception:
                    pass

        # Derive camera-specific encryption key via HKDF-SHA256
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"camserv-camera-credential-salt-v1",
            info=b"camserv-v1-camera-credentials",
        )
        self._vault_key = hkdf.derive(raw_master)
        self._aesgcm = AESGCM(self._vault_key)

    def encrypt_secret(self, plaintext: str) -> str:
        """Encrypt sensitive camera secret using AES-256-GCM with a unique nonce."""
        nonce = secrets.token_bytes(12)
        ct = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        envelope = {
            "n": base64.b64encode(nonce).decode("ascii"),
            "c": base64.b64encode(ct).decode("ascii"),
        }
        return json.dumps(envelope)

    def decrypt_secret(self, encrypted_envelope: str) -> str:
        """Decrypt AES-256-GCM encrypted camera secret."""
        data = json.loads(encrypted_envelope)
        nonce = base64.b64decode(data["n"])
        ct = base64.b64decode(data["c"])
        pt = self._aesgcm.decrypt(nonce, ct, None)
        return pt.decode("utf-8")

    def sanitize_camera_for_client(self, camera_data: dict[str, Any]) -> dict[str, Any]:
        """Produce a safe client-facing camera dict where URL and credentials are redacted."""
        return redact_sensitive_data(camera_data)
