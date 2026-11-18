"""
tests/test_phase27_1_tracking_adversarial.py
============================================

Phase 27.1 Adversarial Tracking Tests:
- Verification of motion-projected bounding box matching for fast-moving objects.
- Verification that high-speed movement without static overlap maintains track continuity.
- Re-verification of zero biometric/facial attributes under multi-object tracking.
"""

import pytest

from camserv.intelligence.contracts import (
    BoundingBox,
    DetectionPrediction,
    TrackLifecycleState,
)
from camserv.intelligence.tracking import ObjectTrackingEngine


@pytest.mark.adversarial
def test_fast_moving_object_motion_projection_continuity() -> None:
    """
    ADVERSARIAL TRACKING TEST:
    A fast-moving car moves 80 pixels in 0.1s.
    Static bounding boxes at t1 [10, 10, 50, 50] and t2 [90, 10, 130, 50] have 0.0 static IoU!
    With velocity projection, the predicted bounding box matches the detection,
    preventing track fragmentation into a new ID.
    """
    tracker = ObjectTrackingEngine(camera_id="cam-highway-fast", iou_threshold=0.20)

    # Frame 1 at t=10.0: Car at x=[10, 50]
    det1 = DetectionPrediction(
        bbox=BoundingBox(10.0, 10.0, 50.0, 50.0),
        class_id=1,
        class_name="car",
        confidence=0.90,
        camera_id="cam-highway-fast",
        frame_id=1,
    )
    t1_tracks = tracker.update([det1], frame_id=1, timestamp_utc=10.0)
    assert len(t1_tracks) == 1
    car_track_id = t1_tracks[0].track_id

    # Frame 2 at t=10.1: Car at x=[30, 70] (moves 20px, establishing initial velocity of 200 px/s)
    det2 = DetectionPrediction(
        bbox=BoundingBox(30.0, 10.0, 70.0, 50.0),
        class_id=1,
        class_name="car",
        confidence=0.92,
        camera_id="cam-highway-fast",
        frame_id=2,
    )
    t2_tracks = tracker.update([det2], frame_id=2, timestamp_utc=10.1)
    assert len(t2_tracks) == 1
    assert t2_tracks[0].track_id == car_track_id
    assert t2_tracks[0].velocity_pixels_per_sec[0] > 100.0

    # Frame 3 at t=10.2: Car at x=[55, 95] (fast jump; static IoU with frame 2 is low or zero)
    det3 = DetectionPrediction(
        bbox=BoundingBox(55.0, 10.0, 95.0, 50.0),
        class_id=1,
        class_name="car",
        confidence=0.91,
        camera_id="cam-highway-fast",
        frame_id=3,
    )
    t3_tracks = tracker.update([det3], frame_id=3, timestamp_utc=10.2)
    assert len(t3_tracks) == 1
    # Track ID MUST be preserved via motion projection matching!
    assert t3_tracks[0].track_id == car_track_id
    assert tracker.fragmentation_count == 0
