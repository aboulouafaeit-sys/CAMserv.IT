"""
tests.test_model_installer
==========================

Unit and adversarial tests for the signed model-weight installer:

* Ed25519 manifest signature verification against pinned trust anchors.
* Per-artifact SHA-256 and byte-size enforcement.
* Path-traversal containment and unmanifested-payload (smuggling) rejection.
* Atomic installation with rollback on mid-flight failure.
* Integration with ``camserv.inference.models.ModelRegistry``.
* Console-script ``generate``/``verify``/``install`` round trip.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from camserv.deploy.model_installer import (
    MANIFEST_FILENAME,
    PAYLOAD_PREFIX,
    ModelArtifact,
    ModelBundleIntegrityError,
    ModelInstallError,
    ModelManifest,
    ModelSignatureError,
    SignedModelInstaller,
    main,
)

CREATED_AT = 1_700_000_000.0


def _write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _keypair() -> tuple[ed25519.Ed25519PrivateKey, str]:
    private_key = ed25519.Ed25519PrivateKey.generate()
    return private_key, private_key.public_key().public_bytes_raw().hex()


def _make_bundle(
    tmp_path: Path,
    files: dict[str, bytes],
    private_key: ed25519.Ed25519PrivateKey,
    metadata: dict[str, dict[str, str]] | None = None,
) -> Path:
    source = {name: _write(tmp_path / "src" / name, data) for name, data in files.items()}
    manifest = ModelManifest(
        bundle_id="test-models",
        models_version="1.2.3",
        created_at=CREATED_AT,
    )
    return SignedModelInstaller.create_bundle(
        source,
        manifest,
        private_key,
        tmp_path / "test.camserv-models",
        metadata=metadata,
    )


def test_signed_bundle_installs_all_artifacts(tmp_path: Path) -> None:
    """A signed bundle installs every declared artifact, including nested paths."""
    private_key, public_hex = _keypair()
    files = {
        "detector.onnx": b"detector-weights" * 64,
        "pose/model.onnx": b"pose-weights" * 32,
    }
    bundle = _make_bundle(tmp_path, files, private_key)

    installer = SignedModelInstaller([public_hex])
    result = installer.install(bundle, tmp_path / "installed")

    assert sorted(result["installed"]) == sorted(files)
    for name, data in files.items():
        assert (tmp_path / "installed" / name).read_bytes() == data
    leftovers = [p.name for p in (tmp_path / "installed").iterdir()]
    assert not any(name.startswith(".camserv-models-stage-") for name in leftovers)


def test_untrusted_signature_rejected(tmp_path: Path) -> None:
    """A bundle signed by an untrusted key is rejected before any files are written."""
    _, trusted_hex = _keypair()
    attacker_key, _ = _keypair()
    bundle = _make_bundle(tmp_path, {"model.onnx": b"weights"}, attacker_key)

    installer = SignedModelInstaller([trusted_hex])
    with pytest.raises(ModelSignatureError, match="CRITICAL SECURITY REJECTION"):
        installer.install(bundle, tmp_path / "installed")
    assert not (tmp_path / "installed").exists()


def test_tampered_artifact_digest_rejected(tmp_path: Path) -> None:
    """Replacing payload bytes while keeping a valid manifest signature is rejected."""
    private_key, public_hex = _keypair()
    bundle = _make_bundle(tmp_path, {"model.onnx": b"aaaabbbb"}, private_key)

    with zipfile.ZipFile(bundle) as zf:
        entries = {name: zf.read(name) for name in zf.namelist()}
    entries[PAYLOAD_PREFIX + "model.onnx"] = b"ccccdddd"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)

    with pytest.raises(ModelBundleIntegrityError, match="SHA-256 mismatch"):
        SignedModelInstaller([public_hex]).install(bundle, tmp_path / "installed")


def test_manifest_path_traversal_rejected(tmp_path: Path) -> None:
    """A signed manifest declaring a traversal path is rejected without escaping."""
    private_key, public_hex = _keypair()
    artifact = ModelArtifact(
        file_name="../escape.onnx",
        sha256=hashlib.sha256(b"x").hexdigest(),
        size=1,
    )
    manifest = ModelManifest(created_at=CREATED_AT, artifacts=[artifact])
    manifest.sign(private_key)

    bundle = tmp_path / "traversal.camserv-models"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(PAYLOAD_PREFIX + "../escape.onnx", b"x")
        zf.writestr(MANIFEST_FILENAME, json.dumps(manifest.to_dict()))

    with pytest.raises(ModelBundleIntegrityError, match="Unsafe artifact path"):
        SignedModelInstaller([public_hex]).verify_bundle(bundle)
    assert not (tmp_path / "escape.onnx").exists()


def test_unmanifested_payload_file_rejected(tmp_path: Path) -> None:
    """Extra payload members not declared in the signed manifest are rejected."""
    private_key, public_hex = _keypair()
    bundle = _make_bundle(tmp_path, {"model.onnx": b"weights"}, private_key)

    with zipfile.ZipFile(bundle, "a") as zf:
        zf.writestr(PAYLOAD_PREFIX + "backdoor.onnx", b"malicious")

    with pytest.raises(ModelBundleIntegrityError, match="unmanifested"):
        SignedModelInstaller([public_hex]).verify_bundle(bundle)

def test_existing_artifact_requires_overwrite(tmp_path: Path) -> None:
    """An existing artifact blocks installation unless overwrite is explicitly requested."""
    private_key, public_hex = _keypair()
    new_payload = b"new-weights" * 8
    bundle = _make_bundle(tmp_path, {"model.onnx": new_payload}, private_key)
    target = tmp_path / "installed"
    _write(target / "model.onnx", b"old-weights")

    installer = SignedModelInstaller([public_hex])
    with pytest.raises(ModelInstallError, match="Refusing to overwrite"):
        installer.install(bundle, target)
    assert (target / "model.onnx").read_bytes() == b"old-weights"

    result = installer.install(bundle, target, overwrite=True)
    assert result["installed"] == ["model.onnx"]
    assert (target / "model.onnx").read_bytes() == new_payload


def test_atomic_rollback_on_layout_conflict(tmp_path: Path) -> None:
    """A mid-flight layout conflict removes already-placed files (no partial install)."""
    private_key, public_hex = _keypair()
    files = {"alpha.onnx": b"A" * 32, "nested/beta.onnx": b"B" * 32}
    bundle = _make_bundle(tmp_path, files, private_key)

    target = tmp_path / "installed"
    target.mkdir()
    conflict = b"i-am-a-file-not-a-directory"
    (target / "nested").write_bytes(conflict)

    installer = SignedModelInstaller([public_hex])
    with pytest.raises(ModelInstallError, match="Atomic model installation failed"):
        installer.install(bundle, target, overwrite=True)

    assert not (target / "alpha.onnx").exists()
    assert (target / "nested").read_bytes() == conflict


def test_missing_trust_anchor_fails_closed() -> None:
    """Constructing the installer without trust anchors is refused (fail-closed)."""
    with pytest.raises(ValueError, match="trusted"):
        SignedModelInstaller([])
    with pytest.raises(ValueError, match="trusted"):
        SignedModelInstaller(["   "])


def test_register_into_model_registry(tmp_path: Path) -> None:
    """Installed, verified artifacts can be registered with the ModelRegistry."""
    private_key, public_hex = _keypair()
    payload = b"D" * 64
    bundle = _make_bundle(
        tmp_path,
        {"detector.onnx": payload},
        private_key,
        metadata={
            "detector.onnx": {
                "name": "detector",
                "version": "2.0.0",
                "task": "object_detection",
                "license": "Apache-2.0",
                "provenance": "unit-test",
            }
        },
    )
    installer = SignedModelInstaller([public_hex])
    result = installer.install(bundle, tmp_path / "models")
    manifest = installer.verify_bundle(bundle)

    from camserv.inference.models import ModelRegistry

    registry = ModelRegistry()
    registered = installer.register_into(registry, manifest, result["target_dir"])

    assert [metadata.name for metadata in registered] == ["detector"]
    assert registry.get_model("detector").sha256_hash == hashlib.sha256(payload).hexdigest()


def test_cli_generate_verify_install_roundtrip(tmp_path: Path) -> None:
    """The console entry point builds, verifies and installs a signed bundle."""
    private_key, public_hex = _keypair()
    payload = b"W" * 128
    _write(tmp_path / "weights" / "detector.onnx", payload)
    bundle = tmp_path / "cli.camserv-models"

    assert (
        main(
            [
                "generate",
                "--source-dir",
                str(tmp_path / "weights"),
                "--output",
                str(bundle),
                "--signing-key-hex",
                private_key.private_bytes_raw().hex(),
                "--models-version",
                "9.9.9",
            ]
        )
        == 0
    )
    assert bundle.is_file()
    assert main(["verify", str(bundle), "--trusted-key", public_hex]) == 0
    assert (
        main(
            [
                "install",
                str(bundle),
                "--target",
                str(tmp_path / "models"),
                "--trusted-key",
                public_hex,
            ]
        )
        == 0
    )
    assert (tmp_path / "models" / "detector.onnx").read_bytes() == payload


def test_cli_rejects_untrusted_key(tmp_path: Path) -> None:
    """CLI verification returns a non-zero status for an untrusted signature."""
    private_key, _ = _keypair()
    _, attacker_hex = _keypair()
    bundle = _make_bundle(tmp_path, {"model.onnx": b"weights"}, private_key)
    assert main(["verify", str(bundle), "--trusted-key", attacker_hex]) == 1