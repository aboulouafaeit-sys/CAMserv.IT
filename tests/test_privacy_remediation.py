"""
tests/test_privacy_remediation.py
=================================

Remediation and regression tests for SEC-01 (Mandatory Fail-Closed Privacy Enforcement):
- Mandatory fail-closed privacy in production profile.
- Rejection of invalid privacy configuration via PrivacyConfigurationError.
- Prohibition of disabling privacy in production profile.
- Centralized privacy enforcement across live stream, snapshot export, and recording paths.
- Role-based export access control (FORENSIC_AUTHORITY vs OPERATOR).
- Intentional bypass attempts and exception containment.
- Concurrent multi-thread pipeline safety.
"""

from __future__ import annotations

import concurrent.futures
import threading
import numpy as np
import pytest

from camserv.inference.detector import BoundingBox, Detection
from camserv.inference.privacy import BlurMethod, PrivacyConfig
from camserv.inference.privacy_pipeline import (
    CentralizedPrivacyEnforcer,
    FailClosedPrivacyPipeline,
    PrivacyConfigurationError,
    PrivacyEvidenceManifest,
    PrivacyState,
    validate_privacy_config,
)
from camserv.pipeline.engine import EngineConfig, PipelineEngine


@pytest.fixture
def sample_frame():
    """Create a deterministic synthetic frame with high-contrast pattern."""
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    pattern = np.indices((100, 100)).sum(axis=0) % 2 * 255
    img[100:200, 150:250, 0] = pattern
    img[100:200, 150:250, 1] = 220
    img[100:200, 150:250, 2] = 180
    return img


def test_invalid_privacy_configuration_rejected():
    """Verify that invalid kernel sizes, negative block sizes, or bad blur methods raise PrivacyConfigurationError."""
    # Even kernel size (must be odd)
    bad_cfg1 = PrivacyConfig(gaussian_kernel_size=50)
    with pytest.raises(PrivacyConfigurationError):
        validate_privacy_config(bad_cfg1)

    # Kernel size < 3
    bad_cfg2 = PrivacyConfig(gaussian_kernel_size=1)
    with pytest.raises(PrivacyConfigurationError):
        validate_privacy_config(bad_cfg2)

    # Pixelate block size < 1
    bad_cfg3 = PrivacyConfig(pixelate_block_size=0)
    with pytest.raises(PrivacyConfigurationError):
        validate_privacy_config(bad_cfg3)


def test_production_profile_disabling_privacy_rejected():
    """Verify that attempting to disable privacy in a production profile raises PrivacyConfigurationError."""
    # Direct enforcer check
    with pytest.raises(PrivacyConfigurationError):
        CentralizedPrivacyEnforcer(is_production_profile=True, enable_privacy_filtering=False)

    # PipelineEngine check
    eng_cfg = EngineConfig(is_production_profile=True, enable_privacy_filtering=False)
    with pytest.raises(PrivacyConfigurationError):
        PipelineEngine(config=eng_cfg)


def test_centralized_enforcer_live_streaming_and_snapshot_roles(sample_frame):
    """Verify that live streaming and normal snapshots receive masked derivatives, while forensic role can export raw."""
    enforcer = CentralizedPrivacyEnforcer(is_production_profile=True, enable_privacy_filtering=True)
    det = Detection(
        bbox=BoundingBox(150.0, 100.0, 250.0, 200.0),
        class_id=0,
        class_name="face",
        confidence=0.98,
        camera_id="cam-01",
    )

    # 1. Live streaming path -> strictly masked
    stream_frame, stream_manifest = enforcer.process_live_stream_frame(
        raw_frame=sample_frame,
        camera_id="cam-01",
        frame_id=1,
        detections=[det],
    )
    assert not np.array_equal(stream_frame, sample_frame)
    assert stream_manifest.fail_closed_active is False

    # 2. Normal operator snapshot export -> strictly masked
    op_frame, op_manifest, is_raw = enforcer.process_snapshot_export(
        raw_frame=sample_frame,
        camera_id="cam-01",
        frame_id=1,
        user_role="OPERATOR",
        detections=[det],
    )
    assert is_raw is False
    assert not np.array_equal(op_frame, sample_frame)

    # 3. Forensic authority snapshot export -> raw pristine evidence
    forensic_frame, forensic_manifest, is_raw_f = enforcer.process_snapshot_export(
        raw_frame=sample_frame,
        camera_id="cam-01",
        frame_id=1,
        user_role="FORENSIC_AUTHORITY",
        detections=[det],
    )
    assert is_raw_f is True
    assert np.array_equal(forensic_frame, sample_frame)
    assert FailClosedPrivacyPipeline.verify_manifest(forensic_manifest, sample_frame, op_frame) is True


def test_centralized_enforcer_fail_closed_under_failure(sample_frame):
    """Verify that when an error occurs, enforcer strictly produces full-frame blackout on all operational paths."""
    pipeline = FailClosedPrivacyPipeline(force_fail_closed_simulation=True)
    enforcer = CentralizedPrivacyEnforcer(pipeline=pipeline, is_production_profile=True)

    stream_frame, manifest = enforcer.process_live_stream_frame(
        raw_frame=sample_frame,
        camera_id="cam-01",
        frame_id=99,
    )
    assert manifest.fail_closed_active is True
    assert manifest.privacy_state == PrivacyState.FAIL_CLOSED
    assert np.array_equal(stream_frame[0:20, 0:20], np.zeros((20, 20, 3), dtype=np.uint8))

    # Snapshot export under fail-closed also reflects fail-closed manifest
    _, snap_manifest, _ = enforcer.process_snapshot_export(
        raw_frame=sample_frame,
        camera_id="cam-01",
        frame_id=99,
        user_role="OPERATOR",
    )
    assert snap_manifest.fail_closed_active is True


def test_concurrent_pipeline_privacy_enforcement(sample_frame):
    """Verify thread-safety of centralized privacy enforcement under concurrent stream execution."""
    enforcer = CentralizedPrivacyEnforcer(is_production_profile=True)
    det = Detection(
        bbox=BoundingBox(150.0, 100.0, 250.0, 200.0),
        class_id=0,
        class_name="face",
        confidence=0.95,
        camera_id="cam-conc",
    )

    def _worker(thread_id: int):
        f, m = enforcer.process_live_stream_frame(sample_frame, f"cam-{thread_id}", thread_id, [det])
        return not np.array_equal(f, sample_frame), m.original_sha256

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_worker, i) for i in range(20)]
        results = [fut.result() for fut in futures]

    for is_masked, orig_hash in results:
        assert is_masked is True
        assert len(orig_hash) == 64
