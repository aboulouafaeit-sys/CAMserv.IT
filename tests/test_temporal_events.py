"""Tests for camserv.events.temporal."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from camserv.events.temporal import TemporalEventEngine
from camserv.pipeline.interfaces import BoundingBox, EventSeverity, Track, TrackState


@pytest.mark.unit
def test_fall_detection_temporal_progression() -> None:
    """Test multi-frame aspect-ratio transition triggering a fall event with explainability trace."""
    engine = TemporalEventEngine(fall_dwell_threshold_sec=0.2)
    base_time = datetime.now(timezone.utc)

    # 1. Subject upright (H=200, W=80 -> AR=0.4) for 10 frames
    for i in range(12):
        t_frame = base_time + timedelta(milliseconds=i * 66)
        track = Track(
            track_id=101,
            bbox=BoundingBox(x1=100.0, y1=100.0, x2=180.0, y2=300.0),
            class_name="person",
            class_id=0,
            confidence=0.92,
            age=i + 1,
            state=TrackState.CONFIRMED,
            camera_id="cam-dock",
        )
        engine.update_track(track, frame_id=i, timestamp=t_frame)

    events_before = engine.evaluate_temporal_events([track], camera_id="cam-dock", current_time=t_frame)
    assert len(events_before) == 0

    # 2. Subject transitions to ground prostrate position (H=60, W=180 -> AR=3.0) for 8 frames
    for j in range(8):
        t_frame = base_time + timedelta(milliseconds=(12 + j) * 66)
        track = Track(
            track_id=101,
            bbox=BoundingBox(x1=100.0, y1=240.0, x2=280.0, y2=300.0),
            class_name="person",
            class_id=0,
            confidence=0.88,
            age=12 + j + 1,
            state=TrackState.CONFIRMED,
            camera_id="cam-dock",
        )
        engine.update_track(track, frame_id=12 + j, timestamp=t_frame)

    events = engine.evaluate_temporal_events([track], camera_id="cam-dock", current_time=t_frame)
    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "fall_detection"
    assert ev.severity == EventSeverity.CRITICAL
    assert ev.requires_verification is True
    assert ev.is_prediction is True
    assert "supporting_observations" in ev.metadata
    assert len(ev.metadata["supporting_observations"]) == 2
    assert "reasoning_trace" in ev.metadata
    assert "aspect_ratio" in ev.metadata["reasoning_trace"]


@pytest.mark.unit
def test_loitering_progression() -> None:
    """Test that tracks exceeding dwell threshold generate loitering events."""
    engine = TemporalEventEngine(loiter_warning_sec=2.0, loiter_critical_sec=5.0)
    t0 = datetime.now(timezone.utc)

    # Initial appearance
    track = Track(
        track_id=202,
        bbox=BoundingBox(x1=50.0, y1=50.0, x2=120.0, y2=200.0),
        class_name="person",
        class_id=0,
        confidence=0.90,
        age=1,
        state=TrackState.CONFIRMED,
        camera_id="cam-gate",
    )
    engine.update_track(track, frame_id=1, timestamp=t0)
    evs = engine.evaluate_temporal_events([track], camera_id="cam-gate", current_time=t0)
    assert len(evs) == 0

    # Advance time by 3 seconds (> loiter_warning_sec)
    t1 = t0 + timedelta(seconds=3.0)
    engine.update_track(track, frame_id=45, timestamp=t1)
    evs_warning = engine.evaluate_temporal_events([track], camera_id="cam-gate", current_time=t1)
    assert len(evs_warning) == 1
    assert evs_warning[0].event_type == "loitering"
    assert evs_warning[0].severity == EventSeverity.MEDIUM

    # Advance time by 6 seconds (> loiter_critical_sec)
    # Clear cooldown for test purpose
    engine._cooldowns.clear()
    t2 = t0 + timedelta(seconds=6.0)
    engine.update_track(track, frame_id=90, timestamp=t2)
    evs_critical = engine.evaluate_temporal_events([track], camera_id="cam-gate", current_time=t2)
    assert len(evs_critical) == 1
    assert evs_critical[0].severity == EventSeverity.HIGH
    assert evs_critical[0].requires_verification is True
