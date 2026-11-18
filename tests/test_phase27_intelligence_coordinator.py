"""
tests/test_phase27_intelligence_coordinator.py
==============================================

End-to-end integration tests for CAMservIntelligenceEngine:
Orchestration of detection, classification, tracking, traffic analytics,
scene understanding, rules evaluation, event publishing, and health monitoring.
"""

import numpy as np
import pytest

from camserv.intelligence.contracts import (
    BoundingBox,
    CameraProfilePreset,
    HardwareOperatingTier,
)
from camserv.intelligence.coordinator import CAMservIntelligenceEngine


@pytest.mark.integration
def test_coordinator_end_to_end_frame_analysis() -> None:
    """Verify end-to-end multi-engine analysis on a synthetic video stream."""
    engine = CAMservIntelligenceEngine(tier=HardwareOperatingTier.TIER_A_CPU_LOW)
    engine.configure_camera("cam-highway", CameraProfilePreset.ROAD_TRAFFIC)

    synthetic_frame = np.full((480, 640, 3), 120, dtype=np.uint8)

    # Process sequential frames to simulate moving vehicle
    results = []
    for f_id in range(1, 6):
        res = engine.analyze_frame(
            camera_id="cam-highway",
            frame=synthetic_frame,
            frame_id=f_id,
            source_segment_id="seg_test_01",
            timestamp_utc=100.0 + f_id * 0.1,
        )
        results.append(res)

    last_res = results[-1]
    assert last_res["status"] == "SUCCESS"
    assert last_res["camera_id"] == "cam-highway"
    assert len(last_res["detections"]) >= 1
    assert len(last_res["tracks"]) >= 1
    assert last_res["traffic"] is not None
    assert last_res["scene"] is not None

    # Check health summary
    summary = engine.get_health_summary()
    assert summary["overall_status"] in ("active", "available")
    assert summary["total_inferences"] >= 5
    assert summary["current_tier"] == HardwareOperatingTier.TIER_A_CPU_LOW.value

    engine.shutdown()


@pytest.mark.integration
def test_coordinator_anpr_workflow() -> None:
    """Verify coordinator handles ANPR analysis on detected vehicle crops."""
    # Initialize with authorization enabled
    engine = CAMservIntelligenceEngine(
        tier=HardwareOperatingTier.TIER_C_MODERATE_DGPU,
        anpr_authorized=True,
        anpr_justification="Authorized Test Gate #1",
    )

    frame = np.random.randint(60, 200, (480, 640, 3), dtype=np.uint8)
    v_bbox = BoundingBox(150.0, 100.0, 450.0, 380.0)

    plate_res = engine.analyze_plate(
        camera_id="cam-gate",
        frame=frame,
        vehicle_bbox=v_bbox,
        frame_id=1,
        source_segment_id="seg_gate_01",
    )

    assert plate_res.is_prediction is True
    assert plate_res.camera_id == "cam-gate"
    assert plate_res.status.value in ("success", "low_confidence", "unreadable", "review_required")

    engine.shutdown()
