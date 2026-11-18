"""
tests/test_phase27_traffic_analytics.py
=======================================

Verification of TrafficAnalyticsEngine: directional counting lines, density
estimation, congestion levels, wrong-way detection, and calibration-aware
velocity truthfulness.
"""

import pytest

from camserv.intelligence.contracts import (
    BoundingBox,
    CameraCalibration,
    TrackLifecycleState,
    TrackRecord,
    TrafficCongestionLevel,
    TrafficCountingLine,
    TrafficZone,
)
from camserv.intelligence.traffic import TrafficAnalyticsEngine


@pytest.mark.unit
def test_uncalibrated_speed_truthfulness() -> None:
    """
    CRITICAL SPEED TRUTHFULNESS:
    On uncalibrated cameras, calibrated_speed_kmh MUST be None.
    Speed in km/h is NEVER estimated without a validated calibration profile.
    """
    engine = TrafficAnalyticsEngine(camera_id="cam-uncalibrated")
    assert engine.calibration.is_calibrated is False

    trk = TrackRecord(
        track_id=1,
        camera_id="cam-uncalibrated",
        session_id="s1",
        bbox=BoundingBox(10.0, 10.0, 50.0, 50.0),
        class_name="car",
        class_id=1,
        confidence=0.88,
        state=TrackLifecycleState.TRACKED,
        age_frames=10,
        created_at_utc=100.0,
        last_seen_utc=101.0,
        velocity_pixels_per_sec=(60.0, 0.0),  # 60 pixels per second
    )

    measurement = engine.process_tracks([trk], timestamp_utc=101.0)
    assert measurement.is_calibrated is False
    assert measurement.calibrated_speed_kmh is None
    assert measurement.relative_velocity_pixels_sec == 60.0


@pytest.mark.unit
def test_calibrated_speed_calculation() -> None:
    """Verify that when a valid calibration is configured, km/h is correctly computed."""
    # 20 pixels = 1 meter -> 60 px/s = 3 m/s = 10.8 km/h
    calib = CameraCalibration(
        camera_id="cam-calibrated",
        is_calibrated=True,
        pixels_per_meter=20.0,
        reference_distance_meters=15.0,
        error_margin_percent=10.0,
    )
    engine = TrafficAnalyticsEngine(camera_id="cam-calibrated", calibration=calib)

    trk = TrackRecord(
        track_id=1,
        camera_id="cam-calibrated",
        session_id="s1",
        bbox=BoundingBox(10.0, 10.0, 50.0, 50.0),
        class_name="car",
        class_id=1,
        confidence=0.90,
        state=TrackLifecycleState.TRACKED,
        age_frames=10,
        created_at_utc=100.0,
        last_seen_utc=101.0,
        velocity_pixels_per_sec=(60.0, 0.0),
    )

    measurement = engine.process_tracks([trk], timestamp_utc=101.0)
    assert measurement.is_calibrated is True
    assert measurement.calibrated_speed_kmh == pytest.approx(10.8, abs=0.1)


@pytest.mark.unit
def test_directional_counting_lines() -> None:
    """Verify directional counting line increments forward/reverse counts."""
    engine = TrafficAnalyticsEngine(camera_id="cam-01")
    # Vertical line from (200, 0) to (200, 400)
    line = TrafficCountingLine(
        line_id="line_01",
        camera_id="cam-01",
        name="Main Gate Line",
        start_pt=(200.0, 0.0),
        end_pt=(200.0, 400.0),
    )
    engine.add_counting_line(line)

    # Frame 1: Car at x=180 (left of line)
    trk1 = TrackRecord(
        track_id=1,
        camera_id="cam-01",
        session_id="s1",
        bbox=BoundingBox(170.0, 100.0, 190.0, 140.0),
        class_name="car",
        class_id=1,
        confidence=0.88,
        state=TrackLifecycleState.TRACKED,
        age_frames=1,
        created_at_utc=10.0,
        last_seen_utc=10.0,
    )
    engine.process_tracks([trk1], timestamp_utc=10.0)
    assert line.forward_count == 0
    assert line.reverse_count == 0

    # Frame 2: Car moves to x=220 (crosses line forward)
    trk2 = TrackRecord(
        track_id=1,
        camera_id="cam-01",
        session_id="s1",
        bbox=BoundingBox(210.0, 100.0, 230.0, 140.0),
        class_name="car",
        class_id=1,
        confidence=0.88,
        state=TrackLifecycleState.TRACKED,
        age_frames=2,
        created_at_utc=10.0,
        last_seen_utc=10.1,
    )
    engine.process_tracks([trk2], timestamp_utc=10.1)
    assert line.forward_count == 1
    assert line.reverse_count == 0


@pytest.mark.unit
def test_wrong_way_direction_detection() -> None:
    """Verify detection of vehicles traveling opposing configured lane direction."""
    engine = TrafficAnalyticsEngine(camera_id="cam-01")
    # Lane flow is left-to-right: vector (1.0, 0.0)
    engine.set_nominal_flow_direction((1.0, 0.0))

    # Vehicle traveling right-to-left: velocity (-30.0, 0.0)
    trk_wrong = TrackRecord(
        track_id=99,
        camera_id="cam-01",
        session_id="s1",
        bbox=BoundingBox(300.0, 100.0, 350.0, 150.0),
        class_name="car",
        class_id=1,
        confidence=0.85,
        state=TrackLifecycleState.TRACKED,
        age_frames=5,
        created_at_utc=1.0,
        last_seen_utc=1.5,
        velocity_pixels_per_sec=(-30.0, 0.0),
    )

    measurement = engine.process_tracks([trk_wrong], timestamp_utc=1.5)
    assert measurement.wrong_direction_count == 1
    assert engine._wrong_direction_events == 1
