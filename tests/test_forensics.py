"""Tests for camserv.storage.forensics."""
from __future__ import annotations

import zipfile
from pathlib import Path
import pytest

from camserv.storage.forensics import (
    EvidencePackager,
    ForensicSigner,
    IndependentVerifier,
    VerificationResult,
)


@pytest.fixture
def signer() -> ForensicSigner:
    """Fixture providing an Ed25519 forensic signer."""
    return ForensicSigner()


@pytest.mark.unit
def test_forensic_signer_key_export(signer: ForensicSigner) -> None:
    """Test Ed25519 public and private PEM export."""
    pub_pem = signer.export_public_key_pem()
    priv_pem = signer.export_private_key_pem()
    assert "BEGIN PUBLIC KEY" in pub_pem
    assert "BEGIN PRIVATE KEY" in priv_pem


@pytest.mark.unit
def test_evidence_package_and_verification_pass(tmp_path: Path, signer: ForensicSigner) -> None:
    """Test creating an evidence package and successfully auditing it."""
    packager = EvidencePackager(signer)
    zip_out = tmp_path / "valid_evidence.zip"

    payloads = {
        "video_chunk_001.mp4": b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41",
        "snapshot_001.jpg": b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01",
        "detections.json": b'{"tracks": [{"id": 101, "class": "person"}]}',
    }

    packager.create_package(
        output_zip=zip_out,
        evidence_id="ev_test_100",
        camera_id="cam-north",
        event_id="evt_test_001",
        file_payloads=payloads,
    )

    assert zip_out.exists()

    # Verify with embedded key
    res = IndependentVerifier.verify_package(zip_out)
    assert res.is_valid is True
    assert res.package_id == "ev_test_100"
    assert res.camera_id == "cam-north"
    assert res.manifest_hash_match is True
    assert res.signature_valid is True
    assert len(res.files_checked) == 3
    assert len(res.tampered_files) == 0

    # Verify with explicit public key PEM
    pub_pem = signer.export_public_key_pem()
    res_explicit = IndependentVerifier.verify_package(zip_out, trusted_public_key_pem=pub_pem)
    assert res_explicit.is_valid is True


@pytest.mark.unit
def test_tampered_payload_detection(tmp_path: Path, signer: ForensicSigner) -> None:
    """Test that modifying a file inside an evidence ZIP trips tamper detection."""
    packager = EvidencePackager(signer)
    zip_out = tmp_path / "tampered_evidence.zip"

    payloads = {
        "evidence_video.mp4": b"ORIGINAL_AUTHENTIC_FOOTAGE_BYTES",
    }

    packager.create_package(
        output_zip=zip_out,
        evidence_id="ev_tamper_001",
        camera_id="cam-south",
        event_id="evt_tamper_001",
        file_payloads=payloads,
    )

    # Tamper with the zip by altering the video bytes
    tampered_zip = tmp_path / "tampered_altered.zip"
    with zipfile.ZipFile(zip_out, "r") as z_in:
        with zipfile.ZipFile(tampered_zip, "w") as z_out:
            for item in z_in.infolist():
                data = z_in.read(item.filename)
                if item.filename == "payload/evidence_video.mp4":
                    data = b"TAMPERED_MODIFIED_MALICIOUS_BYTES"
                z_out.writestr(item, data)

    res = IndependentVerifier.verify_package(tampered_zip)
    assert res.is_valid is False
    assert res.manifest_hash_match is False
    assert len(res.tampered_files) > 0
    assert "evidence_video.mp4" in res.tampered_files[0]


@pytest.mark.unit
def test_forged_signature_detection(tmp_path: Path, signer: ForensicSigner) -> None:
    """Test that a package signed with an untrusted key fails verification against trusted public key."""
    other_signer = ForensicSigner()
    packager = EvidencePackager(other_signer)
    zip_out = tmp_path / "forged_evidence.zip"

    packager.create_package(
        output_zip=zip_out,
        evidence_id="ev_forged_001",
        camera_id="cam-east",
        event_id="evt_forged_001",
        file_payloads={"data.txt": b"some payload"},
    )

    # Verify against original trusted signer key (mismatch!)
    trusted_pem = signer.export_public_key_pem()
    res = IndependentVerifier.verify_package(zip_out, trusted_public_key_pem=trusted_pem)
    assert res.is_valid is False
    assert res.signature_valid is False
