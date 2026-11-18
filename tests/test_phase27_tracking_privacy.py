"""
tests/test_phase27_tracking_privacy.py
======================================

Verification of ObjectTrackingEngine: anonymous integer tracking, lifecycle state machine,
occlusion handling, fragmentation, frame discontinuity detection, bounded memory, and
strict privacy assertions (zero facial/biometric identification).
"""

import pytest

from camserv.intelligence.contracts import (
    BoundingBox,
    DetectionPrediction,
    EngineHealthStatus,
    TrackLifecycleState,
)
from camserv.intelligence.tracking import ObjectTrackingEngine


@pytest.mark.unit
def test_track_lifecycle_progression() -> None:
    """Verify track state machine transitions: NEW -> TRACKED -> LOST -> REMOVED."""
    tracker = ObjectTrackingEngine(camera_id="cam-01", max_lost_frames=3)

    # Frame 1: Initial detection -> NEW track
    det1 = DetectionPrediction(
        bbox=BoundingBox(100.0, 100.0, 150.0, 200.0),
        class_id=0,
        class_name="person",
        confidence=0.88,
        camera_id="cam-01",
        frame_id=1,
    )
    tracks_f1 = tracker.update([det1], frame_id=1, timestamp_utc=100.0)
    assert len(tracks_f1) == 1
    track_id = tracks_f1[0].track_id
    assert isinstance(track_id, int)
    assert tracks_f1[0].state == TrackLifecycleState.NEW

    # Frame 2: Temporal match -> TRACKED
    det2 = DetectionPrediction(
        bbox=BoundingBox(102.0, 102.0, 152.0, 202.0),
        class_id=0,
        class_name="person",
        confidence=0.91,
        camera_id="cam-01",
        frame_id=2,
    )
    tracks_f2 = tracker.update([det2], frame_id=2, timestamp_utc=100.1)
    assert len(tracks_f2) == 1
    assert tracks_f2[0].track_id == track_id
    assert tracks_f2[0].state == TrackLifecycleState.TRACKED
    assert tracks_f2[0].age_frames == 2

    # Frames 3, 4, 5: Missed detections -> LOST
    tracks_f3 = tracker.update([], frame_id=3, timestamp_utc=100.2)
    assert tracker._tracks[track_id].state == TrackLifecycleState.LOST

    tracker.update([], frame_id=4, timestamp_utc=100.3)
    tracker.update([], frame_id=5, timestamp_utc=100.4)

    # Frame 6: Exceeds max_lost_frames (3) -> Track REMOVED and fragmented
    tracker.update([], frame_id=6, timestamp_utc=100.5)
    assert track_id not in tracker._tracks
    assert tracker.fragmentation_count == 1


@pytest.mark.unit
def test_frame_discontinuity_detection() -> None:
    """Verify tracker detects timestamp gaps or frame skips indicating network/pipeline drops."""
    tracker = ObjectTrackingEngine(camera_id="cam-01", discontinuity_threshold_sec=0.5)

    det = DetectionPrediction(
        bbox=BoundingBox(10.0, 10.0, 50.0, 50.0),
        class_id=1,
        class_name="car",
        confidence=0.80,
        camera_id="cam-01",
        frame_id=1,
    )
    tracker.update([det], frame_id=1, timestamp_utc=10.0)
    assert tracker.discontinuity_events == 0

    # Normal delta: 0.1s -> No discontinuity
    tracker.update([det], frame_id=2, timestamp_utc=10.1)
    assert tracker.discontinuity_events == 0

    # Abnormal timestamp jump: 1.5s (> 0.5s threshold)
    tracker.update([det], frame_id=3, timestamp_utc=11.6)
    assert tracker.discontinuity_events == 1


@pytest.mark.unit
def test_bounded_memory_track_limits() -> None:
    """Verify tracker respects max_active_tracks to prevent memory exhaustion."""
    tracker = ObjectTrackingEngine(camera_id="cam-01", max_active_tracks=5)

    # Submit 10 non-overlapping detections
    dets = [
        DetectionPrediction(
            bbox=BoundingBox(float(i * 50), float(i * 50), float(i * 50 + 30), float(i * 50 + 30)),
            class_id=0,
            class_name="person",
            confidence=0.80,
            camera_id="cam-01",
            frame_id=1,
        )
        for i in range(10)
    ]
    tracker.update(dets, frame_id=1, timestamp_utc=1.0)
    assert len(tracker._tracks) <= 5


@pytest.mark.unit
def test_strict_privacy_assertions() -> None:
    """
    CRITICAL PRIVACY TEST:
    Verify that track records contain ONLY anonymous integer IDs and spatial coordinates.
    Prohibit facial embeddings, biometric tokens, or cross-camera identity correlations.
    """
    tracker = ObjectTrackingEngine(camera_id="cam-privacy-test")
    det = DetectionPrediction(
        bbox=BoundingBox(20.0, 20.0, 80.0, 120.0),
        class_id=0,
        class_name="person",
        confidence=0.92,
        camera_id="cam-privacy-test",
        frame_id=1,
    )
    tracks = tracker.update([det], frame_id=1)
    assert len(tracks) == 1
    trk = tracks[0]

    # Verify ID is an anonymous integer
    assert isinstance(trk.track_id, int)
    assert trk.camera_id == "cam-privacy-test"

    # Verify no biometric or identity keys exist in track metadata
    prohibited_keys = ["face_id", "person_identity", "biometric", "reid_embedding", "ssn", "name"]
    for key in prohibited_keys:
        assert key not in trk.metadata
        assert not hasattr(trk, key)
