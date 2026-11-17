"""
camserv.security.identity.password
==================================

High-assurance password hashing, verification, and policy enforcement using
RFC 9106 Argon2id with backwards-compatible PBKDF2 verification, bounded execution
concurrency, and zero silent truncation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import threading
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidKey
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
import structlog

logger = structlog.get_logger(__name__)


# Standard disallowed weak passwords
COMMON_WEAK_PASSWORDS: frozenset[str] = frozenset({
    "password", "password123", "password1234", "123456789012",
    "administrator", "adminadminadmin", "camservadmin", "camserv12345",
    "welcome12345", "changeme12345", "letmein12345", "surveillance1",
    "defaultpassword", "operator1234", "security1234"
})


class PasswordPolicyError(ValueError):
    """Raised when a candidate password violates the local identity password policy."""
    def __init__(self, violations: list[str]) -> None:
        self.violations = violations
        super().__init__(f"Password violates policy: {'; '.join(violations)}")


class ConcurrencyExhaustedError(RuntimeError):
    """Raised when the password hashing semaphore queue is saturated."""


@dataclass(slots=True)
class Argon2idConfig:
    """RFC 9106 Argon2id calibration parameters."""

    memory_cost: int = 65536   # 64 MiB
    time_cost: int = 2         # 2 iterations
    parallelism: int = 4       # 4 concurrent lanes
    hash_len: int = 32         # 256-bit derived key
    salt_len: int = 16         # 128-bit cryptographic salt


@dataclass(slots=True)
class PasswordPolicy:
    """Password strength and complexity rules."""

    min_length: int = 12
    max_length: int = 1024
    require_uppercase: bool = True
    require_lowercase: bool = True
    require_digits: bool = True
    require_symbols: bool = True
    passphrase_min_length: int = 20  # Passphrases >= 20 chars bypass character-class requirements


class Argon2idPasswordHasher:
    """Production Argon2id password hasher with dual-verification and bounded concurrency."""

    def __init__(
        self,
        config: Argon2idConfig | None = None,
        policy: PasswordPolicy | None = None,
        max_concurrency: int = 4,
    ) -> None:
        self.config = config or Argon2idConfig()
        self.policy = policy or PasswordPolicy()
        self._semaphore = threading.Semaphore(max_concurrency)

    def validate_password(self, password: str, username: str | None = None) -> tuple[bool, list[str]]:
        """Validate candidate password against security policy.

        Returns (is_valid, list_of_violations).
        """
        violations: list[str] = []

        if len(password) < self.policy.min_length:
            violations.append(f"Password must be at least {self.policy.min_length} characters long")

        if len(password) > self.policy.max_length:
            violations.append(f"Password must not exceed {self.policy.max_length} characters")

        lower_pw = password.lower().strip()
        if lower_pw in COMMON_WEAK_PASSWORDS:
            violations.append("Password matches a known common or insecure pattern")

        if username and len(username) >= 3 and username.lower() in lower_pw:
            violations.append("Password must not contain the account username")

        # Passphrase exemption: >= passphrase_min_length bypasses character-class requirements
        if len(password) < self.policy.passphrase_min_length:
            if self.policy.require_uppercase and not re.search(r"[A-Z]", password):
                violations.append("Password must contain at least one uppercase letter")
            if self.policy.require_lowercase and not re.search(r"[a-z]", password):
                violations.append("Password must contain at least one lowercase letter")
            if self.policy.require_digits and not re.search(r"\d", password):
                violations.append("Password must contain at least one digit")
            if self.policy.require_symbols and not re.search(r"[!@#$%^&*(),.?\":{}|<>[\]\\/'`~_+=;\-]", password):
                violations.append("Password must contain at least one special character")

        return (len(violations) == 0, violations)

    def hash_password(
        self,
        password: str,
        validate_policy: bool = True,
        username: str | None = None,
        timeout_sec: float = 5.0,
    ) -> str:
        """Hash a password using RFC 9106 Argon2id.

        Format: `$argon2id$v=19$m={memory_cost},t={time_cost},p={parallelism}${b64_salt}${b64_hash}`
        """
        if validate_policy:
            valid, violations = self.validate_password(password, username)
            if not valid:
                raise PasswordPolicyError(violations)

        acquired = self._semaphore.acquire(timeout=timeout_sec)
        if not acquired:
            raise ConcurrencyExhaustedError("Password hashing worker capacity saturated")

        try:
            salt = os.urandom(self.config.salt_len)
            kdf = Argon2id(
                salt=salt,
                length=self.config.hash_len,
                iterations=self.config.time_cost,
                lanes=self.config.parallelism,
                memory_cost=self.config.memory_cost,
            )
            raw_hash = kdf.derive(password.encode("utf-8"))

            b64_salt = base64.b64encode(salt).decode("ascii").rstrip("=")
            b64_hash = base64.b64encode(raw_hash).decode("ascii").rstrip("=")

            return (
                f"$argon2id$v=19$m={self.config.memory_cost},"
                f"t={self.config.time_cost},"
                f"p={self.config.parallelism}$"
                f"{b64_salt}${b64_hash}"
            )
        finally:
            self._semaphore.release()

    def verify_password(self, password: str, hashed_str: str, timeout_sec: float = 5.0) -> bool:
        """Verify candidate password against Argon2id or legacy PBKDF2 hash."""
        if not hashed_str or not password:
            return False

        # 1. PBKDF2-HMAC-SHA256 compatibility branch
        if hashed_str.startswith("pbkdf2_sha256$"):
            return self._verify_pbkdf2(password, hashed_str)

        # 2. RFC 9106 Argon2id branch
        if hashed_str.startswith("$argon2id$"):
            acquired = self._semaphore.acquire(timeout=timeout_sec)
            if not acquired:
                logger.warning("argon2id_verification_throttled", reason="concurrency_saturated")
                return False
            try:
                return self._verify_argon2id(password, hashed_str)
            finally:
                self._semaphore.release()

        logger.warning("unsupported_password_hash_format", hash_prefix=hashed_str[:15])
        return False

    def needs_rehash(self, hashed_str: str) -> bool:
        """Determine if hash was generated with legacy algorithm or outdated parameters."""
        if not hashed_str:
            return True
        if hashed_str.startswith("pbkdf2_sha256$"):
            return True
        if not hashed_str.startswith("$argon2id$"):
            return True

        # Check Argon2id parameter calibration
        try:
            parts = hashed_str.split("$")
            # Expected: ['', 'argon2id', 'v=19', 'm=...,t=...,p=...', salt, hash]
            if len(parts) != 6:
                return True
            param_pairs = dict(item.split("=") for item in parts[3].split(","))
            m = int(param_pairs.get("m", 0))
            t = int(param_pairs.get("t", 0))
            p = int(param_pairs.get("p", 0))

            if m != self.config.memory_cost or t != self.config.time_cost or p != self.config.parallelism:
                return True
        except Exception:
            return True

        return False

    def _verify_argon2id(self, password: str, hashed_str: str) -> bool:
        """Internal Argon2id verification with parsed parameters."""
        try:
            parts = hashed_str.split("$")
            if len(parts) != 6:
                return False
            # parts[1] == 'argon2id'
            # parts[2] == 'v=19'
            param_pairs = dict(item.split("=") for item in parts[3].split(","))
            m = int(param_pairs["m"])
            t = int(param_pairs["t"])
            p = int(param_pairs["p"])

            raw_salt = self._b64decode_unpadded(parts[4])
            raw_hash = self._b64decode_unpadded(parts[5])

            kdf = Argon2id(
                salt=raw_salt,
                length=len(raw_hash),
                iterations=t,
                lanes=p,
                memory_cost=m,
            )
            kdf.verify(password.encode("utf-8"), raw_hash)
            return True
        except InvalidKey:
            return False
        except Exception as exc:
            logger.debug("argon2id_verification_failed_internal", error=str(exc))
            return False

    def _verify_pbkdf2(self, password: str, hashed_str: str) -> bool:
        """Internal PBKDF2-HMAC-SHA256 verification."""
        try:
            parts = hashed_str.split("$")
            if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
                return False
            iterations = int(parts[1])
            salt = bytes.fromhex(parts[2])
            expected = bytes.fromhex(parts[3])
            derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            return hmac.compare_digest(derived, expected)
        except Exception:
            return False

    @staticmethod
    def _b64decode_unpadded(data: str) -> bytes:
        """Decode base64 string with missing padding."""
        missing_padding = len(data) % 4
        if missing_padding:
            data += "=" * (4 - missing_padding)
        return base64.b64decode(data.encode("ascii"))


# Singleton default hasher instance
_default_hasher = Argon2idPasswordHasher()


def hash_password(password: str, validate_policy: bool = False, username: str | None = None) -> str:
    """Convenience function for Argon2id password hashing."""
    return _default_hasher.hash_password(password, validate_policy=validate_policy, username=username)


def verify_password(password: str, hashed_str: str) -> bool:
    """Convenience function for constant-time dual Argon2id / PBKDF2 verification."""
    return _default_hasher.verify_password(password, hashed_str)


def needs_rehash(hashed_str: str) -> bool:
    """Convenience function to check if a hash needs upgrading to current Argon2id config."""
    return _default_hasher.needs_rehash(hashed_str)


def validate_password_policy(password: str, username: str | None = None) -> tuple[bool, list[str]]:
    """Convenience function to validate password complexity and length."""
    return _default_hasher.validate_password(password, username)
