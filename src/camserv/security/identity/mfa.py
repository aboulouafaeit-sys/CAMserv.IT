"""
camserv.security.identity.mfa
=============================

Multi-Factor Authentication (MFA) engine for CAMserv:
* RFC 6238 Time-Based One-Time Password (TOTP) generator and verifier.
* AES-256-GCM encrypted TOTP secret storage.
* Single-use cryptographic recovery codes.
* WebAuthn / Passkey registration and assertion verification hooks.
* Clock drift tolerance (window ±1 step) and strict replay protection.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import structlog

logger = structlog.get_logger(__name__)


class MFAError(Exception):
    """Base exception for multi-factor authentication failures."""


class ReplayAttackError(MFAError):
    """Raised when an identical TOTP code is reused within the active window."""


class InvalidMFACodeError(MFAError):
    """Raised when an MFA code is invalid or expired."""


@dataclass(slots=True)
class TOTPConfig:
    """TOTP generation parameters."""

    digits: int = 6
    interval_sec: int = 30
    algorithm: str = "SHA1"  # "SHA1" or "SHA256"
    drift_tolerance_steps: int = 1  # ±1 step (allows 30s before and after)
    issuer: str = "CAMserv"


class MFASecretProtector:
    """AES-256-GCM encryption for TOTP secrets at rest."""

    def __init__(self, key: bytes | None = None, key_file: str | Path | None = None) -> None:
        if key is not None:
            if len(key) != 32:
                raise ValueError("Key must be 32 bytes for AES-256-GCM")
            self._key = key
        else:
            path = Path(key_file or "data/secrets/identity_mfa.key")
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                with open(path, "rb") as f:
                    self._key = f.read()
            else:
                self._key = secrets.token_bytes(32)
                with open(path, "wb") as f:
                    f.write(self._key)
                try:
                    os.chmod(path, 0o600)
                except Exception:
                    pass

        self._aesgcm = AESGCM(self._key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt secret string into JSON base64 envelope."""
        nonce = secrets.token_bytes(12)
        ct = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        envelope = {
            "n": base64.b64encode(nonce).decode("ascii"),
            "c": base64.b64encode(ct).decode("ascii"),
        }
        return json.dumps(envelope)

    def decrypt(self, envelope_json: str) -> str:
        """Decrypt JSON base64 envelope back to plaintext string."""
        data = json.loads(envelope_json)
        nonce = base64.b64decode(data["n"])
        ct = base64.b64decode(data["c"])
        pt = self._aesgcm.decrypt(nonce, ct, None)
        return pt.decode("utf-8")


class TOTPManager:
    """RFC 6238 TOTP Manager with replay protection and encrypted secret storage."""

    def __init__(self, config: TOTPConfig | None = None, protector: MFASecretProtector | None = None) -> None:
        self.config = config or TOTPConfig()
        self.protector = protector or MFASecretProtector()

    def generate_secret(self, byte_length: int = 20) -> str:
        """Generate a random 160-bit cryptographically secure base32 secret."""
        raw = secrets.token_bytes(byte_length)
        return base64.b32encode(raw).decode("ascii").rstrip("=")

    def get_provisioning_uri(self, username: str, secret_b32: str) -> str:
        """Generate standard otpauth:// URI for QR code enrollment."""
        encoded_user = quote(username)
        encoded_issuer = quote(self.config.issuer)
        return (
            f"otpauth://totp/{encoded_issuer}:{encoded_user}"
            f"?secret={secret_b32}"
            f"&issuer={encoded_issuer}"
            f"&algorithm={self.config.algorithm}"
            f"&digits={self.config.digits}"
            f"&period={self.config.interval_sec}"
        )

    def compute_code(self, secret_b32: str, timestamp: float | None = None) -> tuple[str, int]:
        """Compute TOTP code for a given timestamp.

        Returns (code_str, time_step).
        """
        if timestamp is None:
            timestamp = time.time()

        padding = "=" * ((8 - len(secret_b32) % 8) % 8)
        key = base64.b32decode(secret_b32.upper() + padding)
        step = int(timestamp // self.config.interval_sec)
        msg = struct.pack(">Q", step)

        algo = hashlib.sha256 if self.config.algorithm.upper() == "SHA256" else hashlib.sha1
        digest = hmac.new(key, msg, algo).digest()
        offset = digest[-1] & 0x0F
        code_int = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (10 ** self.config.digits)
        return f"{code_int:0{self.config.digits}d}", step

    def verify_code(
        self,
        secret_b32: str,
        candidate_code: str,
        last_used_step: int = -1,
        timestamp: float | None = None,
    ) -> tuple[bool, int]:
        """Verify candidate code against RFC 6238 window with replay protection.

        Returns (is_valid, matched_step).
        """
        if not candidate_code or not secret_b32:
            return (False, -1)

        candidate_clean = candidate_code.strip().replace(" ", "")
        if len(candidate_clean) != self.config.digits or not candidate_clean.isdigit():
            return (False, -1)

        if timestamp is None:
            timestamp = time.time()

        current_step = int(timestamp // self.config.interval_sec)
        tolerance = self.config.drift_tolerance_steps

        # Check steps in range [current_step - tolerance, current_step + tolerance]
        for step in range(current_step - tolerance, current_step + tolerance + 1):
            if step <= last_used_step:
                # Replay protection: cannot reuse the same or an older step than already verified
                continue

            padding = "=" * ((8 - len(secret_b32) % 8) % 8)
            try:
                key = base64.b32decode(secret_b32.upper() + padding)
            except Exception:
                return (False, -1)

            msg = struct.pack(">Q", step)
            algo = hashlib.sha256 if self.config.algorithm.upper() == "SHA256" else hashlib.sha1
            digest = hmac.new(key, msg, algo).digest()
            offset = digest[-1] & 0x0F
            code_int = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (10 ** self.config.digits)
            expected_code = f"{code_int:0{self.config.digits}d}"

            if hmac.compare_digest(candidate_clean, expected_code):
                return (True, step)

        return (False, -1)


# ---------------------------------------------------------------------------
# Recovery Codes
# ---------------------------------------------------------------------------

def generate_recovery_codes(count: int = 10, length: int = 16) -> list[str]:
    """Generate high-entropy single-use recovery codes in XXXX-XXXX-XXXX-XXXX format."""
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # Base32 crockford-style (no 0, 1, I, O)
    codes: list[str] = []
    for _ in range(count):
        raw = "".join(secrets.choice(alphabet) for _ in range(length))
        # Format as groups of 4
        formatted = "-".join(raw[i : i + 4] for i in range(0, length, 4))
        codes.append(formatted)
    return codes


def hash_recovery_code(code: str) -> str:
    """Normalize and compute SHA-256 hash of a recovery code."""
    normalized = code.strip().replace("-", "").replace(" ", "").upper()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# WebAuthn / Passkey Hooks
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PasskeyChallenge:
    """WebAuthn cryptographic challenge."""

    challenge_id: str
    user_id: str
    challenge_bytes_b64: str
    created_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at_utc: str = ""


class PasskeyManager:
    """Local WebAuthn / Passkey interface hooks for hardware token authentication."""

    def __init__(self, rp_id: str = "localhost", rp_name: str = "CAMserv Local Appliance") -> None:
        self.rp_id = rp_id
        self.rp_name = rp_name

    def create_registration_options(self, user_id: str, username: str) -> dict[str, Any]:
        """Create standard WebAuthn publicKeyCredentialCreationOptions."""
        challenge = secrets.token_bytes(32)
        return {
            "challenge": base64.urlsafe_b64encode(challenge).decode("ascii").rstrip("="),
            "rp": {"name": self.rp_name, "id": self.rp_id},
            "user": {
                "id": base64.urlsafe_b64encode(user_id.encode()).decode("ascii").rstrip("="),
                "name": username,
                "displayName": username,
            },
            "pubKeyCredParams": [
                {"alg": -7, "type": "public-key"},  # ES256
                {"alg": -257, "type": "public-key"},  # RS256
            ],
            "timeout": 60000,
            "attestation": "none",
        }

    def create_assertion_options(self, user_id: str) -> dict[str, Any]:
        """Create standard WebAuthn publicKeyCredentialRequestOptions."""
        challenge = secrets.token_bytes(32)
        return {
            "challenge": base64.urlsafe_b64encode(challenge).decode("ascii").rstrip("="),
            "timeout": 60000,
            "rpId": self.rp_id,
            "userVerification": "preferred",
        }
