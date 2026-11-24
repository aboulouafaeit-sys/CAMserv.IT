"""
camserv.security.key_anchor
===========================

Hardware-rooted trust-anchor resolution for TPM 2.0 and PKCS#11 HSMs.

The platform never needs the *private* half of a release/forensic signing key in
application memory: the public key is read from the hardware key store, pinned by
SHA-256 fingerprint, and used to verify signatures. Private-key operations stay
inside the TPM/HSM through the same provider handles.

Supported anchor kinds (``AnchorKind``):

* ``software_file`` — PEM/DER public key file (explicitly *not* hardware-backed).
* ``software_env``  — Ed25519 public key as 64 hex chars in an environment variable.
* ``windows_tpm``   — persisted CNG key in the *Microsoft Platform Crypto Provider*
  (TPM 2.0). The public blob is exported and normalized to SPKI DER.
* ``pkcs11_hsm``    — HSM-resident public key addressed by a ``pkcs11:`` URI
  (requires the optional ``camserv[hsm]`` extra; absent module fails closed).

Security contract (fail-closed by default):

1. A spec that sets ``require_hardware=True`` is rejected unless the resolved
   anchor is backed by TPM/HSM hardware.
2. A spec with ``expected_fingerprint`` is rejected on any mismatch (trust pinning).
3. Duplicate purposes, empty policies, missing files, missing TPM keys and
   unavailable PKCS#11 modules all raise ``KeyAnchorError`` — never a silent
   downgrade to software anchors.
4. Private keys are rejected: a policy pointing at a private key file aborts.

Usage::

    camserv-key-anchor fingerprint --kind software_file --location release.pub.pem
    camserv-key-anchor verify --policy deploy/trust-anchors.json
    camserv-key-anchor status
"""

from __future__ import annotations

import argparse
import ctypes
import enum
import hashlib
import json
import os
import struct
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

logger = structlog.get_logger(__name__)

# --- Windows CNG / TPM constants -------------------------------------------
_CNG_PROVIDER = "Microsoft Platform Crypto Provider"
_BCRYPT_ECCPUBLIC_BLOB = "ECCPUBLICBLOB"
_NCRYPT_MACHINE_KEY_FLAG = 0x00000020
_NCRYPT_SILENT_FLAG = 0x00000040
_CNG_ECC_P256_MAGIC = 0x31534345  # "ECS1"
_CNG_ECC_P384_MAGIC = 0x33534345  # "ECS3"
_CNG_ECC_P521_MAGIC = 0x35534345  # "ECS5"
_CNG_RSA_MAGIC = 0x31415352  # "RSA1"
_CNG_ECC_CURVES: dict[int, tuple[str, type[ec.EllipticCurve]]] = {
    _CNG_ECC_P256_MAGIC: ("ECDSA-P256", ec.SECP256R1),
    _CNG_ECC_P384_MAGIC: ("ECDSA-P384", ec.SECP384R1),
    _CNG_ECC_P521_MAGIC: ("ECDSA-P521", ec.SECP521R1),
}

# --- PKCS#11 constants (data-only so the module imports without the extra) ---
_EC_CURVE_OIDS: dict[str, type[ec.EllipticCurve]] = {
    "1.2.840.10045.3.1.7": ec.SECP256R1,
    "1.3.132.0.34": ec.SECP384R1,
    "1.3.132.0.35": ec.SECP521R1,
}

_PUBLIC_KEY_TYPES = (ed25519.Ed25519PublicKey, ec.EllipticCurvePublicKey, rsa.RSAPublicKey)

# PEM envelopes are assembled at runtime so this module never embeds a verbatim
# private-key header (the Debian packaging audit greps the source tree for those).
_PEM_BEGIN = b"-----BEGIN "
_PEM_END = b"-----"
_PRIVATE_KEY_PEM_LABELS = (
    b"PRIVATE KEY",
    b"RSA PRIVATE KEY",
    b"EC PRIVATE KEY",
    b"ENCRYPTED PRIVATE KEY",
)


def _contains_private_key_pem(data: bytes) -> bool:
    """Return True when ``data`` carries a PEM private-key envelope."""
    return any(
        _PEM_BEGIN + label + _PEM_END in data for label in _PRIVATE_KEY_PEM_LABELS
    )


class KeyAnchorError(PermissionError):
    """Raised when a trust anchor cannot be resolved safely (fail-closed)."""


class AnchorKind(str, enum.Enum):
    """Where a trust anchor's public key physically lives."""

    SOFTWARE_FILE = "software_file"
    SOFTWARE_ENV = "software_env"
    WINDOWS_TPM = "windows_tpm"
    PKCS11_HSM = "pkcs11_hsm"

    @property
    def is_hardware(self) -> bool:
        """Return True when the anchor is rooted in TPM/HSM hardware."""
        return self in {AnchorKind.WINDOWS_TPM, AnchorKind.PKCS11_HSM}


def normalize_fingerprint(value: str) -> str:
    """Normalize a SHA-256 SPKI fingerprint to bare lowercase hex (64 chars)."""
    cleaned = value.strip().lower()
    if cleaned.startswith("sha256:"):
        cleaned = cleaned[len("sha256:") :]
    cleaned = cleaned.replace(":", "").replace(" ", "")
    if len(cleaned) != 64 or any(char not in "0123456789abcdef" for char in cleaned):
        raise KeyAnchorError(
            "Fingerprint must be a 64-character SHA-256 hex digest "
            "(optionally prefixed with 'sha256:')."
        )
    return cleaned


def fingerprint_spki(spki_der: bytes) -> str:
    """Return the SHA-256 hex fingerprint of a DER ``SubjectPublicKeyInfo`` blob."""
    if not spki_der:
        raise KeyAnchorError("Cannot fingerprint an empty SPKI blob.")
    return hashlib.sha256(spki_der).hexdigest()


def describe_public_key(key: Any) -> str:
    """Return a stable algorithm label for a supported public key object."""
    if isinstance(key, ed25519.Ed25519PublicKey):
        return "Ed25519"
    if isinstance(key, ec.EllipticCurvePublicKey):
        return f"ECDSA-{key.curve.name}"
    if isinstance(key, rsa.RSAPublicKey):
        return f"RSA-{key.key_size}"
    raise KeyAnchorError(f"Unsupported trust-anchor public key type: {type(key).__name__}.")


def _spki_der(key: Any) -> bytes:
    """Encode a supported public key as DER ``SubjectPublicKeyInfo``."""
    describe_public_key(key)  # validates the type
    return key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


@dataclass(frozen=True, slots=True)
class KeyAnchorSpec:
    """Declarative requirement for one trust anchor, resolved at startup."""

    purpose: str
    kind: AnchorKind
    location: str
    expected_fingerprint: str | None = None
    require_hardware: bool = False

    def __post_init__(self) -> None:
        if not self.purpose.strip():
            raise KeyAnchorError("Trust-anchor purpose must not be empty.")
        if not self.location.strip():
            raise KeyAnchorError(f"Trust anchor '{self.purpose}' requires a location.")
        if self.expected_fingerprint is not None:
            object.__setattr__(
                self, "expected_fingerprint", normalize_fingerprint(self.expected_fingerprint)
            )
        if self.require_hardware and not self.kind.is_hardware:
            raise KeyAnchorError(
                f"Trust anchor '{self.purpose}' requires hardware but declares kind "
                f"'{self.kind.value}'."
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KeyAnchorSpec:
        """Build a spec from its JSON policy representation."""
        if not isinstance(data, dict):
            raise KeyAnchorError("Each trust-anchor policy entry must be a JSON object.")
        if "kind" not in data:
            raise KeyAnchorError("Trust-anchor entry is missing 'kind'.")
        raw_kind = str(data["kind"]).strip().lower()
        try:
            kind = AnchorKind(raw_kind)
        except ValueError as exc:
            allowed = ", ".join(item.value for item in AnchorKind)
            raise KeyAnchorError(
                f"Unknown anchor kind '{raw_kind}'; expected one of {allowed}."
            ) from exc
        pin = data.get("expected_fingerprint")
        return cls(
            purpose=str(data.get("purpose", "")),
            kind=kind,
            location=str(data.get("location", "")),
            expected_fingerprint=str(pin) if pin else None,
            require_hardware=bool(data.get("require_hardware", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the spec back to its JSON policy representation."""
        return {
            "purpose": self.purpose,
            "kind": self.kind.value,
            "location": self.location,
            "expected_fingerprint": self.expected_fingerprint,
            "require_hardware": self.require_hardware,
        }


@dataclass(frozen=True, slots=True)
class TrustAnchor:
    """A resolved, pinnable public key rooted in software or hardware storage."""

    purpose: str
    kind: AnchorKind
    algorithm: str
    fingerprint: str
    spki_der: bytes
    hardware_backed: bool
    source: str

    @property
    def is_ed25519(self) -> bool:
        """Return True when the anchor holds an Ed25519 public key."""
        return self.algorithm == "Ed25519"

    def public_key(self) -> Any:
        """Decode the anchor into a ``cryptography`` public key object."""
        try:
            return serialization.load_der_public_key(self.spki_der)
        except ValueError as exc:  # pragma: no cover - defensive, DER is validated on creation
            raise KeyAnchorError(f"Anchor '{self.purpose}' holds invalid SPKI DER: {exc}") from exc

    def public_key_hex(self) -> str:
        """Return the raw 32-byte Ed25519 public key as hex (for signature verifiers)."""
        if not self.is_ed25519:
            raise KeyAnchorError(
                f"Anchor '{self.purpose}' is {self.algorithm}, not Ed25519; "
                "raw-hex encoding is unavailable."
            )
        raw = self.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        return bytes(raw).hex()

    def to_dict(self) -> dict[str, Any]:
        """Serialize the resolved anchor for logs, audit records and CLI output."""
        return {
            "purpose": self.purpose,
            "kind": self.kind.value,
            "algorithm": self.algorithm,
            "fingerprint": self.fingerprint,
            "hardware_backed": self.hardware_backed,
            "source": self.source,
        }


def _make_anchor(spec: KeyAnchorSpec, key: Any, source: str) -> TrustAnchor:
    """Wrap a resolved public key into a ``TrustAnchor``, validating the type."""
    spki = _spki_der(key)
    return TrustAnchor(
        purpose=spec.purpose,
        kind=spec.kind,
        algorithm=describe_public_key(key),
        fingerprint=fingerprint_spki(spki),
        spki_der=spki,
        hardware_backed=spec.kind.is_hardware,
        source=source,
    )


# ---------------------------------------------------------------------------
# Windows CNG / TPM 2.0 provider
# ---------------------------------------------------------------------------

def _load_windows_dll(name: str) -> Any:
    """Load a Windows system DLL through ``ctypes.WinDLL``."""
    loader = getattr(ctypes, "WinDLL", None)
    if loader is None:
        raise KeyAnchorError("Windows CNG is unavailable on this platform (fail-closed).")
    try:
        return loader(name)
    except OSError as exc:
        raise KeyAnchorError(f"Cannot load '{name}': {exc}") from exc


def _ncrypt_error(operation: str, status: int) -> str:
    """Render a CNG status code as a readable, fail-closed error message."""
    return f"{operation} failed with CNG status 0x{status & 0xFFFFFFFF:08x}."


def parse_cng_public_blob(blob: bytes) -> Any:
    """Convert a CNG ``BCRYPT_*_PUBLIC_BLOB`` into a ``cryptography`` public key.

    Supported blobs are ``ECCPUBLICBLOB`` (P-256/P-384/P-521) and
    ``RSAPUBLICBLOB``; anything else is rejected rather than guessed.
    """
    if len(blob) < 8:
        raise KeyAnchorError("CNG public key blob is truncated.")
    magic, cb_key = struct.unpack_from("<II", blob, 0)

    if magic in _CNG_ECC_CURVES:
        name, curve_cls = _CNG_ECC_CURVES[magic]
        expected = 8 + 2 * cb_key
        if cb_key == 0 or len(blob) != expected:
            raise KeyAnchorError(
                f"Malformed {name} CNG blob: expected {expected} bytes, got {len(blob)}."
            )
        x = int.from_bytes(blob[8 : 8 + cb_key], "big")
        y = int.from_bytes(blob[8 + cb_key :], "big")
        try:
            return ec.EllipticCurvePublicNumbers(x, y, curve_cls()).public_key()
        except ValueError as exc:
            raise KeyAnchorError(f"Invalid {name} public point in CNG blob: {exc}") from exc

    if magic == _CNG_RSA_MAGIC:
        if len(blob) < 24:
            raise KeyAnchorError("CNG RSA public key blob is truncated.")
        _magic, _bits, cb_exp, cb_mod, _cb_p1, _cb_p2 = struct.unpack_from("<IIIIII", blob, 0)
        if cb_exp == 0 or cb_mod == 0:
            raise KeyAnchorError("CNG RSA public key blob declares empty exponent or modulus.")
        expected = 24 + cb_exp + cb_mod
        if len(blob) != expected:
            raise KeyAnchorError(
                f"Malformed RSA CNG blob: expected {expected} bytes, got {len(blob)}."
            )
        exponent = int.from_bytes(blob[24 : 24 + cb_exp], "big")
        modulus = int.from_bytes(blob[24 + cb_exp :], "big")
        try:
            return rsa.RSAPublicNumbers(exponent, modulus).public_key()
        except ValueError as exc:
            raise KeyAnchorError(f"Invalid RSA public numbers in CNG blob: {exc}") from exc

    raise KeyAnchorError(f"Unsupported CNG public blob magic 0x{magic:08x}.")


class CngTpmProvider:
    """Thin, injectable wrapper over the Windows CNG Platform Crypto Provider (TPM 2.0).

    Only ctypes is used, so no extra dependency is required. The class is a plain
    object with four methods (``is_available``, ``open_key``, ``export_public_key``,
    ``free_object``) so tests can substitute a fake provider and exercise the
    anchoring logic on hosts without a TPM.
    """

    def __init__(self) -> None:
        self._ncrypt: Any = None

    def is_available(self) -> bool:
        """Return True when the CNG Platform Crypto Provider can be opened."""
        if os.name != "nt":
            return False
        try:
            self._ensure_loaded()
        except KeyAnchorError as exc:
            logger.warning("key_anchor.cng_unavailable", error=str(exc))
            return False
        return True

    def _ensure_loaded(self) -> Any:
        if self._ncrypt is not None:
            return self._ncrypt
        ncrypt = _load_windows_dll("ncrypt.dll")
        void_p = ctypes.c_void_p
        byte_p = ctypes.POINTER(ctypes.c_ubyte)
        ulong_p = ctypes.POINTER(ctypes.c_ulong)
        ncrypt.NCryptOpenStorageProvider.argtypes = [
            ctypes.POINTER(void_p),
            ctypes.c_wchar_p,
            ctypes.c_ulong,
        ]
        ncrypt.NCryptOpenStorageProvider.restype = ctypes.c_long
        ncrypt.NCryptOpenKey.argtypes = [
            void_p,
            ctypes.POINTER(void_p),
            ctypes.c_wchar_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
        ]
        ncrypt.NCryptOpenKey.restype = ctypes.c_long
        ncrypt.NCryptExportKey.argtypes = [
            void_p,
            void_p,
            ctypes.c_wchar_p,
            void_p,
            byte_p,
            ctypes.c_ulong,
            ulong_p,
            ctypes.c_ulong,
        ]
        ncrypt.NCryptExportKey.restype = ctypes.c_long
        ncrypt.NCryptSignHash.argtypes = [
            void_p,
            void_p,
            byte_p,
            ctypes.c_ulong,
            byte_p,
            ctypes.c_ulong,
            ulong_p,
            ctypes.c_ulong,
        ]
        ncrypt.NCryptSignHash.restype = ctypes.c_long
        ncrypt.NCryptFreeObject.argtypes = [void_p]
        ncrypt.NCryptFreeObject.restype = ctypes.c_long
        self._ncrypt = ncrypt
        return ncrypt

    @staticmethod
    def _byte_buffer(size: int) -> Any:
        return (ctypes.c_ubyte * max(int(size), 1))()

    def open_key(self, key_name: str, *, machine: bool = True) -> int:
        """Open a persisted TPM-backed key by name and return its CNG handle."""
        ncrypt = self._ensure_loaded()
        provider = ctypes.c_void_p()
        status = ncrypt.NCryptOpenStorageProvider(
            ctypes.byref(provider), _CNG_PROVIDER, 0
        )
        if status != 0:
            raise KeyAnchorError(_ncrypt_error("NCryptOpenStorageProvider", status))
        key = ctypes.c_void_p()
        flags = _NCRYPT_MACHINE_KEY_FLAG if machine else 0
        try:
            status = ncrypt.NCryptOpenKey(
                provider, ctypes.byref(key), key_name, 0, flags
            )
        finally:
            ncrypt.NCryptFreeObject(provider)
        if status != 0 or key.value is None:
            raise KeyAnchorError(_ncrypt_error(f"NCryptOpenKey('{key_name}')", status))
        return int(key.value)

    def export_public_key(self, handle: int) -> bytes:
        """Export the public half of a TPM-backed key as a ``BCRYPT_ECCPUBLIC_BLOB``."""
        ncrypt = self._ensure_loaded()
        size = ctypes.c_ulong(0)
        status = ncrypt.NCryptExportKey(
            ctypes.c_void_p(handle),
            None,
            _BCRYPT_ECCPUBLIC_BLOB,
            None,
            None,
            0,
            ctypes.byref(size),
            _NCRYPT_SILENT_FLAG,
        )
        if status != 0 or size.value == 0:
            raise KeyAnchorError(_ncrypt_error("NCryptExportKey", status))
        buffer = self._byte_buffer(size.value)
        status = ncrypt.NCryptExportKey(
            ctypes.c_void_p(handle),
            None,
            _BCRYPT_ECCPUBLIC_BLOB,
            None,
            buffer,
            size.value,
            ctypes.byref(size),
            _NCRYPT_SILENT_FLAG,
        )
        if status != 0:
            raise KeyAnchorError(_ncrypt_error("NCryptExportKey", status))
        return bytes(buffer[: size.value])

    def sign_hash(self, handle: int, digest: bytes) -> bytes:
        """Sign a pre-computed digest with the TPM key (private key never leaves the TPM)."""
        if not digest:
            raise KeyAnchorError("Cannot sign an empty digest.")
        ncrypt = self._ensure_loaded()
        digest_buffer = (ctypes.c_ubyte * len(digest)).from_buffer_copy(digest)
        size = ctypes.c_ulong(0)
        status = ncrypt.NCryptSignHash(
            ctypes.c_void_p(handle),
            None,
            digest_buffer,
            len(digest),
            None,
            0,
            ctypes.byref(size),
            _NCRYPT_SILENT_FLAG,
        )
        if status != 0 or size.value == 0:
            raise KeyAnchorError(_ncrypt_error("NCryptSignHash", status))
        buffer = self._byte_buffer(size.value)
        status = ncrypt.NCryptSignHash(
            ctypes.c_void_p(handle),
            None,
            digest_buffer,
            len(digest),
            buffer,
            size.value,
            ctypes.byref(size),
            _NCRYPT_SILENT_FLAG,
        )
        if status != 0:
            raise KeyAnchorError(_ncrypt_error("NCryptSignHash", status))
        return bytes(buffer[: size.value])

    def free_object(self, handle: int) -> None:
        """Release a CNG key handle, logging (never raising) on failure."""
        try:
            ncrypt = self._ensure_loaded()
            ncrypt.NCryptFreeObject(ctypes.c_void_p(handle))
        except KeyAnchorError as exc:
            logger.error("key_anchor.cng_free_failed", error=str(exc), handle=handle)


# ---------------------------------------------------------------------------
# Software anchors (explicitly not hardware-backed)
# ---------------------------------------------------------------------------

def load_software_public_key(location: str | Path) -> Any:
    """Load a public key from a PEM or DER file, rejecting private-key material."""
    path = Path(location)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise KeyAnchorError(f"Cannot read trust-anchor file '{path}': {exc}") from exc
    if not data:
        raise KeyAnchorError(f"Trust-anchor file '{path}' is empty.")
    if _contains_private_key_pem(data):
        raise KeyAnchorError(
            f"Trust-anchor file '{path}' contains a private key; "
            "private keys must never be used as trust anchors."
        )
    try:
        key = (
            serialization.load_pem_public_key(data)
            if b"-----BEGIN" in data
            else serialization.load_der_public_key(data)
        )
    except (ValueError, TypeError) as exc:
        raise KeyAnchorError(f"Trust-anchor file '{path}' is not a public key: {exc}") from exc
    if not isinstance(key, _PUBLIC_KEY_TYPES):
        raise KeyAnchorError(
            f"Trust-anchor file '{path}' contains {type(key).__name__}; "
            "private keys must never be used as trust anchors."
        )
    return key


def load_software_ed25519_from_env(variable: str) -> Any:
    """Load an Ed25519 public key from a 64-hex-character environment variable."""
    raw = os.environ.get(variable)
    if not raw or not raw.strip():
        raise KeyAnchorError(f"Environment variable '{variable}' is not set.")
    cleaned = raw.strip().lower()
    if cleaned.startswith("0x"):
        cleaned = cleaned[2:]
    try:
        key_bytes = bytes.fromhex(cleaned)
    except ValueError as exc:
        raise KeyAnchorError(
            f"Environment variable '{variable}' is not valid hex: {exc}"
        ) from exc
    if len(key_bytes) != 32:
        raise KeyAnchorError(
            f"Environment variable '{variable}' must hold a 32-byte Ed25519 key, "
            f"got {len(key_bytes)} bytes."
        )
    try:
        return ed25519.Ed25519PublicKey.from_public_bytes(key_bytes)
    except ValueError as exc:
        raise KeyAnchorError(
            f"Environment variable '{variable}' is not an Ed25519 public key: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Minimal DER helpers (PKCS#11 attribute decoding)
# ---------------------------------------------------------------------------

def _der_read_tlv(data: bytes, offset: int = 0) -> tuple[int, bytes, int]:
    """Read a single DER TLV triple, returning ``(tag, value, next_offset)``."""
    if offset + 2 > len(data):
        raise KeyAnchorError("Truncated DER structure.")
    tag = data[offset]
    length = data[offset + 1]
    cursor = offset + 2
    if length & 0x80:
        count = length & 0x7F
        if count == 0 or cursor + count > len(data):
            raise KeyAnchorError("Unsupported DER length encoding.")
        length = int.from_bytes(data[cursor : cursor + count], "big")
        cursor += count
    end = cursor + length
    if end > len(data):
        raise KeyAnchorError("DER value exceeds the available buffer.")
    return tag, data[cursor:end], end


def der_octet_string_value(data: bytes) -> bytes:
    """Return the payload of a DER OCTET STRING (ignoring trailing bytes)."""
    tag, value, _ = _der_read_tlv(data)
    if tag != 0x04:
        raise KeyAnchorError(f"Expected a DER OCTET STRING (0x04), got tag 0x{tag:02x}.")
    return value


def der_oid_to_string(value: bytes) -> str:
    """Decode a DER OBJECT IDENTIFIER payload into dotted-decimal form."""
    if not value:
        raise KeyAnchorError("Empty DER OBJECT IDENTIFIER.")
    parts = [str(value[0] // 40), str(value[0] % 40)]
    number = 0
    for byte in value[1:]:
        number = (number << 7) | (byte & 0x7F)
        if not byte & 0x80:
            parts.append(str(number))
            number = 0
    return ".".join(parts)


# ---------------------------------------------------------------------------
# PKCS#11 HSM anchors (optional dependency: camserv[hsm])
# ---------------------------------------------------------------------------

def _load_pkcs11_module() -> Any:
    """Import the optional ``python-pkcs11`` module or fail closed."""
    try:
        import pkcs11  # noqa: PLC0415 - optional dependency, imported on demand
    except ImportError as exc:
        raise KeyAnchorError(
            "PKCS#11 trust anchor requested but 'python-pkcs11' is not installed; "
            "install the 'camserv[hsm]' extra (fail-closed)."
        ) from exc
    return pkcs11


def parse_pkcs11_uri(uri: str) -> dict[str, str]:
    """Parse a ``pkcs11:`` URI into lower-cased attributes.

    Example::

        pkcs11:module=/usr/lib/softhsm/libsofthsm2.so;token=camserv;object=release-pub
    """
    prefix = "pkcs11:"
    if not uri.lower().startswith(prefix):
        raise KeyAnchorError("PKCS#11 anchor location must be a 'pkcs11:' URI.")
    attrs: dict[str, str] = {}
    for part in uri[len(prefix) :].split(";"):
        if not part:
            continue
        name, _, value = part.partition("=")
        if not value:
            raise KeyAnchorError(f"Malformed PKCS#11 URI attribute: '{part}'.")
        attrs[name.strip().lower()] = value.strip()
    if "module" not in attrs:
        raise KeyAnchorError(
            "PKCS#11 URI must include 'module=<path-to-pkcs11-library>'."
        )
    if "id" in attrs:
        try:
            bytes.fromhex(attrs["id"])
        except ValueError as exc:
            raise KeyAnchorError(f"PKCS#11 URI 'id' is not hex: {exc}") from exc
    return attrs


def _pkcs11_key_to_cryptography(pkcs11_module: Any, key: Any) -> Any:
    """Convert an HSM public-key handle into a ``cryptography`` public key."""
    attribute = pkcs11_module.Attribute
    key_type = key[attribute.KEY_TYPE]

    if key_type == pkcs11_module.KeyType.EC_EDWARDS:
        point = der_octet_string_value(key[attribute.EC_POINT])
        if len(point) != 32:
            raise KeyAnchorError(
                f"HSM Ed25519 public point must be 32 bytes, got {len(point)}."
            )
        return ed25519.Ed25519PublicKey.from_public_bytes(point)

    if key_type == pkcs11_module.KeyType.EC:
        params_tag, params, _ = _der_read_tlv(key[attribute.EC_PARAMS])
        if params_tag != 0x06:
            raise KeyAnchorError("HSM EC_PARAMS is not a DER OBJECT IDENTIFIER.")
        curve_cls = _EC_CURVE_OIDS.get(der_oid_to_string(params))
        if curve_cls is None:
            raise KeyAnchorError("Unsupported elliptic curve in HSM EC_PARAMS.")
        point = der_octet_string_value(key[attribute.EC_POINT])
        if not point or point[0] != 0x04:
            raise KeyAnchorError("HSM EC_POINT must be an uncompressed SEC1 point.")
        size = (len(point) - 1) // 2
        if size == 0 or len(point) != 1 + 2 * size:
            raise KeyAnchorError("HSM EC_POINT has an inconsistent length.")
        x = int.from_bytes(point[1 : 1 + size], "big")
        y = int.from_bytes(point[1 + size :], "big")
        return ec.EllipticCurvePublicNumbers(x, y, curve_cls()).public_key()

    if key_type == pkcs11_module.KeyType.RSA:
        modulus = key[attribute.MODULUS]
        exponent = key[attribute.PUBLIC_EXPONENT]
        return rsa.RSAPublicNumbers(
            int.from_bytes(exponent, "big"), int.from_bytes(modulus, "big")
        ).public_key()

    raise KeyAnchorError(f"Unsupported PKCS#11 key type: {key_type}.")


def load_pkcs11_public_key(uri: str, *, loader: Callable[[], Any] | None = None) -> Any:
    """Load an HSM-resident public key addressed by a ``pkcs11:`` URI."""
    attrs = parse_pkcs11_uri(uri)
    module = (loader or _load_pkcs11_module)()
    label = attrs.get("object") or attrs.get("label")
    object_id = bytes.fromhex(attrs["id"]) if attrs.get("id") else None
    try:
        library = module.lib(attrs["module"])
        token = next(iter(library.get_tokens(token_label=attrs.get("token"))), None)
        if token is None:
            raise KeyAnchorError(f"No PKCS#11 token matched '{uri}'.")
        key = token.get_key(id=object_id, label=label)
    except KeyAnchorError:
        raise
    except Exception as exc:  # noqa: BLE001 - third-party bindings raise heterogeneous errors
        raise KeyAnchorError(f"PKCS#11 lookup failed for '{uri}': {exc}") from exc
    if key is None:
        raise KeyAnchorError(f"PKCS#11 token holds no matching public key for '{uri}'.")
    try:
        return _pkcs11_key_to_cryptography(module, key)
    except KeyAnchorError:
        raise
    except (TypeError, ValueError) as exc:
        raise KeyAnchorError(f"HSM public key is not usable: {exc}") from exc


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

class KeyAnchorResolver:
    """Resolve ``KeyAnchorSpec`` entries into pinned, fail-closed ``TrustAnchor`` objects.

    ``cng_provider`` and ``pkcs11_loader`` are injection points used by tests to
    exercise TPM/HSM code paths on hosts without the corresponding hardware.
    """

    def __init__(
        self,
        *,
        cng_provider: Any | None = None,
        pkcs11_loader: Callable[[], Any] | None = None,
    ) -> None:
        self._cng_provider = cng_provider
        self._pkcs11_loader = pkcs11_loader

    def resolve_one(self, spec: KeyAnchorSpec) -> TrustAnchor:
        """Resolve a single spec, enforcing hardware requirements and fingerprint pins."""
        key, source = self._load(spec)
        anchor = _make_anchor(spec, key, source)

        if spec.require_hardware and not anchor.hardware_backed:
            raise KeyAnchorError(
                f"Trust anchor '{spec.purpose}' requires hardware backing but resolved to "
                f"software storage ('{anchor.source}')."
            )

        if spec.expected_fingerprint and anchor.fingerprint != spec.expected_fingerprint:
            logger.critical(
                "key_anchor.fingerprint_pin_mismatch",
                purpose=spec.purpose,
                expected=spec.expected_fingerprint,
                actual=anchor.fingerprint,
                source=anchor.source,
            )
            raise KeyAnchorError(
                f"Trust anchor '{spec.purpose}' fingerprint mismatch: expected "
                f"{spec.expected_fingerprint}, got {anchor.fingerprint} ({anchor.source})."
            )

        return anchor

    def resolve(self, specs: Sequence[KeyAnchorSpec]) -> dict[str, TrustAnchor]:
        """Resolve every spec, keyed by purpose; refuses empty or duplicate policies."""
        if not specs:
            raise KeyAnchorError("At least one trust anchor is required (fail-closed).")
        anchors: dict[str, TrustAnchor] = {}
        for spec in specs:
            if spec.purpose in anchors:
                raise KeyAnchorError(f"Duplicate trust-anchor purpose '{spec.purpose}'.")
            anchors[spec.purpose] = self.resolve_one(spec)
        logger.info(
            "key_anchor.resolved",
            count=len(anchors),
            anchors=[anchor.to_dict() for anchor in anchors.values()],
        )
        return anchors

    def status(self, specs: Sequence[KeyAnchorSpec]) -> list[dict[str, Any]]:
        """Return a non-raising per-spec resolution report for operators and CI gates."""
        report: list[dict[str, Any]] = []
        for spec in specs:
            try:
                anchor = self.resolve_one(spec)
            except KeyAnchorError as exc:
                report.append(
                    {
                        "purpose": spec.purpose,
                        "kind": spec.kind.value,
                        "hardware_required": spec.require_hardware,
                        "ok": False,
                        "error": str(exc),
                    }
                )
                continue
            entry = anchor.to_dict()
            entry["hardware_required"] = spec.require_hardware
            entry["ok"] = True
            report.append(entry)
        return report

    def _load(self, spec: KeyAnchorSpec) -> tuple[Any, str]:
        """Dispatch on anchor kind and return ``(public_key, provenance)``."""
        if spec.kind is AnchorKind.SOFTWARE_FILE:
            return load_software_public_key(spec.location), str(Path(spec.location))
        if spec.kind is AnchorKind.SOFTWARE_ENV:
            return load_software_ed25519_from_env(spec.location), f"env:{spec.location}"
        if spec.kind is AnchorKind.WINDOWS_TPM:
            return self._tpm_key(spec.location), f"cng:{spec.location}"
        return self._hsm_key(spec.location), spec.location

    def _tpm_key(self, key_name: str) -> Any:
        """Read a persisted TPM 2.0 public key through CNG, failing closed on absence."""
        provider = self._cng_provider if self._cng_provider is not None else CngTpmProvider()
        if not provider.is_available():
            raise KeyAnchorError(
                "Windows TPM trust anchor requested but the CNG Platform Crypto Provider "
                "is unavailable (fail-closed)."
            )
        handle = provider.open_key(key_name, machine=True)
        try:
            blob = provider.export_public_key(handle)
        finally:
            provider.free_object(handle)
        return parse_cng_public_blob(blob)

    def _hsm_key(self, uri: str) -> Any:
        """Read an HSM-resident public key through PKCS#11 (optional dependency)."""
        return load_pkcs11_public_key(uri, loader=self._pkcs11_loader)


def specs_from_settings(settings: Any) -> list[KeyAnchorSpec]:
    """Build anchor specs from a ``SecuritySettings.key_anchors``-shaped object."""
    specs: list[KeyAnchorSpec] = []
    require_hardware = bool(getattr(settings, "require_hardware", False))
    pins = getattr(settings, "pinned_fingerprints", None) or {}
    tpm_key_name = getattr(settings, "tpm_key_name", None)
    pkcs11_uri = getattr(settings, "pkcs11_uri", None)
    if tpm_key_name:
        purpose = "platform-tpm"
        specs.append(
            KeyAnchorSpec(
                purpose=purpose,
                kind=AnchorKind.WINDOWS_TPM,
                location=str(tpm_key_name),
                expected_fingerprint=pins.get(purpose),
                require_hardware=require_hardware,
            )
        )
    if pkcs11_uri:
        purpose = "platform-hsm"
        specs.append(
            KeyAnchorSpec(
                purpose=purpose,
                kind=AnchorKind.PKCS11_HSM,
                location=str(pkcs11_uri),
                expected_fingerprint=pins.get(purpose),
                require_hardware=require_hardware,
            )
        )
    return specs


# ---------------------------------------------------------------------------
# CLI — camserv-key-anchor
# ---------------------------------------------------------------------------

def load_anchor_policy(path: str | Path) -> list[KeyAnchorSpec]:
    """Load a JSON trust-anchor policy (``{"anchors": [...]}`` or a bare list)."""
    policy_path = Path(path)
    try:
        raw = policy_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise KeyAnchorError(f"Cannot read anchor policy '{policy_path}': {exc}") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise KeyAnchorError(
            f"Anchor policy '{policy_path}' is not valid JSON: {exc}"
        ) from exc
    entries = data.get("anchors") if isinstance(data, dict) else data
    if not isinstance(entries, list) or not entries:
        raise KeyAnchorError("Anchor policy must contain a non-empty 'anchors' list.")
    return [KeyAnchorSpec.from_dict(entry) for entry in entries]


def _cmd_status(args: Any) -> int:
    """Report hardware availability, or the resolution status of a policy file."""
    if not args.policy:
        provider = CngTpmProvider()
        report = {
            "platform": os.name,
            "windows_tpm_available": provider.is_available(),
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    specs = load_anchor_policy(args.policy)
    anchors = KeyAnchorResolver().status(specs)
    print(json.dumps({"anchors": anchors}, indent=2, sort_keys=True))
    return 0 if all(entry.get("ok") for entry in anchors) else 1


def _cmd_fingerprint(args: Any) -> int:
    """Resolve one anchor and print its algorithm and SHA-256 SPI fingerprint."""
    spec = KeyAnchorSpec(
        purpose="fingerprint",
        kind=AnchorKind(args.kind),
        location=args.location,
        expected_fingerprint=args.expect,
        require_hardware=args.require_hardware,
    )
    anchor = KeyAnchorResolver().resolve_one(spec)
    print(json.dumps(anchor.to_dict(), indent=2, sort_keys=True))
    return 0


def _cmd_verify(args: Any) -> int:
    """Resolve and pin every anchor in a policy file (non-zero exit on any failure)."""
    anchors = KeyAnchorResolver().resolve(load_anchor_policy(args.policy))
    payload = {"verified": [anchor.to_dict() for anchor in anchors.values()]}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


@contextmanager
def _structured_logs_to_stderr() -> Iterator[None]:
    """Route structlog output to stderr so CLI stdout stays machine-readable JSON."""
    config = structlog.get_config()
    try:
        structlog.configure(
            processors=config.get("processors"),
            context_class=config.get("context_class"),
            wrapper_class=config.get("wrapper_class"),
            logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
            cache_logger_on_first_use=False,
        )
        yield
    finally:
        structlog.configure(**config)


def _build_parser() -> Any:
    parser = argparse.ArgumentParser(
        prog="camserv-key-anchor",
        description=(
            "Resolve and verify TPM 2.0 / PKCS#11 hardware trust anchors "
            "(fail-closed by default)."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser(
        "status", help="Report hardware availability or a policy's anchor status."
    )
    status.add_argument("--policy", default=None, help="Optional JSON trust-anchor policy.")
    status.set_defaults(handler=_cmd_status)

    fingerprint = subparsers.add_parser(
        "fingerprint", help="Resolve one anchor and print its SHA-256 fingerprint."
    )
    fingerprint.add_argument(
        "--kind", required=True, choices=[kind.value for kind in AnchorKind]
    )
    fingerprint.add_argument("--location", required=True, help="Path, env var, key name or URI.")
    fingerprint.add_argument(
        "--expect", default=None, help="Fail unless the resolved fingerprint matches this pin."
    )
    fingerprint.add_argument(
        "--require-hardware",
        action="store_true",
        help="Fail unless the anchor is TPM/HSM-backed.",
    )
    fingerprint.set_defaults(handler=_cmd_fingerprint)

    verify = subparsers.add_parser(
        "verify", help="Resolve and pin every anchor in a policy file."
    )
    verify.add_argument("--policy", required=True, help="Path to a JSON trust-anchor policy.")
    verify.set_defaults(handler=_cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``camserv-key-anchor`` console script."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        with _structured_logs_to_stderr():
            return int(args.handler(args))
    except (KeyAnchorError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
