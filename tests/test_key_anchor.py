"""Unit and adversarial tests for hardware-rooted trust anchors (TPM 2.0 / PKCS#11).

Covers:

* Software PEM/DER and environment anchors, including private-key rejection.
* SHA-256 SPKI fingerprint pinning and fail-closed mismatches.
* Policy validation: empty policies, duplicate purposes, hardware-required anchors.
* CNG public blob parsing (EC P-256 / RSA) and TPM resolution through a fake provider,
  so CI validates the anchoring logic without a physical TPM.
* PKCS#11 URI parsing, missing-module fail-closed behaviour, and HSM key decoding
  through an injected fake module.
* Integration with ``SignedModelInstaller`` / ``SignedUpdateManager`` and the CLI.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

from camserv.config.settings import JWTSettings, SecuritySettings
from camserv.deploy.model_installer import (
    ModelManifest,
    ModelSignatureError,
    SignedModelInstaller,
)
from camserv.deploy.updater import SignedUpdateManager, UpdateSignatureError
from camserv.security.key_anchor import (
    AnchorKind,
    KeyAnchorError,
    KeyAnchorResolver,
    KeyAnchorSpec,
    TrustAnchor,
    der_octet_string_value,
    fingerprint_spki,
    load_anchor_policy,
    load_pkcs11_public_key,
    load_software_public_key,
    main,
    normalize_fingerprint,
    parse_cng_public_blob,
    parse_pkcs11_uri,
    specs_from_settings,
)

_P256_OID = b"\x06\x08\x2a\x86\x48\xce\x3d\x03\x01\x07"


# ---------------------------------------------------------------------------
# Helpers and fakes
# ---------------------------------------------------------------------------

def _spki_der(key: Any) -> bytes:
    return key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def _write_public_pem(path: Path, key: Any) -> Path:
    path.write_bytes(
        key.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    return path


def _write_private_pem(path: Path, key: ed25519.Ed25519PrivateKey) -> Path:
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return path


def _der_octet_string(payload: bytes) -> bytes:
    length = len(payload)
    if length < 0x80:
        return b"\x04" + bytes([length]) + payload
    encoded = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return b"\x04" + bytes([0x80 | len(encoded)]) + encoded + payload


def _cng_ecc_blob(public_key: ec.EllipticCurvePublicKey) -> bytes:
    numbers = public_key.public_numbers()
    size = (public_key.curve.key_size + 7) // 8
    magic = {256: 0x31534345, 384: 0x33534345, 521: 0x35534345}[public_key.curve.key_size]
    return (
        struct.pack("<II", magic, size)
        + numbers.x.to_bytes(size, "big")
        + numbers.y.to_bytes(size, "big")
    )


def _cng_rsa_blob(public_key: rsa.RSAPublicKey) -> bytes:
    numbers = public_key.public_numbers()
    modulus = numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")
    exponent = numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")
    header = struct.pack(
        "<IIIIII", 0x31415352, public_key.key_size, len(exponent), len(modulus), 0, 0
    )
    return header + exponent + modulus


class FakeCngProvider:
    """Deterministic stand-in for :class:`CngTpmProvider` (no physical TPM needed)."""

    def __init__(self, blob: bytes, *, available: bool = True) -> None:
        self.blob = blob
        self.available = available
        self.opened: list[str] = []
        self.freed: list[int] = []

    def is_available(self) -> bool:
        return self.available

    def open_key(self, key_name: str, *, machine: bool = True) -> int:
        self.opened.append(key_name)
        return 0x5A5A

    def export_public_key(self, handle: int) -> bytes:
        assert handle == 0x5A5A
        return self.blob

    def free_object(self, handle: int) -> None:
        self.freed.append(handle)


class _FakeAttribute:
    KEY_TYPE = "KEY_TYPE"
    EC_POINT = "EC_POINT"
    EC_PARAMS = "EC_PARAMS"
    MODULUS = "MODULUS"
    PUBLIC_EXPONENT = "PUBLIC_EXPONENT"


class _FakeKeyType:
    EC_EDWARDS = "EC_EDWARDS"
    EC = "EC"
    RSA = "RSA"


class _FakeHsmKey:
    def __init__(self, attributes: dict[str, Any]) -> None:
        self._attributes = attributes

    def __getitem__(self, name: str) -> Any:
        return self._attributes[name]


class _FakeToken:
    def __init__(self, key: _FakeHsmKey) -> None:
        self._key = key
        self.calls: list[dict[str, Any]] = []

    def get_key(self, **kwargs: Any) -> _FakeHsmKey:
        self.calls.append(kwargs)
        return self._key


class _FakeLibrary:
    def __init__(self, token: _FakeToken) -> None:
        self._token = token

    def get_tokens(self, token_label: str | None = None) -> list[_FakeToken]:
        return [self._token] if token_label in (None, "camserv") else []


class FakePkcs11Module:
    """Minimal ``python-pkcs11`` stand-in exposing only what the resolver needs."""

    Attribute = _FakeAttribute
    KeyType = _FakeKeyType

    def __init__(self, token: _FakeToken) -> None:
        self._library = _FakeLibrary(token)

    def lib(self, path: str) -> _FakeLibrary:
        assert path
        return self._library


# ---------------------------------------------------------------------------
# Software anchors and fingerprint pinning
# ---------------------------------------------------------------------------

def test_software_file_anchor_resolves_ed25519(tmp_path: Path) -> None:
    private = ed25519.Ed25519PrivateKey.generate()
    public = private.public_key()
    pem = _write_public_pem(tmp_path / "release.pem", public)

    spec = KeyAnchorSpec(
        purpose="model-authority", kind=AnchorKind.SOFTWARE_FILE, location=str(pem)
    )
    anchor = KeyAnchorResolver().resolve_one(spec)

    assert anchor.kind is AnchorKind.SOFTWARE_FILE
    assert anchor.algorithm == "Ed25519"
    assert anchor.hardware_backed is False
    assert anchor.source == str(pem)
    assert anchor.fingerprint == fingerprint_spki(_spki_der(public))
    assert anchor.public_key_hex() == public.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()
    assert anchor.to_dict()["purpose"] == "model-authority"


def test_software_file_anchor_accepts_der(tmp_path: Path) -> None:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    der_path = tmp_path / "release.der"
    der_path.write_bytes(_spki_der(private.public_key()))

    spec = KeyAnchorSpec("ota-authority", AnchorKind.SOFTWARE_FILE, str(der_path))
    anchor = KeyAnchorResolver().resolve_one(spec)

    assert anchor.algorithm == "RSA-2048"
    assert anchor.is_ed25519 is False
    with pytest.raises(KeyAnchorError, match="raw-hex encoding is unavailable"):
        anchor.public_key_hex()


def test_private_key_file_is_rejected_as_anchor(tmp_path: Path) -> None:
    path = _write_private_pem(
        tmp_path / "private.pem", ed25519.Ed25519PrivateKey.generate()
    )
    with pytest.raises(KeyAnchorError, match="private keys must never be used"):
        load_software_public_key(path)


def test_missing_anchor_file_fails_closed(tmp_path: Path) -> None:
    spec = KeyAnchorSpec(
        "model-authority", AnchorKind.SOFTWARE_FILE, str(tmp_path / "absent.pem")
    )
    with pytest.raises(KeyAnchorError, match="Cannot read trust-anchor file"):
        KeyAnchorResolver().resolve_one(spec)


def test_empty_anchor_file_fails_closed(tmp_path: Path) -> None:
    empty = tmp_path / "empty.pem"
    empty.write_bytes(b"")
    with pytest.raises(KeyAnchorError, match="is empty"):
        load_software_public_key(empty)


def test_software_env_anchor_accepts_hex(monkeypatch: pytest.MonkeyPatch) -> None:
    public = ed25519.Ed25519PrivateKey.generate().public_key()
    raw_hex = public.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()
    monkeypatch.setenv("CAMSERV_TEST_ANCHOR", "0x" + raw_hex.upper())

    spec = KeyAnchorSpec("model-authority", AnchorKind.SOFTWARE_ENV, "CAMSERV_TEST_ANCHOR")
    anchor = KeyAnchorResolver().resolve_one(spec)

    assert anchor.public_key_hex() == raw_hex
    assert anchor.source == "env:CAMSERV_TEST_ANCHOR"
    assert anchor.hardware_backed is False


@pytest.mark.parametrize("value", ["zz" * 32, "00" * 16, ""])
def test_software_env_anchor_rejects_malformed_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("CAMSERV_TEST_ANCHOR", value)
    spec = KeyAnchorSpec("model-authority", AnchorKind.SOFTWARE_ENV, "CAMSERV_TEST_ANCHOR")
    with pytest.raises(KeyAnchorError):
        KeyAnchorResolver().resolve_one(spec)


def test_fingerprint_pin_mismatch_fails_closed(tmp_path: Path) -> None:
    public = ed25519.Ed25519PrivateKey.generate().public_key()
    pem = _write_public_pem(tmp_path / "release.pem", public)
    spec = KeyAnchorSpec(
        "model-authority",
        AnchorKind.SOFTWARE_FILE,
        str(pem),
        expected_fingerprint="00" * 32,
    )
    with pytest.raises(KeyAnchorError, match="fingerprint mismatch"):
        KeyAnchorResolver().resolve_one(spec)


def test_fingerprint_pin_accepts_colon_and_prefix_formatting(tmp_path: Path) -> None:
    public = ed25519.Ed25519PrivateKey.generate().public_key()
    pem = _write_public_pem(tmp_path / "release.pem", public)
    digest = fingerprint_spki(_spki_der(public))
    formatted = "sha256:" + ":".join(
        digest[index : index + 2] for index in range(0, 64, 2)
    ).upper()

    spec = KeyAnchorSpec(
        "model-authority",
        AnchorKind.SOFTWARE_FILE,
        str(pem),
        expected_fingerprint=formatted,
    )
    assert KeyAnchorResolver().resolve_one(spec).fingerprint == digest


def test_normalize_fingerprint_rejects_invalid_length() -> None:
    with pytest.raises(KeyAnchorError, match="64-character"):
        normalize_fingerprint("abc")


# ---------------------------------------------------------------------------
# Policy validation
# ---------------------------------------------------------------------------

def test_empty_policy_fails_closed() -> None:
    with pytest.raises(KeyAnchorError, match="At least one trust anchor"):
        KeyAnchorResolver().resolve([])


def test_duplicate_purpose_is_rejected(tmp_path: Path) -> None:
    pem = _write_public_pem(
        tmp_path / "release.pem", ed25519.Ed25519PrivateKey.generate().public_key()
    )
    specs = [
        KeyAnchorSpec("model-authority", AnchorKind.SOFTWARE_FILE, str(pem)),
        KeyAnchorSpec("model-authority", AnchorKind.SOFTWARE_FILE, str(pem)),
    ]
    with pytest.raises(KeyAnchorError, match="Duplicate trust-anchor purpose"):
        KeyAnchorResolver().resolve(specs)


def test_require_hardware_rejects_software_kind() -> None:
    with pytest.raises(KeyAnchorError, match="requires hardware"):
        KeyAnchorSpec(
            "model-authority",
            AnchorKind.SOFTWARE_FILE,
            "release.pem",
            require_hardware=True,
        )


def test_spec_from_dict_rejects_unknown_kind() -> None:
    with pytest.raises(KeyAnchorError, match="Unknown anchor kind"):
        KeyAnchorSpec.from_dict({"purpose": "x", "kind": "yubikey", "location": "y"})


def test_spec_from_dict_normalizes_pin_and_roundtrips() -> None:
    with pytest.raises(KeyAnchorError, match="missing 'kind'"):
        KeyAnchorSpec.from_dict({"purpose": "x", "location": "y"})

    spec = KeyAnchorSpec.from_dict(
        {
            "purpose": "x",
            "kind": "software_file",
            "location": "release.pem",
            "expected_fingerprint": "sha256:" + "A" * 64,
        }
    )
    assert spec.expected_fingerprint == "a" * 64
    assert spec.to_dict()["kind"] == "software_file"


# ---------------------------------------------------------------------------
# CNG blob parsing (TPM 2.0 public key export)
# ---------------------------------------------------------------------------

def test_parse_cng_ecc_p256_blob_roundtrip() -> None:
    public = ec.generate_private_key(ec.SECP256R1()).public_key()
    parsed = parse_cng_public_blob(_cng_ecc_blob(public))

    assert parsed.public_numbers() == public.public_numbers()
    assert _spki_der(parsed) == _spki_der(public)


def test_parse_cng_rsa_blob_roundtrip() -> None:
    public = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    parsed = parse_cng_public_blob(_cng_rsa_blob(public))

    assert parsed.public_numbers() == public.public_numbers()
    assert _spki_der(parsed) == _spki_der(public)


def test_parse_cng_blob_rejects_truncated_and_unknown_magic() -> None:
    with pytest.raises(KeyAnchorError, match="truncated"):
        parse_cng_public_blob(b"\x45\x43\x53\x31")
    with pytest.raises(KeyAnchorError, match="Unsupported CNG public blob magic"):
        parse_cng_public_blob(b"\x00\x00\x00\x00" + b"\x00" * 12)


def test_parse_cng_ecc_blob_rejects_inconsistent_length() -> None:
    public = ec.generate_private_key(ec.SECP256R1()).public_key()
    blob = _cng_ecc_blob(public)
    with pytest.raises(KeyAnchorError, match="Malformed ECDSA-P256 CNG blob"):
        parse_cng_public_blob(blob[:-4])


# ---------------------------------------------------------------------------
# Windows TPM 2.0 anchoring (fake CNG provider — no hardware required)
# ---------------------------------------------------------------------------

def test_windows_tpm_anchor_is_hardware_backed() -> None:
    public = ec.generate_private_key(ec.SECP256R1()).public_key()
    provider = FakeCngProvider(_cng_ecc_blob(public))

    spec = KeyAnchorSpec("platform-tpm", AnchorKind.WINDOWS_TPM, "camserv-platform-key")
    anchor = KeyAnchorResolver(cng_provider=provider).resolve_one(spec)

    assert anchor.hardware_backed is True
    assert anchor.kind is AnchorKind.WINDOWS_TPM
    assert anchor.algorithm == "ECDSA-secp256r1"
    assert anchor.source == "cng:camserv-platform-key"
    assert anchor.fingerprint == fingerprint_spki(_spki_der(public))
    assert provider.opened == ["camserv-platform-key"]
    assert provider.freed == [0x5A5A]


def test_windows_tpm_anchor_satisfies_require_hardware() -> None:
    public = ec.generate_private_key(ec.SECP384R1()).public_key()
    spec = KeyAnchorSpec(
        "platform-tpm",
        AnchorKind.WINDOWS_TPM,
        "camserv-platform-key",
        require_hardware=True,
    )
    anchor = KeyAnchorResolver(
        cng_provider=FakeCngProvider(_cng_ecc_blob(public))
    ).resolve_one(spec)

    assert anchor.hardware_backed is True
    assert anchor.algorithm == "ECDSA-secp384r1"


def test_windows_tpm_unavailable_fails_closed() -> None:
    spec = KeyAnchorSpec("platform-tpm", AnchorKind.WINDOWS_TPM, "camserv-platform-key")
    resolver = KeyAnchorResolver(cng_provider=FakeCngProvider(b"", available=False))
    with pytest.raises(KeyAnchorError, match="is unavailable"):
        resolver.resolve_one(spec)


def test_windows_tpm_key_open_failure_fails_closed() -> None:
    class _MissingKeyProvider(FakeCngProvider):
        def open_key(self, key_name: str, *, machine: bool = True) -> int:
            raise KeyAnchorError(
                f"NCryptOpenKey('{key_name}') failed with CNG status 0x80090016."
            )

    spec = KeyAnchorSpec("platform-tpm", AnchorKind.WINDOWS_TPM, "absent-key")
    with pytest.raises(KeyAnchorError, match="NCryptOpenKey"):
        KeyAnchorResolver(cng_provider=_MissingKeyProvider(b"")).resolve_one(spec)


# ---------------------------------------------------------------------------
# PKCS#11 HSM anchoring (fake module — no HSM required)
# ---------------------------------------------------------------------------

def test_pkcs11_uri_parsing() -> None:
    attrs = parse_pkcs11_uri(
        "pkcs11:module=/usr/lib/softhsm/libsofthsm2.so;token=camserv;"
        "object=release-pub;id=0a0b"
    )
    assert attrs["module"] == "/usr/lib/softhsm/libsofthsm2.so"
    assert attrs["token"] == "camserv"
    assert attrs["object"] == "release-pub"
    assert attrs["id"] == "0a0b"


@pytest.mark.parametrize(
    ("uri", "message"),
    [
        ("/usr/lib/libpkcs11.so", "must be a 'pkcs11:' URI"),
        ("pkcs11:token=camserv;object=release-pub", "must include 'module="),
        ("pkcs11:module=/x;id=zz", "not hex"),
        ("pkcs11:module=/x;object=", "Malformed PKCS#11 URI attribute"),
    ],
)
def test_pkcs11_uri_validation(uri: str, message: str) -> None:
    with pytest.raises(KeyAnchorError, match=message):
        parse_pkcs11_uri(uri)


def test_pkcs11_missing_binding_fails_closed() -> None:
    with pytest.raises(KeyAnchorError) as excinfo:
        load_pkcs11_public_key("pkcs11:module=/nonexistent/libpkcs11.so;object=release-pub")
    assert "pkcs11" in str(excinfo.value).lower()


def test_pkcs11_ed25519_hsm_anchor() -> None:
    public = ed25519.Ed25519PrivateKey.generate().public_key()
    raw = public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    token = _FakeToken(
        _FakeHsmKey({"KEY_TYPE": "EC_EDWARDS", "EC_POINT": _der_octet_string(raw)})
    )
    module = FakePkcs11Module(token)
    uri = "pkcs11:module=/opt/hsm/libpkcs11.so;token=camserv;object=release-pub"

    anchor = KeyAnchorResolver(pkcs11_loader=lambda: module).resolve_one(
        KeyAnchorSpec("model-authority", AnchorKind.PKCS11_HSM, uri)
    )

    assert anchor.hardware_backed is True
    assert anchor.algorithm == "Ed25519"
    assert anchor.public_key_hex() == raw.hex()
    assert anchor.source == uri
    assert token.calls == [{"id": None, "label": "release-pub"}]


def test_pkcs11_ecdsa_hsm_anchor() -> None:
    public = ec.generate_private_key(ec.SECP256R1()).public_key()
    numbers = public.public_numbers()
    point = b"\x04" + numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big")
    key = _FakeHsmKey(
        {"KEY_TYPE": "EC", "EC_PARAMS": _P256_OID, "EC_POINT": _der_octet_string(point)}
    )
    module = FakePkcs11Module(_FakeToken(key))

    anchor = KeyAnchorResolver(pkcs11_loader=lambda: module).resolve_one(
        KeyAnchorSpec("ota-authority", AnchorKind.PKCS11_HSM, "pkcs11:module=/hsm.so;object=ota")
    )

    assert anchor.algorithm == "ECDSA-secp256r1"
    assert _spki_der(anchor.public_key()) == _spki_der(public)


def test_pkcs11_unsupported_key_type_rejected() -> None:
    module = FakePkcs11Module(_FakeToken(_FakeHsmKey({"KEY_TYPE": "DSA"})))
    with pytest.raises(KeyAnchorError, match="Unsupported PKCS#11 key type"):
        KeyAnchorResolver(pkcs11_loader=lambda: module).resolve_one(
            KeyAnchorSpec("x", AnchorKind.PKCS11_HSM, "pkcs11:module=/hsm.so;object=x")
        )


def test_pkcs11_token_not_found_fails_closed() -> None:
    module = FakePkcs11Module(_FakeToken(_FakeHsmKey({"KEY_TYPE": "EC_EDWARDS"})))
    uri = "pkcs11:module=/hsm.so;token=absent;object=x"
    with pytest.raises(KeyAnchorError, match="No PKCS#11 token matched"):
        KeyAnchorResolver(pkcs11_loader=lambda: module).resolve_one(
            KeyAnchorSpec("x", AnchorKind.PKCS11_HSM, uri)
        )


def test_der_octet_string_value_rejects_wrong_tag() -> None:
    with pytest.raises(KeyAnchorError, match="Expected a DER OCTET STRING"):
        der_octet_string_value(b"\x06\x01\x00")


# ---------------------------------------------------------------------------
# Integration: installer, updater and settings
# ---------------------------------------------------------------------------

def test_trust_anchor_feeds_model_installer(tmp_path: Path) -> None:
    private = ed25519.Ed25519PrivateKey.generate()
    pem = _write_public_pem(tmp_path / "release.pem", private.public_key())
    anchor = KeyAnchorResolver().resolve_one(
        KeyAnchorSpec("model-authority", AnchorKind.SOFTWARE_FILE, str(pem))
    )

    installer = SignedModelInstaller.from_trust_anchors([anchor])
    assert installer.trusted_model_keys == [anchor.public_key_hex()]

    manifest = ModelManifest(bundle_id="camserv-models", models_version="1.0.0")
    manifest.sign(private)
    assert manifest.verify(installer.trusted_model_keys[0]) is True


def test_model_installer_rejects_non_ed25519_anchor() -> None:
    public = ec.generate_private_key(ec.SECP256R1()).public_key()
    anchor = TrustAnchor(
        purpose="ota",
        kind=AnchorKind.SOFTWARE_FILE,
        algorithm="ECDSA-secp256r1",
        fingerprint=fingerprint_spki(_spki_der(public)),
        spki_der=_spki_der(public),
        hardware_backed=False,
        source="unit-test",
    )

    with pytest.raises(ModelSignatureError, match="require Ed25519"):
        SignedModelInstaller.from_trust_anchors([anchor])
    with pytest.raises(ModelSignatureError, match="TrustAnchor instances"):
        SignedModelInstaller.from_trust_anchors(["not-an-anchor"])


def test_trust_anchor_feeds_update_manager(tmp_path: Path) -> None:
    pem = _write_public_pem(
        tmp_path / "release.pem", ed25519.Ed25519PrivateKey.generate().public_key()
    )
    anchor = KeyAnchorResolver().resolve_one(
        KeyAnchorSpec("ota", AnchorKind.SOFTWARE_FILE, str(pem))
    )

    manager = SignedUpdateManager.from_trust_anchors([anchor])
    assert manager.trusted_release_keys == [anchor.public_key_hex()]
    with pytest.raises(UpdateSignatureError, match="TrustAnchor instances"):
        SignedUpdateManager.from_trust_anchors([object()])


def test_specs_from_settings_preserves_policy() -> None:
    settings = SimpleNamespace(
        require_hardware=True,
        tpm_key_name="camserv-platform-key",
        pkcs11_uri="pkcs11:module=/hsm.so;token=camserv;object=release-pub",
        pinned_fingerprints={"platform-tpm": "AB:" * 31 + "CD"},
    )

    specs = specs_from_settings(settings)

    assert [spec.purpose for spec in specs] == ["platform-tpm", "platform-hsm"]
    assert specs[0].kind is AnchorKind.WINDOWS_TPM
    assert specs[0].require_hardware is True
    assert specs[0].expected_fingerprint == "ab" * 31 + "cd"
    assert specs[1].kind is AnchorKind.PKCS11_HSM
    assert specs[1].expected_fingerprint is None


def test_settings_default_key_anchor_policy() -> None:
    security = SecuritySettings(
        jwt=JWTSettings(secret_key="unit-test-secret-key-that-is-at-least-32-chars-long")
    )
    assert security.key_anchors.require_hardware is False
    assert security.key_anchors.tpm_key_name is None
    assert security.key_anchors.pinned_fingerprints == {}


# ---------------------------------------------------------------------------
# CLI: camserv-key-anchor
# ---------------------------------------------------------------------------

def test_cli_fingerprint_and_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    public = ed25519.Ed25519PrivateKey.generate().public_key()
    pem = _write_public_pem(tmp_path / "release.pem", public)

    exit_code = main(["fingerprint", "--kind", "software_file", "--location", str(pem)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["fingerprint"] == fingerprint_spki(_spki_der(public))
    assert payload["hardware_backed"] is False

    assert main(["status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert isinstance(status["windows_tpm_available"], bool)
    assert status["platform"] in {"nt", "posix"}


def test_cli_fingerprint_fails_when_hardware_is_required(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pem = _write_public_pem(
        tmp_path / "release.pem", ed25519.Ed25519PrivateKey.generate().public_key()
    )

    exit_code = main(
        [
            "fingerprint",
            "--kind",
            "software_file",
            "--location",
            str(pem),
            "--require-hardware",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err.startswith("error:")
    assert captured.out == ""


def test_cli_verify_enforces_policy_pins(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    public = ed25519.Ed25519PrivateKey.generate().public_key()
    pem = _write_public_pem(tmp_path / "release.pem", public)
    digest = fingerprint_spki(_spki_der(public))

    good = tmp_path / "good.json"
    good.write_text(
        json.dumps(
            {
                "anchors": [
                    {
                        "purpose": "model-authority",
                        "kind": "software_file",
                        "location": str(pem),
                        "expected_fingerprint": digest,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert main(["verify", "--policy", str(good)]) == 0
    assert json.loads(capsys.readouterr().out)["verified"][0]["fingerprint"] == digest

    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            [
                {
                    "purpose": "model-authority",
                    "kind": "software_file",
                    "location": str(pem),
                    "expected_fingerprint": "00" * 32,
                }
            ]
        ),
        encoding="utf-8",
    )
    assert main(["verify", "--policy", str(bad)]) == 1
    assert "fingerprint mismatch" in capsys.readouterr().err

    assert main(["status", "--policy", str(bad)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["anchors"][0]["ok"] is False


def test_load_anchor_policy_rejects_invalid_documents(tmp_path: Path) -> None:
    with pytest.raises(KeyAnchorError, match="Cannot read anchor policy"):
        load_anchor_policy(tmp_path / "absent.json")

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(KeyAnchorError, match="not valid JSON"):
        load_anchor_policy(broken)

    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"anchors": []}), encoding="utf-8")
    with pytest.raises(KeyAnchorError, match="non-empty 'anchors' list"):
        load_anchor_policy(empty)
