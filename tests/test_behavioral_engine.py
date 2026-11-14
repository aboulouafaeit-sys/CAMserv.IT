"""
tests/test_behavioral_engine.py
===============================

Unit and scenario tests for Phase 2D:
- Scenario 1: RESTRICTED_AREA_ENTRY (Polygon breach).
- Scenario 2: PERIMETER_LOITERING (Dwell time threshold).
- Scenario 3: ACCESS_POINT_TAMPERING (Camera occlusion).
- Scenario 4: SCHEDULE_ANOMALY (Nighttime activity).
- Scenario 5: RETAIL_INTERACTION (Bypassed checkout flow).
- Human-in-the-Loop (HITL) review workflow state machine.
"""

from __future__ import annotations

from datetime import datetime, timezone
import numpy as np
import pytest

from camserv.events.behavioral_engine import (
    BehaviorScenario,
    BehavioralEngine,
    BehavioralIncident,
    ReviewStatus,
)
from camserv.inference.detector import BoundingBox
from camserv.tracking.coordinator import EnhancedTrack, TrackState


def _make_track(cx: float, cy: float, class_name: str = "person", speed: float = 1.0) -> EnhancedTrack:
    w, h = 40.0, 80.0
    bbox = BoundingBox(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    return EnhancedTrack(
        track_id=101,
        camera_id="cam-01",
        class_name=class_name,
        class_id=0,
        bbox=bbox,
        confidence=0.92,
        state=TrackState.CONFIRMED,
        hits=5,
        age=10,
        lost_frames=0,
        trajectory=[(cx, cy)],
        speed=speed,
    )


def test_scenario_1_restricted_area_entry():
    """Verify incident generation upon polygon geo-fence entry."""
    engine = BehavioralEngine()
    zone_poly = [(100.0, 100.0), (300.0, 100.0), (300.0, 300.0), (100.0, 300.0)]

    # Track outside zone -> No incident
    track_outside = _make_track(50.0, 50.0)
    assert engine.evaluate_restricted_area(track_outside, zone_poly) is None

    # Track inside zone -> Incident generated
    track_inside = _make_track(150.0, 150.0)
    inc = engine.evaluate_restricted_area(track_inside, zone_poly)

    assert inc is not None
    assert inc.scenario == BehaviorScenario.RESTRICTED_AREA_ENTRY
    assert inc.threat_score >= 0.70
    assert inc.requires_human_review is True
    assert inc.review_status == ReviewStatus.DETECTED


def test_scenario_2_perimeter_loitering():
    """Verify loitering detection after exceeding dwell time threshold."""
    engine = BehavioralEngine(dwell_threshold_seconds=10.0)
    zone_poly = [(0.0, 0.0), (200.0, 0.0), (200.0, 200.0), (0.0, 200.0)]
    track = _make_track(100.0, 100.0)

    # Initial frame at t=100s -> Starts dwell timer, no incident yet
    inc_t0 = engine.evaluate_perimeter_loitering(track, zone_poly, current_time=100.0)
    assert inc_t0 is None

    # Frame at t=105s (5s elapsed < 10s) -> No incident yet
    inc_t5 = engine.evaluate_perimeter_loitering(track, zone_poly, current_time=105.0)
    assert inc_t5 is None

    # Frame at t=112s (12s elapsed >= 10s) -> Incident triggered!
    inc_t12 = engine.evaluate_perimeter_loitering(track, zone_poly, current_time=112.0)
    assert inc_t12 is not None
    assert inc_t12.scenario == BehaviorScenario.PERIMETER_LOITERING
    assert inc_t12.metadata["dwell_duration_sec"] == 12.0


def test_scenario_3_camera_tampering():
    """Verify camera tampering detection upon extreme luminance occlusion."""
    engine = BehavioralEngine(tamper_luminance_threshold=0.85)

    # Normal frame (mean ~120)
    normal_frame = np.full((240, 320, 3), 120, dtype=np.uint8)
    assert engine.evaluate_camera_tampering("cam-01", normal_frame, reference_mean_luminance=120.0) is None

    # Occluded / covered lens frame (darkness mean = 2)
    dark_frame = np.full((240, 320, 3), 2, dtype=np.uint8)
    inc = engine.evaluate_camera_tampering("cam-01", dark_frame, reference_mean_luminance=120.0)

    assert inc is not None
    assert inc.scenario == BehaviorScenario.ACCESS_POINT_TAMPERING
    assert inc.threat_score >= 0.90
    assert inc.requires_human_review is True


def test_scenario_4_schedule_anomaly():
    """Verify after-hours movement detection outside authorized daytime schedule."""
    engine = BehavioralEngine(night_start_hour=21, night_end_hour=6)
    track = _make_track(100.0, 100.0)

    # Daytime: 14:00 UTC -> No anomaly
    day_dt = datetime(2026, 11, 14, 14, 0, 0, tzinfo=timezone.utc)
    assert engine.evaluate_schedule_anomaly(track, day_dt) is None

    # Nighttime: 02:30 UTC -> Anomaly triggered!
    night_dt = datetime(2026, 11, 14, 2, 30, 0, tzinfo=timezone.utc)
    inc = engine.evaluate_schedule_anomaly(track, night_dt)

    assert inc is not None
    assert inc.scenario == BehaviorScenario.SCHEDULE_ANOMALY
    assert inc.threat_score >= 0.75


def test_scenario_5_retail_interaction():
    """Verify sequence analysis detecting customer visiting high-value shelf then exiting without checkout."""
    engine = BehavioralEngine()
    track = _make_track(100.0, 100.0)

    # Step 1: Customer enters entry zone
    assert engine.evaluate_retail_sequence(track, "entry") is None
    # Step 2: Customer visits high-value shelf
    assert engine.evaluate_retail_sequence(track, "high_value_shelf") is None
    # Step 3: Customer moves directly to exit without visiting checkout
    inc = engine.evaluate_retail_sequence(track, "exit")

    assert inc is not None
    assert inc.scenario == BehaviorScenario.RETAIL_INTERACTION
    assert inc.threat_score >= 0.70
    assert inc.metadata["zone_sequence"] == ["entry", "high_value_shelf", "exit"]


def test_human_in_the_loop_review_workflow():
    """Verify the formal state machine: DETECTED -> UNDER_REVIEW -> CONFIRMED / DISMISSED."""
    engine = BehavioralEngine()
    zone_poly = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    track = _make_track(50.0, 50.0)

    # 1. Trigger incident
    inc = engine.evaluate_restricted_area(track, zone_poly)
    assert inc is not None
    assert inc.review_status == ReviewStatus.DETECTED
    assert inc.requires_human_review is True

    pending = engine.list_pending_reviews()
    assert len(pending) == 1

    # 2. Assign review to human operator
    inc_under_review = engine.assign_review(inc.incident_id, operator_id="guard-alice")
    assert inc_under_review.review_status == ReviewStatus.UNDER_REVIEW

    # 3. Operator reviews evidence and confirms incident
    confirmed_inc = engine.submit_review_decision(
        incident_id=inc.incident_id,
        operator_id="guard-alice",
        decision=ReviewStatus.CONFIRMED,
        notes="Unauthorized individual breached perimeter fence at north gate.",
    )

    assert confirmed_inc.review_status == ReviewStatus.CONFIRMED
    assert confirmed_inc.review_record is not None
    assert confirmed_inc.review_record.action_authorized is True
    assert confirmed_inc.review_record.operator_id == "guard-alice"

    # Pending queue should now be empty
    assert len(engine.list_pending_reviews()) == 0
