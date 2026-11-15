"""
Unit tests for CAMserv analytics: tripwires, polygon zones, loitering candidate classification,
camera tampering / obstruction detection, crowd density, and hardware AI adapters.
"""

from __future__ import annotations

import time
import numpy as np
import pytest

from camserv.analytics.adapters import get_available_adapters, get_best_available_adapter
from camserv.analytics.adapters.cpu import CPUBackendAdapter
from camserv.analytics.crowd import CrowdDensityEstimator
from camserv.analytics.tampering import CameraTamperingDetector
from camserv.analytics.zones import (
    PolygonZone,
    Tripwire,
    ZoneAnalyticsEngine,
)


@pytest.mark.unit
def test_tripwire_crossing_detection() -> None:
    """Test virtual tripwire line crossing detection with bidirectional and directional rules."""
    engine = ZoneAnalyticsEngine()

    # Vertical tripwire line at x=50, from y=0 to y=100
    tw = Tripwire(
        tripwire_id="tw_gate",
        camera_id="cam_entry",
        name="Main Entrance Gate",
        start_point=(50.0, 0.0),
        end_point=(50.0, 100.0),
        direction="forward",
    )
    engine.add_tripwire(tw)

    # Frame 1: Object at x=30, y=50 (left of tripwire)
    trk_f1 = [{"track_id": 101, "ground_contact": (30.0, 50.0), "confidence": 0.9}]
    events_f1 = engine.evaluate_tracks("cam_entry", trk_f1, timestamp_utc=1000.0)
    assert len(events_f1) == 0

    # Frame 2: Object moves to x=70, y=50 (crosses from left to right)
    trk_f2 = [{"track_id": 101, "ground_contact": (70.0, 50.0), "confidence": 0.9}]
    events_f2 = engine.evaluate_tracks("cam_entry", trk_f2, timestamp_utc=1001.0)
    assert len(events_f2) == 1
    assert events_f2[0].event_type == "tripwire_crossed"
    assert events_f2[0].zone_or_tripwire_id == "tw_gate"
    assert events_f2[0].track_id == 101


@pytest.mark.unit
def test_polygon_zone_entry_exit_and_loitering() -> None:
    """Test polygon zone entry, exit, and loitering candidate classification with dwell timer."""
    engine = ZoneAnalyticsEngine()

    # Square polygon zone [0,0] to [100,100]
    zone = PolygonZone(
        zone_id="zone_restricted",
        camera_id="cam_secure",
        name="Restricted Area",
        vertices=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        loitering_threshold_sec=5.0,
    )
    engine.add_zone(zone)

    # Frame 1 (t=0s): Object enters zone at (50, 50)
    trk1 = [{"track_id": 202, "ground_contact": (50.0, 50.0), "confidence": 0.95}]
    evs1 = engine.evaluate_tracks("cam_secure", trk1, timestamp_utc=1000.0)
    assert len(evs1) == 1
    assert evs1[0].event_type == "zone_entered"

    # Frame 2 (t=3s): Object still inside at (52, 51) -> Under threshold (no loitering yet)
    trk2 = [{"track_id": 202, "ground_contact": (52.0, 51.0), "confidence": 0.95}]
    evs2 = engine.evaluate_tracks("cam_secure", trk2, timestamp_utc=1003.0)
    assert len(evs2) == 0

    # Frame 3 (t=6s): Object still inside (dwell = 6s >= 5s) -> Triggers loitering candidate!
    trk3 = [{"track_id": 202, "ground_contact": (53.0, 52.0), "confidence": 0.95}]
    evs3 = engine.evaluate_tracks("cam_secure", trk3, timestamp_utc=1006.0)
    assert len(evs3) == 1
    assert evs3[0].event_type == "loitering_candidate"
    assert evs3[0].dwell_duration_sec == 6.0
    assert evs3[0].is_prediction is True

    # Frame 4 (t=7s): Object moves out of zone to (150, 50) -> Triggers zone_exited
    trk4 = [{"track_id": 202, "ground_contact": (150.0, 50.0), "confidence": 0.95}]
    evs4 = engine.evaluate_tracks("cam_secure", trk4, timestamp_utc=1007.0)
    assert len(evs4) == 1
    assert evs4[0].event_type == "zone_exited"
    assert evs4[0].dwell_duration_sec == 7.0


@pytest.mark.unit
def test_camera_tampering_lens_obstruction() -> None:
    """Test camera tampering detector flags severe visual occlusion / lens obstruction."""
    detector = CameraTamperingDetector(min_spatial_variance=10.0, warmup_frames=5)
    cam_id = "cam_tamper_test"

    # Normal textured frames for warmup
    rng = np.random.default_rng(42)
    for _ in range(6):
        normal_frame = rng.integers(0, 256, size=(100, 100, 3), dtype=np.uint8)
        alarms = detector.evaluate_frame(cam_id, normal_frame)
        assert len(alarms) == 0

    # Tampered frame: completely black (lens covered by hand or spray paint)
    obstructed_frame = np.zeros((100, 100, 3), dtype=np.uint8)
    alarms = detector.evaluate_frame(cam_id, obstructed_frame)
    assert len(alarms) == 1
    assert alarms[0].alarm_type == "lens_obstruction"
    assert alarms[0].severity == "critical"
    assert alarms[0].confidence > 0.9


@pytest.mark.unit
def test_crowd_density_estimation() -> None:
    """Test crowd density calculation and overcrowding alert."""
    estimator = CrowdDensityEstimator(zone_area_sq_m=10.0, max_capacity=3)

    tracks = [
        {"track_id": 1, "class_name": "person"},
        {"track_id": 2, "class_name": "person"},
        {"track_id": 3, "class_name": "person"},
        {"track_id": 4, "class_name": "person"},  # 4 persons > capacity 3
        {"track_id": 5, "class_name": "car"},
    ]

    report = estimator.estimate_occupancy("cam_hall", tracks)
    assert report.total_persons == 4
    assert report.total_vehicles == 1
    assert report.density_per_sq_m == 0.4  # 4 persons / 10 sq m
    assert report.is_overcrowded is True


@pytest.mark.unit
def test_hardware_ai_adapters() -> None:
    """Test pluggable hardware inference backend adapter discovery and fallback."""
    adapters = get_available_adapters()
    assert len(adapters) == 5
    adapter_names = [a.name for a in adapters]
    assert "onnx_cpu" in adapter_names
    assert "nvidia_cuda" in adapter_names
    assert "intel_openvino" in adapter_names
    assert "coral_edgetpu" in adapter_names
    assert "hailo_npu" in adapter_names

    # Best available must resolve without crashing
    best = get_best_available_adapter()
    assert best is not None
    assert best.is_available() is True
    profile = best.get_profile()
    assert profile.is_available is True
