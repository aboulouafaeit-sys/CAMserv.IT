"""
tests/test_phase27_detection_classification.py
=============================================

Verification of ObjectDetectionEngine, NMS, class taxonomy, and
ObjectClassificationEngine uncertainty handling.
"""

import numpy as np
import pytest

from camserv.intelligence.classification import ObjectClassificationEngine
from camserv.intelligence.contracts import (
    BoundingBox,
    DetectionPrediction,
    EngineHealthStatus,
)
from camserv.intelligence.detection import (
    CANONICAL_CLASSES,
    ObjectDetectionEngine,
    apply_nms,
)


@pytest.mark.unit
def test_canonical_classes_taxonomy() -> None:
    """Verify supported class categories include human, vehicle, and hazard classes."""
    for expected in ["person", "pedestrian", "car", "truck", "motorcycle", "smoke", "fire", "road_obstruction"]:
        assert expected in CANONICAL_CLASSES


@pytest.mark.unit
def test_nms_suppression() -> None:
    """Verify greedy NMS suppresses overlapping boxes of the same class."""
    det1 = DetectionPrediction(
        bbox=BoundingBox(10.0, 10.0, 100.0, 100.0),
        class_id=0,
        class_name="person",
        confidence=0.90,
        camera_id="cam-01",
        frame_id=1,
    )
    det2 = DetectionPrediction(
        bbox=BoundingBox(12.0, 12.0, 102.0, 102.0),
        class_id=0,
        class_name="person",
        confidence=0.85,
        camera_id="cam-01",
        frame_id=1,
    )
    det3 = DetectionPrediction(
        bbox=BoundingBox(200.0, 200.0, 280.0, 280.0),
        class_id=0,
        class_name="person",
        confidence=0.88,
        camera_id="cam-01",
        frame_id=1,
    )

    filtered = apply_nms([det1, det2, det3], iou_threshold=0.50)
    assert len(filtered) == 2
    assert filtered[0].confidence == 0.90
    assert filtered[1].confidence == 0.88


@pytest.mark.unit
def test_detection_engine_input_validation() -> None:
    """Verify ObjectDetectionEngine gracefully handles empty, invalid, or tiny images."""
    engine = ObjectDetectionEngine()
    assert engine.health_status in (EngineHealthStatus.AVAILABLE, EngineHealthStatus.ACTIVE)

    # Empty array
    assert engine.detect(np.array([])) == []
    # 1D array
    assert engine.detect(np.zeros((5,), dtype=np.uint8)) == []
    # Tiny 2x2 image
    assert engine.detect(np.zeros((2, 2, 3), dtype=np.uint8)) == []


@pytest.mark.unit
def test_detection_engine_inference_on_synthetic_frame() -> None:
    """Verify deterministic inference generates valid predictions on standard test frames."""
    engine = ObjectDetectionEngine(confidence_threshold=0.30)
    synthetic_frame = np.full((480, 640, 3), 128, dtype=np.uint8)

    dets = engine.detect(synthetic_frame, camera_id="cam-01", frame_id=1)
    assert len(dets) >= 1
    det = dets[0]
    assert det.is_prediction is True
    assert 0.0 <= det.confidence <= 1.0
    assert det.class_name in CANONICAL_CLASSES
    assert det.bbox.width > 0
    assert det.bbox.height > 0


@pytest.mark.unit
def test_classification_engine_aspect_ratio_and_uncertainty() -> None:
    """Verify ObjectClassificationEngine classifies subcategories and flags uncertainty."""
    classifier = ObjectClassificationEngine(uncertainty_threshold=0.70)

    # Bus-like aspect ratio (wide crop: 300x100)
    bus_crop = np.full((100, 300, 3), 150, dtype=np.uint8)
    res_bus = classifier.classify_crop(bus_crop, base_category="vehicle")
    assert res_bus.class_name == "bus"
    assert res_bus.confidence > 0.70
    assert res_bus.is_uncertain is False

    # Low-resolution ambiguous crop
    tiny_crop = np.full((20, 20, 3), 50, dtype=np.uint8)
    res_tiny = classifier.classify_crop(tiny_crop, base_category="unknown")
    assert res_tiny.is_uncertain is True

    # Empty crop
    empty_res = classifier.classify_crop(np.array([]))
    assert empty_res.class_name == "unclassifiable"
    assert empty_res.confidence == 0.0
