"""
tests/test_privacy_pipeline.py
==============================

Unit and regression tests for Phase 2C:
- Fail-Closed Privacy Pipeline behavior.
- Non-biometric face and plate masking.
- Cryptographic separation of raw evidence and masked derivative.
- PrivacyEvidenceManifest integrity verification and tamper detection.
- Non-mutation guarantee for pristine original evidence.
"""

from __future__ import annotations

import hashlib
import numpy as np
import pytest

from camserv.inference.detector import BoundingBox, Detection
from camserv.inference.privacy import BlurMethod, PrivacyConfig
from camserv.inference.privacy_pipeline import (
    FailClosedPrivacyPipeline,
    PrivacyEvidenceManifest,
    PrivacyState,
)


@pytest.fixture
def test_frame():
    """Generate a deterministic synthetic image with distinct background and content."""
    # 480x640x3 with gradient and textured face/plate zone
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    # Textured region with high-contrast checkerboard/gradient so blur alters pixel values
    pattern = np.indices((100, 100)).sum(axis=0) % 2 * 255
    img[100:200, 150:250, 0] = pattern
    img[100:200, 150:250, 1] = 200
    img[100:200, 150:250, 2] = 150
    img[300:400, 400:500] = (100, 150, 200)
    return img


def test_privacy_pipeline_normal_masking_and_cryptographic_separation(test_frame):
    """Verify that sensitive regions are masked and original evidence remains pristine and cryptographically separated."""
    config = PrivacyConfig(
        blur_faces=True,
        default_blur_method=BlurMethod.GAUSSIAN,
    )
    pipeline = FailClosedPrivacyPipeline(config=config)

    # Detection covering the face region
    det = Detection(
        bbox=BoundingBox(150.0, 100.0, 250.0, 200.0),
        class_id=0,
        class_name="face",
        confidence=0.95,
        camera_id="cam-01",
    )

    masked_img, manifest, pristine_orig = pipeline.process_frame(
        raw_frame=test_frame,
        camera_id="cam-01",
        frame_id=42,
        privacy_detections=[det],
    )

    # 1. State check
    assert pipeline.current_state == PrivacyState.NORMAL
    assert manifest.fail_closed_active is False
    assert manifest.camera_id == "cam-01"
    assert manifest.frame_id == 42

    # 2. Non-destructive guarantee: pristine_orig must match test_frame exactly
    assert np.array_equal(pristine_orig, test_frame)

    # 3. Masked frame must differ from original in the masked region
    assert not np.array_equal(masked_img, test_frame)
    # But outside region should match
    assert np.array_equal(masked_img[0:50, 0:50], test_frame[0:50, 0:50])

    # 4. Cryptographic integrity verification
    assert FailClosedPrivacyPipeline.verify_manifest(manifest, pristine_orig, masked_img) is True


def test_privacy_manifest_tamper_detection(test_frame):
    """Verify that tampering with either the original frame or the derivative invalidates the manifest."""
    pipeline = FailClosedPrivacyPipeline()
    det = Detection(
        bbox=BoundingBox(150.0, 100.0, 250.0, 200.0),
        class_id=0,
        class_name="face",
        confidence=0.95,
    )

    masked_img, manifest, pristine_orig = pipeline.process_frame(
        raw_frame=test_frame,
        camera_id="cam-01",
        frame_id=1,
        privacy_detections=[det],
    )

    # Tamper with original
    tampered_orig = pristine_orig.copy()
    tampered_orig[0, 0] = (255, 255, 255)
    assert FailClosedPrivacyPipeline.verify_manifest(manifest, tampered_orig, masked_img) is False

    # Tamper with derivative
    tampered_deriv = masked_img.copy()
    tampered_deriv[0, 0] = (128, 128, 128)
    assert FailClosedPrivacyPipeline.verify_manifest(manifest, pristine_orig, tampered_deriv) is False


def test_privacy_pipeline_fail_closed_mode(test_frame):
    """Verify that when a failure occurs or fail-closed is triggered, the pipeline enters FAIL_CLOSED state and masks entire frame."""
    pipeline = FailClosedPrivacyPipeline(force_fail_closed_simulation=True)

    masked_img, manifest, pristine_orig = pipeline.process_frame(
        raw_frame=test_frame,
        camera_id="cam-01",
        frame_id=99,
        privacy_detections=[],
    )

    # Pipeline must enter FAIL_CLOSED
    assert pipeline.current_state == PrivacyState.FAIL_CLOSED
    assert pipeline.fail_closed_count == 1
    assert manifest.fail_closed_active is True
    assert manifest.privacy_state == PrivacyState.FAIL_CLOSED

    # Output frame must not leak raw pixels
    assert not np.array_equal(masked_img, test_frame)
    # Manifest verification must still succeed for the fail-closed frame
    assert FailClosedPrivacyPipeline.verify_manifest(manifest, pristine_orig, masked_img) is True
