"""Inference & detection tests for CAMserv.

Verifies:
- Predictions are NEVER labeled as facts (is_prediction=True always)
- Detections enforce strict confidence bounds [0.0, 1.0]
- NMS algorithm suppresses overlapping bounding boxes
- DetectorFactory selects correct backends
- GPU fallback to CPU when CUDA is unavailable
- Privacy filter blurs designated static zones
- Privacy filter polygon masking excludes sensitive detections
- SceneAnalyzer crowd density calculation and uncertainty
- SceneAnalyzer multi-frame observation confirmation
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from camserv.inference.detector import (
    BaseDetector,
    Detection,
    DetectorBackend,
    DetectorFactory,
    ONNXDetector,
    nms,
)
from camserv.inference.privacy import (
    BlurMethod,
    PrivacyConfig,
    PrivacyFilter,
    PrivacyZone,
)
from camserv.inference.scene import (
    HazardType,
    ObservationStatus,
    SceneAnalyzer,
    Zone,
)


@pytest.mark.unit
def test_detection_has_confidence_and_prediction_flag() -> None:
    """Verify Detection instances always carry confidence and explicitly set is_prediction=True."""
    det = Detection(
        bbox=(10.0, 20.0, 100.0, 150.0),
        class_id=0,
        class_name="person",
        confidence=0.88,
        is_prediction=True,
    )

    assert det.is_prediction is True
    assert det.confidence == 0.88
    assert det.class_name == "person"


@pytest.mark.unit
def test_detection_confidence_range_0_to_1() -> None:
    """Verify that confidence outside [0.0, 1.0] raises a ValueError."""
    # Valid bounds
    d_zero = Detection(bbox=(0, 0, 10, 10), class_id=0, class_name="person", confidence=0.0)
    d_one = Detection(bbox=(0, 0, 10, 10), class_id=0, class_name="person", confidence=1.0)
    assert d_zero.confidence == 0.0
    assert d_one.confidence == 1.0

    # Negative confidence
    with pytest.raises(ValueError, match=r"confidence must be in \[0, 1\]"):
        Detection(bbox=(0, 0, 10, 10), class_id=0, class_name="person", confidence=-0.1)

    # Above 1.0 confidence
    with pytest.raises(ValueError, match=r"confidence must be in \[0, 1\]"):
        Detection(bbox=(0, 0, 10, 10), class_id=0, class_name="person", confidence=1.05)


@pytest.mark.unit
def test_nms_removes_overlapping_boxes() -> None:
    """Verify non-maximum suppression retains the highest-confidence box and removes high-IoU duplicates."""
    det1 = Detection(bbox=(10.0, 10.0, 100.0, 100.0), class_id=0, class_name="person", confidence=0.95)
    # Heavily overlapping box with lower confidence
    det2 = Detection(bbox=(12.0, 12.0, 102.0, 102.0), class_id=0, class_name="person", confidence=0.70)
    # Distinct non-overlapping box
    det3 = Detection(bbox=(300.0, 300.0, 400.0, 400.0), class_id=0, class_name="person", confidence=0.85)

    filtered = nms([det1, det2, det3], iou_threshold=0.45)

    assert len(filtered) == 2
    assert det1 in filtered
    assert det3 in filtered
    assert det2 not in filtered


@pytest.mark.unit
def test_detector_factory_creates_correct_backend() -> None:
    """Verify DetectorFactory constructs the requested detector backend."""
    mock_ort = MagicMock()
    def fake_init(self, *args, **kwargs):
        self._using_gpu = False
    with patch.dict("sys.modules", {"onnxruntime": mock_ort}):
        with patch.object(ONNXDetector, "warm_up"):
            with patch.object(ONNXDetector, "__init__", fake_init):
                detector = DetectorFactory.create(
                    backend=DetectorBackend.ONNX_CPU,
                    model_path="dummy.onnx",
                    auto_fallback=False,
                )
                assert detector.backend_name == "onnx_cpu"
                assert isinstance(detector, BaseDetector)


@pytest.mark.unit
def test_gpu_fallback_to_cpu() -> None:
    """Verify that when GPU initialization fails, DetectorFactory gracefully falls back to CPU."""
    with patch.object(DetectorFactory, "_build") as mock_build:
        cpu_detector = MagicMock(spec=ONNXDetector)
        cpu_detector.backend_name = "onnx_cpu"
        cpu_detector.warm_up = MagicMock()

        # First call (GPU) raises exception, second call (CPU) succeeds
        mock_build.side_effect = [
            RuntimeError("CUDA execution provider initialization failed: no GPU device found"),
            cpu_detector,
        ]

        detector = DetectorFactory.create(
            backend=DetectorBackend.ONNX_GPU,
            model_path="dummy.onnx",
            auto_fallback=True,
        )

        assert detector.backend_name == "onnx_cpu"
        assert mock_build.call_count == 2


@pytest.mark.unit
def test_privacy_filter_blurs_zones() -> None:
    """Verify that static privacy zones are blurred on the output image."""
    zone = PrivacyZone(
        name="atm_keypad",
        polygon=[(10, 10), (100, 10), (100, 100), (10, 100)],
        blur_output=True,
        blur_method=BlurMethod.SOLID,
    )
    config = PrivacyConfig(zones=[zone], solid_color=(0, 0, 0))
    filter_obj = PrivacyFilter(config=config)

    # Create solid white frame (200x200x3)
    frame = np.full((200, 200, 3), 255, dtype=np.uint8)
    masked = filter_obj.apply_mask(frame)

    # Frame inside zone (e.g. at 50, 50) should be modified/black
    assert np.all(masked[50, 50] == [0, 0, 0])
    # Outside zone (e.g. at 150, 150) should remain unchanged (white)
    assert np.all(masked[150, 150] == [255, 255, 255])
    # Original frame must NOT be mutated
    assert np.all(frame[50, 50] == [255, 255, 255])


@pytest.mark.unit
def test_privacy_filter_polygon_masking() -> None:
    """Verify detections located inside privacy exclusion zones are filtered out."""
    zone = PrivacyZone(
        name="private_residence",
        polygon=[(100, 100), (300, 100), (300, 300), (100, 300)],
        exclude_from_inference=True,
    )
    filter_obj = PrivacyFilter(config=PrivacyConfig(zones=[zone]))

    det_inside = Detection(
        bbox=(120.0, 120.0, 180.0, 200.0),  # centre (150, 160) inside zone
        class_id=0,
        class_name="person",
        confidence=0.9,
    )
    det_outside = Detection(
        bbox=(400.0, 400.0, 480.0, 500.0),  # centre (440, 450) outside zone
        class_id=0,
        class_name="person",
        confidence=0.9,
    )

    filtered = filter_obj.filter_detections([det_inside, det_outside])

    assert len(filtered) == 1
    assert det_outside in filtered
    assert det_inside not in filtered


@pytest.mark.unit
def test_scene_analyzer_crowd_density() -> None:
    """Verify SceneAnalyzer calculates crowd density and uncertainty metrics per zone."""
    zone = Zone(name="lobby", x1=0.0, y1=0.0, x2=200.0, y2=200.0)
    analyzer = SceneAnalyzer(zones=[zone])

    detections = [
        Detection(bbox=(20.0, 30.0, 50.0, 90.0), class_id=0, class_name="person", confidence=0.9),
        Detection(bbox=(80.0, 80.0, 110.0, 140.0), class_id=0, class_name="person", confidence=0.85),
        Detection(bbox=(120.0, 130.0, 150.0, 190.0), class_id=0, class_name="person", confidence=0.88),
    ]

    results = analyzer.estimate_crowd_density(detections, frame_shape=(480, 640, 3))

    assert len(results) == 1
    res = results[0]
    assert res.zone_name == "lobby"
    assert res.count == 3
    assert res.density > 0.0
    assert res.uncertainty_lower <= res.count <= res.uncertainty_upper
    assert res.status == ObservationStatus.VERIFIED


@pytest.mark.unit
def test_scene_analyzer_multi_frame_confirmation() -> None:
    """Verify hazards require multiple consecutive frames before status transitions from UNCERTAIN to VERIFIED."""
    analyzer = SceneAnalyzer(hazard_confirm_frames=3)

    hazard_detection = [
        Detection(bbox=(50.0, 50.0, 150.0, 150.0), class_id=8, class_name="fire", confidence=0.91)
    ]

    # Frame 1: Single frame -> UNCERTAIN
    res1 = analyzer.detect_hazards(hazard_detection, camera_id="cam-01")
    assert len(res1) == 1
    assert res1[0].status == ObservationStatus.UNCERTAIN
    assert res1[0].requires_verification is True

    # Frame 2: Streak 2 -> UNCERTAIN
    res2 = analyzer.detect_hazards(hazard_detection, camera_id="cam-01")
    assert res2[0].status == ObservationStatus.UNCERTAIN

    # Frame 3: Streak 3 -> VERIFIED
    res3 = analyzer.detect_hazards(hazard_detection, camera_id="cam-01")
    assert res3[0].status == ObservationStatus.VERIFIED
    assert res3[0].requires_verification is False


@pytest.mark.unit
def test_detections_never_labeled_as_facts() -> None:
    """Verify that all Detection outputs are strictly tagged as predictions, never as ground-truth facts."""
    det = Detection(
        bbox=(0.0, 0.0, 100.0, 100.0),
        class_id=0,
        class_name="person",
        confidence=0.99,
    )
    # The default must always be is_prediction=True
    assert det.is_prediction is True
    # Setting is_prediction to False should not be the platform behavior
    assert hasattr(det, "is_prediction")
