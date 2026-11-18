"""
tests/test_phase27_scene_rules_events.py
========================================

Verification of SceneUnderstandingEngine (OBSERVATION -> MEASUREMENT -> INFERENCE -> EVENT),
ConfigurableRulesEngine (profile presets), EventDetectionEngine (deduplication, review workflow),
and EvidenceProvenanceEngine (tamper-evident SHA-256 frame link).
"""

import numpy as np
import pytest

from camserv.intelligence.contracts import (
    BoundingBox,
    CameraProfilePreset,
    DetectionPrediction,
    EpistemicLevel,
    IntelligenceEventType,
    TrackLifecycleState,
    TrackRecord,
)
from camserv.intelligence.events import EventDetectionEngine
from camserv.intelligence.evidence import EvidenceProvenanceEngine
from camserv.intelligence.rules import ConfigurableRulesEngine
from camserv.intelligence.scene import SceneUnderstandingEngine


@pytest.mark.unit
def test_scene_understanding_epistemic_reasoning_chain() -> None:
    """Verify that SceneUnderstandingEngine generates explicit 4-tier reasoning without collapsing."""
    scene_engine = SceneUnderstandingEngine(camera_id="cam-01", stationary_threshold_sec=5.0)

    # Frame 1: Moving car
    trk_moving = TrackRecord(
        track_id=1,
        camera_id="cam-01",
        session_id="s1",
        bbox=BoundingBox(50.0, 50.0, 150.0, 100.0),
        class_name="car",
        class_id=1,
        confidence=0.89,
        state=TrackLifecycleState.TRACKED,
        age_frames=1,
        created_at_utc=100.0,
        last_seen_utc=100.0,
        velocity_pixels_per_sec=(30.0, 0.0),
    )
    rec1 = scene_engine.evaluate_scene([trk_moving], [], frame_id=1, timestamp_utc=100.0)
    assert len(rec1.observations) >= 1
    assert len(rec1.measurements) >= 1
    assert len(rec1.events) == 0  # No stationary event yet

    # Frame 2: Car stopped for > 5 seconds
    trk_stopped = TrackRecord(
        track_id=1,
        camera_id="cam-01",
        session_id="s1",
        bbox=BoundingBox(50.0, 50.0, 150.0, 100.0),
        class_name="car",
        class_id=1,
        confidence=0.89,
        state=TrackLifecycleState.TRACKED,
        age_frames=30,
        created_at_utc=100.0,
        last_seen_utc=106.0,
        velocity_pixels_per_sec=(0.1, 0.0),  # Stationary
    )
    # Prime timer
    scene_engine.evaluate_scene([trk_stopped], [], frame_id=2, timestamp_utc=100.5)
    # Evaluate at 106.0 (> 5.0s delta)
    rec2 = scene_engine.evaluate_scene([trk_stopped], [], frame_id=30, timestamp_utc=106.0)
    assert any("VEHICLE_STOPPED" in evt for evt in rec2.events)
    assert rec2.epistemic_level == EpistemicLevel.EVENT


@pytest.mark.unit
def test_event_deduplication_window() -> None:
    """Verify EventDetectionEngine suppresses duplicate events within the configured window."""
    event_engine = EventDetectionEngine(deduplication_window_sec=3.0)

    # Publish event 1 at t=10.0
    evt1 = event_engine.publish_event(
        event_type=IntelligenceEventType.VEHICLE_STOPPED,
        camera_id="cam-01",
        confidence=0.90,
        severity="MEDIUM",
        epistemic_level=EpistemicLevel.EVENT,
        evidence_hash="hash1",
        source_segment_id="seg_01",
        source_frame_id=10,
        entity_key="track_01",
        timestamp_utc=10.0,
    )
    assert evt1 is not None

    # Duplicate attempt at t=11.0 (< 3.0s window) -> Must be suppressed (None)
    evt2 = event_engine.publish_event(
        event_type=IntelligenceEventType.VEHICLE_STOPPED,
        camera_id="cam-01",
        confidence=0.90,
        severity="MEDIUM",
        epistemic_level=EpistemicLevel.EVENT,
        evidence_hash="hash1",
        source_segment_id="seg_01",
        source_frame_id=15,
        entity_key="track_01",
        timestamp_utc=11.0,
    )
    assert evt2 is None

    # Attempt at t=14.0 (> 3.0s window) -> Must succeed
    evt3 = event_engine.publish_event(
        event_type=IntelligenceEventType.VEHICLE_STOPPED,
        camera_id="cam-01",
        confidence=0.90,
        severity="MEDIUM",
        epistemic_level=EpistemicLevel.EVENT,
        evidence_hash="hash1",
        source_segment_id="seg_01",
        source_frame_id=50,
        entity_key="track_01",
        timestamp_utc=14.0,
    )
    assert evt3 is not None


@pytest.mark.unit
def test_camera_profile_application() -> None:
    """Verify applying camera profile presets configures appropriate sampling and threshold limits."""
    event_engine = EventDetectionEngine()
    rules_engine = ConfigurableRulesEngine(event_engine=event_engine)

    # Road Traffic profile
    cfg_road = rules_engine.apply_profile("cam-highway", CameraProfilePreset.ROAD_TRAFFIC)
    assert cfg_road.profile_preset == CameraProfilePreset.ROAD_TRAFFIC
    assert cfg_road.sampling_fps == 6.0
    assert "traffic" in cfg_road.enabled_engines

    # Parking profile
    cfg_parking = rules_engine.apply_profile("cam-lot", CameraProfilePreset.PARKING)
    assert cfg_parking.profile_preset == CameraProfilePreset.PARKING
    assert cfg_parking.sampling_fps == 3.0


@pytest.mark.unit
def test_evidence_provenance_cryptographic_verification() -> None:
    """Verify that EvidenceProvenanceEngine cryptographically verifies source frame integrity."""
    event_engine = EventDetectionEngine()
    provenance_engine = EvidenceProvenanceEngine()

    evt = event_engine.publish_event(
        event_type=IntelligenceEventType.PERSON_DETECTED,
        camera_id="cam-01",
        confidence=0.95,
        severity="INFO",
        epistemic_level=EpistemicLevel.EVENT,
        evidence_hash="mock",
        source_segment_id="seg_01",
        source_frame_id=1,
    )
    assert evt is not None

    frame = np.full((100, 100, 3), 200, dtype=np.uint8)
    link = provenance_engine.create_evidence_link(evt, frame)

    assert link.is_derived_artifact is True
    assert len(link.frame_sha256) == 64

    # Verification against identical frame must succeed
    assert provenance_engine.verify_evidence_integrity(link.evidence_id, frame) is True

    # Verification against mutated frame must fail
    mutated_frame = np.copy(frame)
    mutated_frame[0, 0, 0] = 0
    assert provenance_engine.verify_evidence_integrity(link.evidence_id, mutated_frame) is False
