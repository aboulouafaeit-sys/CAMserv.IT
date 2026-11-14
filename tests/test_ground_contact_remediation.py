"""
tests/test_ground_contact_remediation.py
========================================

Remediation and validation tests for SEC-04 (Ground Contact Position for Restricted-Zone Analysis):
- Elimination of perspective-projection false alarms using FEET_GROUND_CONTACT.
- Verification that upper-body torso visual overlap does NOT trigger when feet are outside.
- Verification that ground boundary penetration correctly triggers.
- Verification of ADAPTIVE anchoring (feet for persons, centroid for vehicles).
- Bounding-box validation and posture metadata diagnostics.
"""

from __future__ import annotations

import pytest

from camserv.events.behavioral_engine import (
    BehaviorScenario,
    BehavioralEngine,
    SpatialAnchorStrategy,
)
from camserv.inference.detector import BoundingBox
from camserv.tracking.coordinator import EnhancedTrack, TrackState


def _create_person_track(x1: float, y1: float, x2: float, y2: float) -> EnhancedTrack:
    """Helper to create an EnhancedTrack for a person with exact bbox coordinates."""
    bbox = BoundingBox(x1, y1, x2, y2)
    cx, cy = bbox.center
    return EnhancedTrack(
        track_id=202,
        camera_id="cam-perimeter",
        class_name="person",
        class_id=0,
        bbox=bbox,
        confidence=0.94,
        state=TrackState.CONFIRMED,
        hits=10,
        age=20,
        lost_frames=0,
        trajectory=[(cx, cy)],
    )


def test_perspective_false_alarm_eliminated_with_ground_contact():
    """Verify that a person whose torso/centroid overlaps a zone from outside is NOT flagged when using ground contact."""
    engine = BehavioralEngine()

    # Restricted zone between Y=100 and Y=200, X=100 and X=300
    zone_poly = [(100.0, 100.0), (300.0, 100.0), (300.0, 200.0), (100.0, 200.0)]

    # Person stands in the foreground:
    # Feet at Y2=220 (OUTSIDE the zone, below Y=200 boundary)
    # Head at Y1=140 (INSIDE the zone bounding box)
    # Centroid: Y = (140 + 220) / 2 = 180 (INSIDE zone between 100 and 200)
    person = _create_person_track(x1=130.0, y1=140.0, x2=170.0, y2=220.0)

    # 1. Under legacy CENTROID strategy:
    # Centroid is (150, 180), which lies INSIDE polygon -> Generates FALSE ALARM!
    inc_centroid = engine.evaluate_restricted_area(
        person, zone_poly, anchor_strategy=SpatialAnchorStrategy.CENTROID
    )
    assert inc_centroid is not None
    assert inc_centroid.scenario == BehaviorScenario.RESTRICTED_AREA_ENTRY

    # 2. Under FEET_GROUND_CONTACT (or ADAPTIVE):
    # Anchor point is feet at (150, 220), which lies OUTSIDE polygon -> NO FALSE ALARM!
    inc_feet = engine.evaluate_restricted_area(
        person, zone_poly, anchor_strategy=SpatialAnchorStrategy.FEET_GROUND_CONTACT
    )
    assert inc_feet is None

    inc_adaptive = engine.evaluate_restricted_area(
        person, zone_poly, anchor_strategy=SpatialAnchorStrategy.ADAPTIVE
    )
    assert inc_adaptive is None


def test_ground_contact_true_intrusion_detected():
    """Verify that when a person actually steps their feet into the zone, an incident is triggered."""
    engine = BehavioralEngine()
    zone_poly = [(100.0, 100.0), (200.0, 100.0), (200.0, 200.0), (100.0, 200.0)]

    # Person's feet are at Y=150 (INSIDE the zone polygon)
    intruder = _create_person_track(x1=130.0, y1=90.0, x2=170.0, y2=150.0)

    inc = engine.evaluate_restricted_area(
        intruder, zone_poly, anchor_strategy=SpatialAnchorStrategy.FEET_GROUND_CONTACT
    )
    assert inc is not None
    assert inc.scenario == BehaviorScenario.RESTRICTED_AREA_ENTRY
    assert inc.metadata["anchor_strategy"] == "FEET_GROUND_CONTACT"
    assert inc.metadata["anchor_point"] == (150.0, 150.0)


def test_adaptive_strategy_for_vehicles():
    """Verify that vehicles use centroid under ADAPTIVE strategy while persons use ground contact."""
    engine = BehavioralEngine()

    # Person track
    person = _create_person_track(x1=100.0, y1=50.0, x2=140.0, y2=150.0)
    px_p, py_p, meta_p = engine.get_spatial_anchor_point(person, SpatialAnchorStrategy.ADAPTIVE)
    # Person anchor must be feet (Y2 = 150.0)
    assert (px_p, py_p) == (120.0, 150.0)

    # Vehicle track
    vehicle_bbox = BoundingBox(100.0, 50.0, 200.0, 150.0)
    vehicle = EnhancedTrack(
        track_id=303,
        camera_id="cam-road",
        class_name="vehicle",
        class_id=1,
        bbox=vehicle_bbox,
        confidence=0.91,
        state=TrackState.CONFIRMED,
        hits=5,
        age=10,
        lost_frames=0,
    )
    px_v, py_v, meta_v = engine.get_spatial_anchor_point(vehicle, SpatialAnchorStrategy.ADAPTIVE)
    # Vehicle anchor must be centroid (cx=150.0, cy=100.0)
    assert (px_v, py_v) == (150.0, 100.0)
