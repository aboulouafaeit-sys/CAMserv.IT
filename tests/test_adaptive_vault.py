"""Tests for Smart Adaptive Retention Vault & Cryptographic Evidence Sealing."""

import tempfile
import time
import numpy as np
import pytest

from camserv.storage.adaptive_vault import (
    AdaptiveRetentionVault,
    ForensicChunkSeal,
    SceneMetadataRecord,
)


@pytest.fixture
def temp_vault() -> AdaptiveRetentionVault:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield AdaptiveRetentionVault(vault_root=tmpdir, pre_roll_seconds=2.0, normal_fps_decimation=4)


def test_tiered_recording_decision(temp_vault: AdaptiveRetentionVault):
    dummy_frame = np.ones((50, 50, 3), dtype=np.uint8)

    # Frame 0: normal condition -> should record (0 % 4 == 0)
    assert temp_vault.push_frame("cam-01", 0, time.time(), dummy_frame, threat_score=10.0) is True
    # Frame 1: normal condition -> decimate (1 % 4 != 0)
    assert temp_vault.push_frame("cam-01", 1, time.time(), dummy_frame, threat_score=10.0) is False
    # Frame 2: elevated threat (>= 50) -> should record regardless of index
    assert temp_vault.push_frame("cam-01", 2, time.time(), dummy_frame, threat_score=65.0) is True


def test_pre_roll_incident_capture(temp_vault: AdaptiveRetentionVault):
    dummy_frame = np.ones((50, 50, 3), dtype=np.uint8)

    # Push 10 pre-roll frames
    t0 = time.time()
    for i in range(10):
        temp_vault.push_frame("cam-01", i, t0 + i * 0.04, dummy_frame)

    active_frames = [(10, t0 + 0.40, dummy_frame), (11, t0 + 0.44, dummy_frame)]
    package_path = temp_vault.trigger_incident_capture("cam-01", "EVT-9901", active_frames)
    assert package_path.exists()
    assert package_path.stat().st_size > 50


def test_metadata_storage_and_query(temp_vault: AdaptiveRetentionVault):
    t0 = time.time()
    r1 = SceneMetadataRecord(
        frame_id=10,
        timestamp_epoch=t0,
        camera_id="cam-01",
        track_id=1,
        class_name="person",
        polygon=[(10.0, 10.0), (20.0, 20.0), (10.0, 20.0)],
        keypoints=[],
        velocity=(0.5, 0.2),
        threat_score=25.0,
        threat_state="normal",
    )
    r2 = SceneMetadataRecord(
        frame_id=20,
        timestamp_epoch=t0 + 5.0,
        camera_id="cam-01",
        track_id=2,
        class_name="person",
        polygon=[(50.0, 50.0), (70.0, 70.0), (50.0, 70.0)],
        keypoints=[],
        velocity=(3.5, 1.2),
        threat_score=85.0,
        threat_state="critical",
    )
    temp_vault.record_metadata(r1)
    temp_vault.record_metadata(r2)

    # Query all
    all_res = temp_vault.query_metadata()
    assert len(all_res) == 2

    # Query high threat
    critical_res = temp_vault.query_metadata(min_threat=80.0)
    assert len(critical_res) == 1
    assert critical_res[0].track_id == 2


def test_cryptographic_chunk_sealing_and_verification(temp_vault: AdaptiveRetentionVault):
    payload = b"Sample forensic video chunk data for incident investigation."
    seal, enc_bytes = temp_vault.seal_forensic_chunk("cam-01", payload)

    assert seal.chunk_id.startswith("CHK-")
    assert seal.sequence_number == 1
    assert len(seal.signature_hex) == 128  # 64 bytes in hex
    assert seal.is_worm_protected is True

    # Valid verification
    is_valid = temp_vault.verify_chunk_seal(seal, enc_bytes)
    assert is_valid is True

    # Tampered data should fail verification
    tampered_bytes = bytearray(enc_bytes)
    tampered_bytes[-1] ^= 0xFF
    assert temp_vault.verify_chunk_seal(seal, bytes(tampered_bytes)) is False
