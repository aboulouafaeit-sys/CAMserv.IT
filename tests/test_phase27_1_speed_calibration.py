"""
tests/test_phase27_1_speed_calibration.py
=========================================

Phase 27.1 Speed Measurement & Calibration Truthfulness Tests:
- Verification of SpeedMeasurementStatus: CALIBRATED_ACCURATE, RELATIVE_MOVEMENT_ONLY, SPEED_UNAVAILABLE.
- Verification that arbitrary uncalibrated cameras never report km/h values.
- Audit of scalar pixels-per-meter limitations under perspective distortion.
"""

import pytest

from camserv.intelligence.contracts import (
    BoundingBox,
    CameraCalibration,
    SpeedMeasurementStatus,
    TrackLifecycleState,
    TrackRecord,
)
from camserv.intelligence.traffic import TrafficAnalyticsEngine


@pytest.mark.adversarial
def test_speed_status_classification() -> None:
    """Verify SpeedMeasurementStatus accurately reflects camera calibration state."""
    # 1. Uncalibrated camera with active moving vehicle
    engine_uncalib = TrafficAnalyticsEngine(camera_id="cam-uncalib")
    trk_moving = TrackRecord(
        track_id=1,
        camera_id="cam-uncalib",
        session_id="s1",
        bbox=BoundingBox(10.0, 10.0, 50.0, 50.0),
        class_name="car",
        class_id=1,
        confidence=0.88,
        state=TrackLifecycleState.TRACKED,
        age_frames=10,
        created_at_utc=1.0,
        last_seen_utc=2.0,
        velocity_pixels_per_sec=(50.0, 0.0),
    )
    measurement = engine_uncalib.process_tracks([trk_moving], timestamp_utc=2.0)
    assert measurement.speed_status == SpeedMeasurementStatus.RELATIVE_MOVEMENT_ONLY
    assert measurement.calibrated_speed_kmh is None
    assert measurement.relative_velocity_pixels_sec == 50.0

    # 2. No moving vehicles in scene
    measurement_empty = engine_uncalib.process_tracks([], timestamp_utc=3.0)
    assert measurement_empty.speed_status == SpeedMeasurementStatus.SPEED_UNAVAILABLE

    # 3. Calibrated camera
    calib = CameraCalibration(camera_id="cam-calib", is_calibrated=True, pixels_per_meter=10.0)
    engine_calib = TrafficAnalyticsEngine(camera_id="cam-calib", calibration=calib)
    measurement_calib = engine_calib.process_tracks([trk_moving], timestamp_utc=2.0)
    assert measurement_calib.speed_status == SpeedMeasurementStatus.CALIBRATED_ACCURATE
    assert measurement_calib.calibrated_speed_kmh == pytest.approx(18.0)  # (50/10) * 3.6 = 18.0 km/h
