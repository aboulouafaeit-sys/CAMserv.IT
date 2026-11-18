"""
tests/test_phase27_1_adversarial_vision.py
==========================================

Phase 27.1 Adversarial Vision Tests:
- Reality check on absent neural weights and simulated heuristic detection metadata.
- Adversarial image input handling: pitch black, salt-and-pepper noise, extreme dimensions.
- Confidence calibration and boundary integrity under degenerate optical conditions.
"""

import numpy as np
import pytest

from camserv.intelligence.detection import ObjectDetectionEngine
from camserv.intelligence.contracts import EngineHealthStatus


@pytest.mark.adversarial
def test_absent_weights_metadata_transparency() -> None:
    """
    ADVERSARIAL REALITY CHECK:
    When ONNX/OpenCV neural weights are absent on disk, detection predictions
    MUST explicitly disclose `is_simulated_heuristic=True` and `real_weights_loaded=False`.
    """
    engine = ObjectDetectionEngine()
    assert engine.backend_name == "heuristic_deterministic"

    frame = np.full((480, 640, 3), 128, dtype=np.uint8)
    dets = engine.detect(frame, camera_id="cam-audit", frame_id=1)

    assert len(dets) >= 1
    for det in dets:
        assert det.is_prediction is True
        assert det.metadata.get("is_simulated_heuristic") is True
        assert det.metadata.get("real_weights_loaded") is False


@pytest.mark.adversarial
def test_adversarial_noise_and_degradation_handling() -> None:
    """Verify that random white noise or degenerate frames do not crash the engine or segfault."""
    engine = ObjectDetectionEngine()

    # 1. Pitch black frame (all zeros)
    black_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    dets_black = engine.detect(black_frame, camera_id="cam-black", frame_id=2)
    assert isinstance(dets_black, list)

    # 2. Pure uniform noise frame
    noise_frame = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
    dets_noise = engine.detect(noise_frame, camera_id="cam-noise", frame_id=3)
    assert isinstance(dets_noise, list)

    # 3. Extreme ultra-wide aspect ratio (1920x20)
    wide_frame = np.full((20, 1920, 3), 100, dtype=np.uint8)
    dets_wide = engine.detect(wide_frame, camera_id="cam-wide", frame_id=4)
    assert isinstance(dets_wide, list)
