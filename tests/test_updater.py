"""
tests.test_updater
==================

Unit tests for CAMserv signed OTA software update system:
Ed25519 signature verification, version compatibility, payload integrity checksums,
and atomic rollback upon post-update health check failure.
"""

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from camserv.deploy.updater import (
    DeploymentChannel,
    PackageIntegrityError,
    SignedUpdateManager,
    UpdatePackageManifest,
    UpdateSignatureError,
    VersionIncompatibilityError,
)


def test_create_and_verify_signed_update_package(tmp_path: Path):
    """Verify update creation, cryptographic signing, and staging verification."""
    # Generate release authority keypair
    release_priv = ed25519.Ed25519PrivateKey.generate()
    release_pub_hex = release_priv.public_key().public_bytes_raw().hex()

    pkg_path = tmp_path / "camserv_release_3.1.0.pkg"
    payload = {
        "bin/app.py": b"print('CAMserv 3.1.0')",
        "config/app.yaml": b"version: 3.1.0\nenabled: true",
    }
    manifest = UpdatePackageManifest(
        package_id="upd-2026-310",
        target_version="3.1.0",
        minimum_supported_version="3.0.0",
        channel=DeploymentChannel.STABLE,
        files=[],
    )

    SignedUpdateManager.create_update_package(
        payload_files=payload,
        manifest=manifest,
        signing_key=release_priv,
        output_pkg_path=pkg_path,
    )
    assert pkg_path.exists()

    # Verify and stage with trusted key
    manager = SignedUpdateManager(trusted_release_keys=[release_pub_hex])
    staged_manifest = manager.verify_and_stage_package(
        pkg_path=pkg_path,
        current_version="3.0.0",
        allowed_channel=DeploymentChannel.STABLE,
    )
    assert staged_manifest.package_id == "upd-2026-310"
    assert staged_manifest.target_version == "3.1.0"


def test_untrusted_signature_rejection(tmp_path: Path):
    """Verify that packages not signed by an approved release key are rejected."""
    trusted_priv = ed25519.Ed25519PrivateKey.generate()
    trusted_pub_hex = trusted_priv.public_key().public_bytes_raw().hex()

    # Attacker signs with their own untrusted key
    attacker_priv = ed25519.Ed25519PrivateKey.generate()

    pkg_path = tmp_path / "malicious_update.pkg"
    manifest = UpdatePackageManifest(
        package_id="upd-malicious",
        target_version="3.1.0",
        minimum_supported_version="3.0.0",
        channel=DeploymentChannel.STABLE,
        files=[],
    )

    SignedUpdateManager.create_update_package(
        payload_files={"bin/run.py": b"# backdoor"},
        manifest=manifest,
        signing_key=attacker_priv,
        output_pkg_path=pkg_path,
    )

    manager = SignedUpdateManager(trusted_release_keys=[trusted_pub_hex])
    with pytest.raises(UpdateSignatureError, match="CRITICAL SECURITY REJECTION"):
        manager.verify_and_stage_package(pkg_path, current_version="3.0.0")


def test_version_incompatibility_rejection(tmp_path: Path):
    """Verify that an update requiring a higher baseline version is blocked."""
    release_priv = ed25519.Ed25519PrivateKey.generate()
    release_pub_hex = release_priv.public_key().public_bytes_raw().hex()

    pkg_path = tmp_path / "update_v4.pkg"
    manifest = UpdatePackageManifest(
        package_id="upd-v4",
        target_version="4.0.0",
        minimum_supported_version="3.5.0",  # Requires at least 3.5.0
        channel=DeploymentChannel.STABLE,
        files=[],
    )
    SignedUpdateManager.create_update_package(
        payload_files={"file.txt": b"data"},
        manifest=manifest,
        signing_key=release_priv,
        output_pkg_path=pkg_path,
    )

    manager = SignedUpdateManager(trusted_release_keys=[release_pub_hex])
    with pytest.raises(VersionIncompatibilityError, match="below required minimum"):
        # Host is currently on 3.0.0 (below 3.5.0)
        manager.verify_and_stage_package(pkg_path, current_version="3.0.0")


def test_tampered_payload_integrity_rejection(tmp_path: Path):
    """Verify that modifying a file inside the archive after signing fails integrity checks."""
    import zipfile

    release_priv = ed25519.Ed25519PrivateKey.generate()
    release_pub_hex = release_priv.public_key().public_bytes_raw().hex()

    pkg_path = tmp_path / "valid_pkg.pkg"
    manifest = UpdatePackageManifest(
        package_id="upd-tamper-test",
        target_version="3.1.0",
        minimum_supported_version="3.0.0",
        channel=DeploymentChannel.STABLE,
        files=[],
    )
    SignedUpdateManager.create_update_package(
        payload_files={"code.py": b"original_code()"},
        manifest=manifest,
        signing_key=release_priv,
        output_pkg_path=pkg_path,
    )

    # Tamper with the package by altering code.py inside zip
    tampered_pkg = tmp_path / "tampered.pkg"
    with zipfile.ZipFile(str(pkg_path), "r") as z_in, zipfile.ZipFile(str(tampered_pkg), "w") as z_out:
        for item in z_in.infolist():
            if item.filename == "payload/code.py":
                z_out.writestr(item, b"altered_malicious_code()")
            else:
                z_out.writestr(item, z_in.read(item.filename))

    manager = SignedUpdateManager(trusted_release_keys=[release_pub_hex])
    with pytest.raises(PackageIntegrityError, match="Checksum mismatch"):
        manager.verify_and_stage_package(tampered_pkg, current_version="3.0.0")


def test_atomic_rollback_on_health_failure(tmp_path: Path):
    """Verify that a post-install health failure triggers atomic rollback to pre-update snapshot."""
    release_priv = ed25519.Ed25519PrivateKey.generate()
    pkg_path = tmp_path / "broken_release.pkg"
    manifest = UpdatePackageManifest(
        package_id="upd-broken",
        target_version="3.1.0",
        minimum_supported_version="3.0.0",
        channel=DeploymentChannel.STABLE,
        files=[],
    )
    SignedUpdateManager.create_update_package(
        payload_files={"app.py": b"new_broken_code()"},
        manifest=manifest,
        signing_key=release_priv,
        output_pkg_path=pkg_path,
    )

    install_dir = tmp_path / "installed_app"
    backup_dir = tmp_path / "backup_snaps"
    install_dir.mkdir()
    (install_dir / "app.py").write_bytes(b"original_working_code()")

    manager = SignedUpdateManager(trusted_release_keys=[])

    # Apply with simulated health failure
    success = manager.apply_update_with_atomic_rollback(
        pkg_path=pkg_path,
        target_dir=install_dir,
        backup_dir=backup_dir,
        simulate_post_health_fail=True,
    )
    assert success is False

    # Original working code MUST be restored!
    restored_content = (install_dir / "app.py").read_bytes()
    assert restored_content == b"original_working_code()"
