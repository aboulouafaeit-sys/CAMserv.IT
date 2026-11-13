"""Event detection and alert management tests for CAMserv.

Verifies:
- Zone intrusion detection via ray-casting point-in-polygon
- Fall detection via sudden aspect ratio change and velocity drop
- Abandoned object detection (unattended bag/stationary object)
- Crowd density anomaly detection (zone occupancy limits)
- Camera tamper detection (scene luminance/contrast distortion)
- Loitering detection (dwell time threshold breach)
- Event severity assignment rules
- High-severity events strictly require human verification
- Event deduplication and cooldown suppression
- Event lifecycle state machine transitions (detected -> pending -> verified/dismissed)
- Alert rate limiting against alert flooding storms
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import numpy as np
import pytest

from camserv.events.alerts import AlertManager, AlertRateLimiter
from camserv.events.detector import (
    DEFAULT_SEVERITIES,
    EventDetector,
    EventRule,
    EventState,
    EventType,
    PointInPolygon,
)
from camserv.pipeline.interfaces import (
    BoundingBox,
    Detection,
    Event,
    EventSeverity,
    Frame,
    Track,
    TrackState,
)


@pytest.mark.unit
def test_zone_intrusion_detection() -> None:
    """Verify zone intrusion is triggered when a tracked object enters a restricted polygon."""
    # Define rectangular polygon zone (100, 100) to (300, 300)
    polygon = [(100.0, 100.0), (300.0, 100.0), (300.0, 300.0), (100.0, 300.0)]
    rule = EventRule(
        rule_id="intrusion_rule_1",
        event_type=EventType.ZONE_INTRUSION,
        zone_id="restricted_zone",
        polygon=polygon,
        cooldown_seconds=10.0,
    )
    detector = EventDetector(rules=[rule])

    # Track outside zone: centre (50, 50)
    outside_track = Track(
        track_id=1,
        bbox=BoundingBox(30.0, 30.0, 70.0, 70.0),
        class_name="person",
        class_id=0,
        confidence=0.9,
        age=5,
        state=TrackState.CONFIRMED,
        camera_id="cam-01",
    )
    events_outside = detector.evaluate(tracks=[outside_track])
    assert len(events_outside) == 0

    # Track inside zone: centre (200, 200)
    inside_track = Track(
        track_id=2,
        bbox=BoundingBox(180.0, 180.0, 220.0, 220.0),
        class_name="person",
        class_id=0,
        confidence=0.95,
        age=5,
        state=TrackState.CONFIRMED,
        camera_id="cam-01",
    )
    events_inside = detector.evaluate(tracks=[inside_track])
    assert len(events_inside) == 1
    event = events_inside[0]
    assert event.event_type == EventType.ZONE_INTRUSION
    assert event.severity == EventSeverity.HIGH
    assert event.requires_verification is True
    assert event.is_prediction is True


@pytest.mark.unit
def test_fall_detection() -> None:
    """Verify fall detection triggers when person track transitions from vertical to horizontal."""
    detector = EventDetector()
    now = datetime.now(timezone.utc)

    # Initial upright pose (h > w, ratio > 1.2)
    upright_track = Track(
        track_id=10,
        bbox=BoundingBox(50.0, 50.0, 90.0, 170.0),  # w=40, h=120, ratio=0.33
        class_name="person",
        class_id=0,
        confidence=0.92,
        age=10,
        state=TrackState.CONFIRMED,
        camera_id="cam-01",
        velocity=(0.0, 0.0),
    )
    detector.evaluate([upright_track])

    # Person has fallen: horizontal bbox (w=120, h=40), low velocity
    fallen_track = Track(
        track_id=10,
        bbox=BoundingBox(50.0, 130.0, 170.0, 170.0),  # w=120, h=40, ratio=3.0
        class_name="person",
        class_id=0,
        confidence=0.95,
        age=12,
        state=TrackState.CONFIRMED,
        camera_id="cam-01",
        velocity=(0.1, 0.1),
    )
    events = detector.evaluate([fallen_track])

    fall_events = [e for e in events if e.event_type == EventType.FALL_DETECTION]
    assert len(fall_events) == 1
    fall_event = fall_events[0]
    assert fall_event.severity == EventSeverity.CRITICAL
    assert fall_event.requires_verification is True
    assert fall_event.is_prediction is True


@pytest.mark.unit
def test_abandoned_object_detection() -> None:
    """Verify abandoned object detection triggers when luggage is stationary without owner."""
    rule = EventRule(
        rule_id="abandoned_rule_1",
        event_type=EventType.ABANDONED_OBJECT,
        threshold_seconds=0.01,  # immediate trigger for test
        cooldown_seconds=10.0,
    )
    detector = EventDetector(rules=[rule])
    now = datetime.now(timezone.utc)

    # Stationary bag detection with no person nearby
    bag_detection = Detection(
        bbox=BoundingBox(100.0, 100.0, 140.0, 140.0),
        class_id=6,
        class_name="bag",
        confidence=0.88,
        camera_id="cam-01",
        frame_id=1,
        timestamp=now,
    )
    bag_track = Track(
        track_id=55,
        bbox=BoundingBox(100.0, 100.0, 140.0, 140.0),
        class_name="bag",
        class_id=6,
        confidence=0.88,
        age=10,
        state=TrackState.CONFIRMED,
        camera_id="cam-01",
        velocity=(0.0, 0.0),
    )

    # First evaluation records stationary tracking
    detector.evaluate([bag_track], detections=[bag_detection])
    time.sleep(0.02)
    # Second evaluation exceeds threshold without person nearby
    events = detector.evaluate([bag_track], detections=[bag_detection])

    abandoned_events = [e for e in events if e.event_type == EventType.ABANDONED_OBJECT]
    assert len(abandoned_events) >= 1
    assert abandoned_events[0].severity == EventSeverity.HIGH
    assert abandoned_events[0].requires_verification is True


@pytest.mark.unit
def test_crowd_density_anomaly() -> None:
    """Verify crowd density anomaly triggers when track count exceeds zone capacity limit."""
    polygon = [(0.0, 0.0), (500.0, 0.0), (500.0, 500.0), (0.0, 500.0)]
    rule = EventRule(
        rule_id="crowd_rule_1",
        event_type=EventType.CROWD_DENSITY_ANOMALY,
        zone_id="waiting_area",
        polygon=polygon,
        capacity_limit=2,  # Alert when > 2 people in zone
        cooldown_seconds=10.0,
    )
    detector = EventDetector(rules=[rule])

    # 3 people in the zone
    tracks = [
        Track(track_id=1, bbox=BoundingBox(10, 10, 30, 30), class_name="person", class_id=0, confidence=0.9, age=5, state=TrackState.CONFIRMED, camera_id="cam-01"),
        Track(track_id=2, bbox=BoundingBox(50, 50, 70, 70), class_name="person", class_id=0, confidence=0.9, age=5, state=TrackState.CONFIRMED, camera_id="cam-01"),
        Track(track_id=3, bbox=BoundingBox(90, 90, 110, 110), class_name="person", class_id=0, confidence=0.9, age=5, state=TrackState.CONFIRMED, camera_id="cam-01"),
    ]

    events = detector.evaluate(tracks=tracks)
    crowd_events = [e for e in events if e.event_type == EventType.CROWD_DENSITY_ANOMALY]
    assert len(crowd_events) == 1
    assert crowd_events[0].severity == EventSeverity.MEDIUM


@pytest.mark.unit
def test_camera_tamper_detection() -> None:
    """Verify camera tampering detects sudden blinding or occlusion (all-black or uniform frame)."""
    detector = EventDetector()
    now = datetime.now(timezone.utc)

    # Frame 1: Normal textured frame
    normal_img = np.random.randint(50, 200, size=(100, 100, 3), dtype=np.uint8)
    frame1 = Frame(image=normal_img, camera_id="cam-01", timestamp=now, frame_id=1)
    detector.evaluate([], frame=frame1)

    # Frame 2: Tampered / covered camera (all black)
    tampered_img = np.zeros((100, 100, 3), dtype=np.uint8)
    frame2 = Frame(image=tampered_img, camera_id="cam-01", timestamp=now, frame_id=2)
    events = detector.evaluate([], frame=frame2)

    tamper_events = [e for e in events if e.event_type == EventType.CAMERA_TAMPER]
    assert len(tamper_events) == 1
    assert tamper_events[0].severity == EventSeverity.CRITICAL
    assert tamper_events[0].requires_verification is True


@pytest.mark.unit
def test_loitering_detection() -> None:
    """Verify loitering detection triggers when an object dwells in a zone past threshold."""
    polygon = [(0.0, 0.0), (300.0, 0.0), (300.0, 300.0), (0.0, 300.0)]
    rule = EventRule(
        rule_id="loiter_rule_1",
        event_type=EventType.LOITERING,
        zone_id="courtyard",
        polygon=polygon,
        threshold_seconds=0.01,
        cooldown_seconds=10.0,
    )
    detector = EventDetector(rules=[rule])

    track = Track(
        track_id=42,
        bbox=BoundingBox(50.0, 50.0, 90.0, 150.0),
        class_name="person",
        class_id=0,
        confidence=0.9,
        age=5,
        state=TrackState.CONFIRMED,
        camera_id="cam-01",
    )

    detector.evaluate([track])
    time.sleep(0.02)
    events = detector.evaluate([track])

    loiter_events = [e for e in events if e.event_type == EventType.LOITERING]
    assert len(loiter_events) == 1
    assert loiter_events[0].event_type == EventType.LOITERING


@pytest.mark.unit
def test_event_severity_assignment() -> None:
    """Verify standard default severities are properly assigned to detected event types."""
    assert DEFAULT_SEVERITIES[EventType.ZONE_INTRUSION] == EventSeverity.HIGH
    assert DEFAULT_SEVERITIES[EventType.FALL_DETECTION] == EventSeverity.CRITICAL
    assert DEFAULT_SEVERITIES[EventType.CAMERA_TAMPER] == EventSeverity.CRITICAL
    assert DEFAULT_SEVERITIES[EventType.LOITERING] == EventSeverity.MEDIUM


@pytest.mark.unit
def test_high_severity_requires_human_verification() -> None:
    """Verify that all HIGH and CRITICAL events have requires_verification=True."""
    polygon = [(0.0, 0.0), (200.0, 0.0), (200.0, 200.0), (0.0, 200.0)]
    rule = EventRule(
        rule_id="rule_high",
        event_type=EventType.ZONE_INTRUSION,
        polygon=polygon,
        severity=EventSeverity.HIGH,
    )
    detector = EventDetector(rules=[rule])
    track = Track(
        track_id=1,
        bbox=BoundingBox(20, 20, 40, 40),
        class_name="person",
        class_id=0,
        confidence=0.9,
        age=1,
        state=TrackState.CONFIRMED,
        camera_id="cam-01",
    )

    events = detector.evaluate([track])
    assert len(events) == 1
    assert events[0].severity in (EventSeverity.HIGH, EventSeverity.CRITICAL)
    assert events[0].requires_verification is True


@pytest.mark.unit
def test_event_deduplication_cooldown() -> None:
    """Verify that repeated event triggers for the same target are suppressed during cooldown."""
    polygon = [(0.0, 0.0), (200.0, 0.0), (200.0, 200.0), (0.0, 200.0)]
    rule = EventRule(
        rule_id="rule_cooldown",
        event_type=EventType.ZONE_INTRUSION,
        polygon=polygon,
        cooldown_seconds=60.0,  # 60s cooldown
    )
    detector = EventDetector(rules=[rule])
    track = Track(
        track_id=99,
        bbox=BoundingBox(50, 50, 90, 90),
        class_name="person",
        class_id=0,
        confidence=0.9,
        age=1,
        state=TrackState.CONFIRMED,
        camera_id="cam-01",
    )

    # First trigger produces event
    first_events = detector.evaluate([track])
    assert len(first_events) == 1

    # Second immediate trigger must be suppressed by cooldown
    second_events = detector.evaluate([track])
    assert len(second_events) == 0


@pytest.mark.unit
def test_event_state_machine_transitions() -> None:
    """Verify event lifecycle state transitions: DETECTED -> PENDING -> VERIFIED or DISMISSED."""
    detector = EventDetector()
    event_id = "evt-lifecycle-test"

    # Initial state is DETECTED
    assert detector.get_event_state(event_id) == EventState.DETECTED

    # DETECTED -> PENDING_VERIFICATION (allowed)
    assert detector.transition_event_state(event_id, EventState.PENDING_VERIFICATION) is True
    assert detector.get_event_state(event_id) == EventState.PENDING_VERIFICATION

    # PENDING_VERIFICATION -> VERIFIED (allowed)
    assert detector.transition_event_state(event_id, EventState.VERIFIED) is True
    assert detector.get_event_state(event_id) == EventState.VERIFIED

    # VERIFIED -> PENDING_VERIFICATION (disallowed final state)
    assert detector.transition_event_state(event_id, EventState.PENDING_VERIFICATION) is False
    assert detector.get_event_state(event_id) == EventState.VERIFIED


@pytest.mark.unit
def test_alert_rate_limiting() -> None:
    """Verify AlertRateLimiter limits dispatch when alert frequency exceeds threshold."""
    limiter = AlertRateLimiter(max_alerts=3, window_seconds=60.0)

    # First 3 alerts permitted
    assert limiter.allow("channel_1") is True
    assert limiter.allow("channel_1") is True
    assert limiter.allow("channel_1") is True

    # 4th alert exceeds limit in same window -> rejected
    assert limiter.allow("channel_1") is False

    # Different key remains unaffected
    assert limiter.allow("channel_2") is True
