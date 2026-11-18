"""
tests/test_phase27_intelligence_contracts.py
============================================

Verification of core contracts, dataclasses, enums, bounding box geometry,
and epistemic truthfulness invariants for Phase 27.
"""

import pytest

from camserv.intelligence.contracts import (
    BoundingBox,
    CameraCalibration,
    CameraProfilePreset,
    DetectionPrediction,
    EngineHealthStatus,
    EpistemicLevel,
    EvidenceLink,
    HardwareOperatingTier,
    IntelligenceEvent,
    IntelligenceEventType,
    IntelligencePriority,
    PlateProcessingStatus,
    PlateQualityGrade,
    TrackLifecycleState,
    TrafficCongestionLevel,
)


@pytest.mark.unit
def test_bounding_box_geometry_and_validation() -> None:
    """Verify BoundingBox geometry, IOU, center, and coordinate validation."""
    bbox1 = BoundingBox(x1=10.0, y1=20.0, x2=110.0, y2=120.0)
    assert bbox1.width == 100.0
    assert bbox1.height == 100.0
    assert bbox1.area == 10000.0
    assert bbox1.center == (60.0, 70.0)

    # Inverted coordinates must raise ValueError
    with pytest.raises(ValueError, match="Invalid bounding box coordinates"):
        BoundingBox(x1=100.0, y1=20.0, x2=50.0, y2=120.0)

    with pytest.raises(ValueError, match="Invalid bounding box coordinates"):
        BoundingBox(x1=10.0, y1=200.0, x2=110.0, y2=120.0)

    # Identical box IOU must be 1.0
    bbox2 = BoundingBox(x1=10.0, y1=20.0, x2=110.0, y2=120.0)
    assert bbox1.iou(bbox2) == pytest.approx(1.0)

    # Non-overlapping box IOU must be 0.0
    bbox3 = BoundingBox(x1=200.0, y1=300.0, x2=250.0, y2=350.0)
    assert bbox1.iou(bbox3) == 0.0


@pytest.mark.unit
def test_detection_prediction_epistemic_invariants() -> None:
    """Verify that DetectionPrediction always enforces is_prediction=True and valid confidence."""
    det = DetectionPrediction(
        bbox=BoundingBox(0.0, 0.0, 50.0, 50.0),
        class_id=0,
        class_name="person",
        confidence=0.85,
        camera_id="cam-01",
        frame_id=1,
    )
    assert det.is_prediction is True

    # Attempting to forge is_prediction=False must be reverted or prohibited
    det2 = DetectionPrediction(
        bbox=BoundingBox(0.0, 0.0, 50.0, 50.0),
        class_id=0,
        class_name="person",
        confidence=0.90,
        camera_id="cam-01",
        frame_id=2,
        is_prediction=False,
    )
    assert det2.is_prediction is True

    # Invalid confidence bounds must raise ValueError
    with pytest.raises(ValueError, match=r"Confidence score must be in \[0.0, 1.0\]"):
        DetectionPrediction(
            bbox=BoundingBox(0.0, 0.0, 50.0, 50.0),
            class_id=0,
            class_name="person",
            confidence=-0.1,
            camera_id="cam-01",
            frame_id=3,
        )

    with pytest.raises(ValueError, match=r"Confidence score must be in \[0.0, 1.0\]"):
        DetectionPrediction(
            bbox=BoundingBox(0.0, 0.0, 50.0, 50.0),
            class_id=0,
            class_name="person",
            confidence=1.05,
            camera_id="cam-01",
            frame_id=4,
        )


@pytest.mark.unit
def test_priority_hierarchy_invariants() -> None:
    """Verify non-negotiable priority order: Recording (#1) has strictly higher priority than AI (#6/7)."""
    assert IntelligencePriority.RECORDING_CONTINUITY < IntelligencePriority.VIDEO_INGESTION
    assert IntelligencePriority.VIDEO_INGESTION < IntelligencePriority.STORAGE_EVIDENCE
    assert IntelligencePriority.STORAGE_EVIDENCE < IntelligencePriority.LIVE_VIEWING
    assert IntelligencePriority.LIVE_VIEWING < IntelligencePriority.SYSTEM_MONITORING
    assert IntelligencePriority.SYSTEM_MONITORING < IntelligencePriority.AI_ANALYTICS
    assert IntelligencePriority.AI_ANALYTICS < IntelligencePriority.EXPENSIVE_ANALYSIS


@pytest.mark.unit
def test_camera_calibration_defaults() -> None:
    """Verify uncalibrated camera profile defaults to is_calibrated=False."""
    calib = CameraCalibration(camera_id="cam-test")
    assert calib.is_calibrated is False
    assert calib.reference_distance_meters == 0.0
    assert "Uncalibrated" in calib.notes
