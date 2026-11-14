"""
tests/test_object_tracking_phase2.py
====================================

Unit and validation tests for Phase 2B:
- Track State Machine: TENTATIVE -> CONFIRMED -> OCCLUDED.
- Occlusion Recovery within camera field of view.
- Kinematic Velocity and Speed calculations.
- Strict Camera Isolation and rejection of cross-camera matching.
- Anonymity and non-biometric integer ID validation.
"""

from __future__ import annotations

import time
import numpy as np
import pytest

from camserv.inference.detector import BoundingBox, Detection
from camserv.tracking.coordinator import (
    CameraTracker,
    CrossCameraMatchingForbiddenError,
    EnhancedTrack,
    MultiCameraTrackingCoordinator,
    TrackState,
)


def _make_detection(x1: float, y1: float, x2: float, y2: float, conf: float = 0.9, camera_id: str = "cam-01") -> Detection:
    return Detection(
        bbox=BoundingBox(x1, y1, x2, y2),
        class_id=0,
        class_name="person",
        confidence=conf,
        camera_id=camera_id,
        frame_id=1,
    )


def test_track_state_machine_tentative_to_confirmed():
    """Verify that a newly observed object starts as TENTATIVE and becomes CONFIRMED after min_hits."""
    tracker = CameraTracker(camera_id="cam-01", min_hits=3)

    # Frame 1: Initial detection -> TENTATIVE
    d1 = _make_detection(100, 100, 150, 200)
    tracks_f1 = tracker.update([d1])
    assert len(tracks_f1) == 1
    assert tracks_f1[0].state == TrackState.TENTATIVE
    assert tracks_f1[0].hits == 1

    # Frame 2: Second detection -> Still TENTATIVE (hits=2 < min_hits=3)
    d2 = _make_detection(102, 100, 152, 200)
    tracks_f2 = tracker.update([d2])
    assert len(tracks_f2) == 1
    assert tracks_f2[0].state == TrackState.TENTATIVE
    assert tracks_f2[0].hits == 2

    # Frame 3: Third detection -> Promoted to CONFIRMED
    d3 = _make_detection(104, 100, 154, 200)
    tracks_f3 = tracker.update([d3])
    assert len(tracks_f3) == 1
    assert tracks_f3[0].state == TrackState.CONFIRMED
    assert tracks_f3[0].hits == 3
    assert tracks_f3[0].track_id == tracks_f1[0].track_id


def test_occlusion_recovery_preserves_track_id():
    """Verify that an object occluded for multiple frames transitions to OCCLUDED and retains track_id upon reappearance."""
    tracker = CameraTracker(camera_id="cam-01", min_hits=2, max_age=10)

    # Step 1: Establish confirmed track
    t1 = tracker.update([_make_detection(100, 100, 150, 200)])
    t2 = tracker.update([_make_detection(102, 100, 152, 200)])
    initial_id = t2[0].track_id
    assert t2[0].state == TrackState.CONFIRMED

    # Step 2: Occlusion (3 frames with no detections)
    for _ in range(3):
        tracks_lost = tracker.update([])

    # Verify track entered OCCLUDED state
    occluded = [t for t in tracks_lost if t.track_id == initial_id]
    assert len(occluded) == 1
    assert occluded[0].state == TrackState.OCCLUDED

    # Step 3: Re-emergence at expected position
    tracks_recovered = tracker.update([_make_detection(108, 100, 158, 200)])
    recovered = [t for t in tracks_recovered if t.track_id == initial_id]
    assert len(recovered) == 1
    assert recovered[0].track_id == initial_id
    assert recovered[0].state == TrackState.CONFIRMED


def test_kinematic_velocity_and_speed_calculation():
    """Verify trajectory history and velocity computation over time."""
    tracker = CameraTracker(camera_id="cam-01", min_hits=1)

    t0 = 1000.0
    # Object moves 20 pixels in X over 0.5 seconds (dx=20, dt=0.5s -> 40 px/sec)
    tracker.update([_make_detection(100, 100, 150, 200)], frame_time=t0)
    tracks = tracker.update([_make_detection(120, 100, 170, 200)], frame_time=t0 + 0.5)

    active_tracks = [t for t in tracks if t.state in (TrackState.TENTATIVE, TrackState.CONFIRMED)]
    assert len(active_tracks) == 1
    track = active_tracks[0]
    assert len(track.trajectory) == 2
    # Velocity vx should be ~40 px/sec, vy ~0 px/sec, speed ~40 px/sec
    assert track.velocity[0] == pytest.approx(40.0, rel=0.1)
    assert track.velocity[1] == pytest.approx(0.0, abs=1.0)
    assert track.speed == pytest.approx(40.0, rel=0.1)


def test_multi_camera_isolation_and_cross_camera_prohibition():
    """Verify strict multi-camera isolation and structural prohibition of cross-camera matching."""
    coordinator = MultiCameraTrackingCoordinator()

    # Track on cam-01
    d_cam1 = _make_detection(100, 100, 150, 200, camera_id="cam-01")
    tracks_cam1 = coordinator.update("cam-01", [d_cam1])

    # Track on cam-02
    d_cam2 = _make_detection(100, 100, 150, 200, camera_id="cam-02")
    tracks_cam2 = coordinator.update("cam-02", [d_cam2])

    assert len(tracks_cam1) == 1
    assert len(tracks_cam2) == 1
    assert tracks_cam1[0].camera_id == "cam-01"
    assert tracks_cam2[0].camera_id == "cam-02"
    assert tracks_cam1[0].qualified_id.startswith("cam-01:")
    assert tracks_cam2[0].qualified_id.startswith("cam-02:")

    # Attempting cross-camera correlation MUST raise CrossCameraMatchingForbiddenError
    with pytest.raises(CrossCameraMatchingForbiddenError):
        coordinator.correlate_cross_camera(
            camera_a="cam-01",
            camera_b="cam-02",
            track_a=tracks_cam1[0].track_id,
            track_b=tracks_cam2[0].track_id,
        )
