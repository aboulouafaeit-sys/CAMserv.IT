"""
tests/test_phase27_anpr_pipeline.py
===================================

Verification of LicensePlateEngine (ANPR/LPR): 12-stage pipeline, default unauthorized state,
authorization gating, optical quality assessment (Laplacian blur, glare, micro-resolution),
OCR normalization, human review workflow, and access audit logging.
"""

import numpy as np
import pytest

from camserv.intelligence.anpr import (
    LicensePlateEngine,
    assess_plate_quality,
)
from camserv.intelligence.contracts import (
    BoundingBox,
    PlateProcessingStatus,
    PlateQualityGrade,
)


@pytest.mark.unit
def test_anpr_disabled_by_default_and_unauthorized_rejection() -> None:
    """Verify ANPR engine is disabled by default and rejects processing without authorization."""
    engine = LicensePlateEngine()
    assert engine.authorized is False

    frame = np.full((480, 640, 3), 128, dtype=np.uint8)
    v_bbox = BoundingBox(100.0, 100.0, 300.0, 300.0)

    result = engine.process_frame(frame, v_bbox, camera_id="cam-01", frame_id=1)
    assert result.status == PlateProcessingStatus.UNAUTHORIZED
    assert result.review_status == "REJECTED_UNAUTHORIZED"

    # Verify audit log captures the unauthorized attempt
    logs = engine.get_audit_log(operator="SECURITY_AUDITOR")
    assert any(log["action"] == "UNAUTHORIZED_ANPR_ATTEMPT" for log in logs)


@pytest.mark.unit
def test_optical_quality_gating_blur_rejection() -> None:
    """Verify that severely blurred plate crops fail optical gating (UNREADABLE)."""
    # Create smooth blurred image (low Laplacian variance)
    blurred_crop = np.full((50, 150, 3), 128, dtype=np.uint8)
    quality = assess_plate_quality(blurred_crop)

    assert quality.passed_gating is False
    assert quality.overall_grade == PlateQualityGrade.UNREADABLE
    assert quality.rejection_reason == "EXCESSIVE_MOTION_BLUR"


@pytest.mark.unit
def test_optical_quality_gating_glare_rejection() -> None:
    """Verify that optical glare/overexposure fails optical gating (UNREADABLE)."""
    # Create overexposed image (>35% pixels at 255)
    glare_crop = np.random.randint(100, 200, (50, 150, 3), dtype=np.uint8)
    glare_crop[:30, :100] = 255  # Saturated patch
    quality = assess_plate_quality(glare_crop)

    assert quality.passed_gating is False
    assert quality.overall_grade == PlateQualityGrade.UNREADABLE
    assert quality.rejection_reason == "SEVERE_OPTICAL_GLARE"


@pytest.mark.unit
def test_optical_quality_gating_micro_resolution_rejection() -> None:
    """Verify that crops below 16px height are rejected without OCR hallucination."""
    tiny_crop = np.random.randint(50, 200, (12, 40, 3), dtype=np.uint8)
    quality = assess_plate_quality(tiny_crop)

    assert quality.passed_gating is False
    assert quality.overall_grade == PlateQualityGrade.UNREADABLE
    assert quality.rejection_reason == "LOW_RESOLUTION_BELOW_16PX"


@pytest.mark.unit
def test_authorized_anpr_processing_and_character_confidences() -> None:
    """Verify authorized pipeline yields normalized candidate, character-level confidences, and SHA-256 link."""
    engine = LicensePlateEngine(authorized=True, authorization_justification="Parking Access Gate Authorization #104")

    # Generate synthetic vehicle crop with texture
    frame = np.random.randint(80, 180, (480, 640, 3), dtype=np.uint8)
    # Add contrast in plate region
    frame[300:360, 250:400] = np.random.randint(20, 220, (60, 150, 3), dtype=np.uint8)

    v_bbox = BoundingBox(200.0, 150.0, 450.0, 400.0)
    res = engine.process_frame(frame, v_bbox, camera_id="cam-01", frame_id=42, source_segment_id="seg_alpha")

    assert res.is_prediction is True
    assert res.camera_id == "cam-01"
    assert res.source_segment_id == "seg_alpha"
    assert len(res.source_frame_hash) == 64  # SHA-256
    assert res.quality.passed_gating is True
    assert len(res.character_confidences) > 0
    for char, conf in res.character_confidences:
        assert 0.0 <= conf <= 1.0

    # Normalization should contain alphanumeric characters only
    assert res.normalized_candidate.isalnum()
