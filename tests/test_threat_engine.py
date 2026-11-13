"""Tests for 100% Local Threat Scoring, Pose Analysis, & Narrative Engine."""

from datetime import datetime, timezone
import pytest

from camserv.events.threat_engine import (
    LocalThreatEngine,
    SecurityNarrative,
    ThreatScoreBreakdown,
)
from camserv.inference.segmentation import SegmentationEngine
from camserv.pipeline.interfaces import BoundingBox, Track, TrackState


@pytest.fixture
def threat_engine() -> LocalThreatEngine:
    return LocalThreatEngine()


@pytest.fixture
def person_track() -> Track:
    return Track(
        track_id=402,
        bbox=BoundingBox(100.0, 100.0, 180.0, 320.0),
        class_name="person",
        class_id=0,
        confidence=0.91,
        age=75,
        state=TrackState.CONFIRMED,
        camera_id="cam-north",
        velocity=(0.3, 0.2),
        trajectory=[(100.0, 100.0), (105.0, 105.0)],
    )


def test_multi_factor_threat_scoring_normal(threat_engine: LocalThreatEngine, person_track: Track):
    # Daytime, normal corridor, normal speed
    day_time = datetime(2026, 11, 14, 14, 0, 0, tzinfo=timezone.utc)
    breakdown = threat_engine.evaluate_threat(
        person_track,
        zone_type="corridor",
        current_time=day_time
    )
    assert 0.0 <= breakdown.total_score <= 100.0
    assert breakdown.is_critical is False
    assert breakdown.time_score <= 5.0


def test_multi_factor_threat_scoring_critical_night_tampering(
    threat_engine: LocalThreatEngine,
    person_track: Track
):
    # Nighttime (23:30), restricted fence, bending pose
    night_time = datetime(2026, 11, 14, 23, 30, 0, tzinfo=timezone.utc)
    person_track.age = 500  # 20 seconds dwelling at fence
    engine_seg = SegmentationEngine()
    pose = engine_seg.generate_synthetic_pose(person_track.bbox, posture="bending")

    breakdown = threat_engine.evaluate_threat(
        person_track,
        zone_type="restricted fence perimeter",
        current_time=night_time,
        pose=pose
    )
    assert breakdown.total_score >= 65.0
    assert "Bending" in breakdown.dominant_behavior or "Tampering" in breakdown.dominant_behavior
    assert breakdown.zone_score >= 18.0
    assert breakdown.time_score == 15.0


def test_unattended_object_departure(threat_engine: LocalThreatEngine, person_track: Track):
    # Person walking away at 1.5 m/s
    person_track.velocity = (1.2, 0.9)
    # Bag track remaining stationary at 200px distance
    bag_track = Track(
        track_id=88,
        bbox=BoundingBox(350.0, 100.0, 400.0, 150.0),
        class_name="bag",
        class_id=6,
        confidence=0.88,
        age=60,
        state=TrackState.CONFIRMED,
        camera_id="cam-north",
        velocity=(0.0, 0.0),
    )
    is_abandoned = threat_engine.check_unattended_object(person_track, bag_track, separation_threshold_px=100.0)
    assert is_abandoned is True

    breakdown = threat_engine.evaluate_threat(
        person_track,
        zone_type="terminal hall",
        associated_bag_track=bag_track
    )
    assert "Unattended" in breakdown.dominant_behavior


def test_deterministic_narrative_generation(threat_engine: LocalThreatEngine, person_track: Track):
    breakdown = ThreatScoreBreakdown(
        zone_score=20.0,
        time_score=15.0,
        kinematics_score=15.0,
        pose_score=18.0,
        duration_score=12.0,
        total_score=80.0,
        dominant_behavior="Repeated Bending / Lock Tampering",
        is_critical=True,
    )
    narrative = threat_engine.generate_narrative(
        person_track,
        breakdown,
        zone_name="Northern Fence",
        is_enhanced_isp=True
    )
    assert isinstance(narrative, SecurityNarrative)
    assert "Object (ID #402)" in narrative.english_report
    assert "Northern Fence" in narrative.english_report
    assert "Threat Level: 80%" in narrative.english_report

    # Check Arabic report
    assert "تم رصد الكائن" in narrative.arabic_report
    assert "#402" in narrative.arabic_report
    assert "80%" in narrative.arabic_report
    assert "العبث" in narrative.arabic_report
