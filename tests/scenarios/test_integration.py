"""End-to-end scenario and integration tests for CAMserv.

Verifies:
- Full end-to-end pipeline flow: acquisition -> decoding -> inference -> tracking -> event detection -> storage
- Cross-camera event correlation matching events across cameras within temporal window
- Privacy mask application ensuring PII/faces are blurred before long-term storage
- Tamper-evident evidence chain lifecycle: detection -> encryption -> chain -> verify -> decrypt
- Human-in-the-loop consequential decision workflow from detection to verification and audit logging
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from camserv.api.app import create_app
from camserv.events.detector import EventDetector, EventRule, EventType
from camserv.inference.detector import BaseDetector, Detection
from camserv.inference.privacy import BlurMethod, PrivacyConfig, PrivacyFilter, PrivacyZone
from camserv.inference.scene import (
    ObservationStatus,
    SceneAnalyzer,
    SceneEventType,
    SceneObservation,
)
from camserv.pipeline.engine import EngineConfig, PipelineEngine
from camserv.pipeline.interfaces import (
    BoundingBox,
    Event,
    EventSeverity,
    Frame,
    StorageBackend,
    Track,
    TrackState,
)
from camserv.security.audit import AuditAction, AuditLogger
from camserv.security.auth import AuthManager, Role
from camserv.storage.evidence import EvidenceStore
from camserv.tracking.bytetrack import ByteTracker


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_pipeline_frame_to_event() -> None:
    """Verify that a frame ingested into the pipeline flows through all stages to emit a stored event."""
    now = datetime.now(timezone.utc)

    # 1. Mock detector returning an intrusion candidate
    mock_detector = MagicMock(spec=BaseDetector)
    mock_detector.warmup = AsyncMock()
    mock_detector.detect = AsyncMock(
        return_value=[
            Detection(
                bbox=BoundingBox(120.0, 120.0, 180.0, 200.0),
                class_id=0,
                class_name="person",
                confidence=0.92,
                camera_id="cam-e2e-01",
                frame_id=1,
                timestamp=now,
                is_prediction=True,
            )
        ]
    )

    # 2. Real ByteTracker configured for instant confirmation
    tracker = ByteTracker(track_thresh=0.5, min_hits=1)

    # 3. Real EventDetector with zone intrusion rule
    rule = EventRule(
        rule_id="e2e_intrusion_rule",
        event_type=EventType.ZONE_INTRUSION,
        zone_id="secure_room",
        polygon=[(100.0, 100.0), (300.0, 100.0), (300.0, 300.0), (100.0, 300.0)],
        cooldown_seconds=60.0,
    )
    event_detector = EventDetector(rules=[rule])

    # 4. Mock storage backend
    stored_events: list[Event] = []
    stored_detections: list[Detection] = []
    mock_storage = MagicMock(spec=StorageBackend)
    mock_storage.store_detections = AsyncMock(side_effect=lambda dets: stored_detections.extend(dets))
    mock_storage.store_event = AsyncMock(side_effect=lambda ev: stored_events.append(ev))
    mock_storage.health_check = AsyncMock(return_value=True)

    # 5. Initialize PipelineEngine
    engine = PipelineEngine(
        config=EngineConfig(raw_queue_size=10, decoded_queue_size=10),
        detector=mock_detector,
        tracker=tracker,
        event_detector=event_detector,
        storage=mock_storage,
    )

    await engine.start()

    # Enqueue a test frame
    test_frame = Frame(
        image=np.zeros((480, 640, 3), dtype=np.uint8),
        camera_id="cam-e2e-01",
        timestamp=now,
        frame_id=1,
    )
    await engine.raw_queue.put(test_frame)

    # Allow asynchronous pipeline stages to process
    await asyncio.sleep(0.3)

    await engine.stop()

    # Verify that the event was detected, carries is_prediction=True, and was persisted
    assert len(stored_events) >= 1
    emitted = stored_events[0]
    assert emitted.event_type == EventType.ZONE_INTRUSION
    assert emitted.severity == EventSeverity.HIGH
    assert emitted.is_prediction is True
    assert emitted.requires_verification is True


@pytest.mark.integration
def test_multi_camera_event_correlation() -> None:
    """Verify SceneAnalyzer correlates related security events across adjacent cameras within time window."""
    analyzer = SceneAnalyzer()
    t0 = datetime(2026, 11, 13, 14, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 11, 13, 14, 0, 2, tzinfo=timezone.utc)  # 2 seconds later (within 5s window)

    # Event on Camera North
    obs_north = SceneObservation(
        event_type=SceneEventType.HAZARD,
        camera_id="cam_north",
        timestamp=t0,
        confidence=0.88,
        status=ObservationStatus.VERIFIED,
        description="Smoke hazard detected",
        details={"hazard": "smoke"},
    )

    # Event on Camera East
    obs_east = SceneObservation(
        event_type=SceneEventType.HAZARD,
        camera_id="cam_east",
        timestamp=t1,
        confidence=0.92,
        status=ObservationStatus.VERIFIED,
        description="Smoke hazard detected",
        details={"hazard": "smoke"},
    )

    correlated = analyzer.correlate_events([obs_north, obs_east], time_window_sec=5.0)

    assert len(correlated) == 1
    corr_event = correlated[0]
    assert corr_event.event_type == SceneEventType.CORRELATED
    assert corr_event.camera_id == "cam_north+cam_east"
    assert corr_event.status == ObservationStatus.VERIFIED
    assert "cam_north" in corr_event.details["source_cameras"]
    assert "cam_east" in corr_event.details["source_cameras"]


@pytest.mark.integration
def test_privacy_mask_applied_before_storage(tmp_path: Path) -> None:
    """Verify frames are processed through PrivacyFilter to mask PII/faces before saving to evidence store."""
    zone = PrivacyZone(
        name="private_window",
        polygon=[(50, 50), (150, 50), (150, 150), (50, 150)],
        blur_output=True,
        blur_method=BlurMethod.SOLID,
    )
    privacy_filter = PrivacyFilter(config=PrivacyConfig(zones=[zone], solid_color=(0, 0, 0)))

    # White source frame (200x200x3)
    raw_frame_image = np.full((200, 200, 3), 255, dtype=np.uint8)

    # Apply privacy filter
    masked_frame_image = privacy_filter.apply_mask(raw_frame_image)

    # Save masked frame into EvidenceStore
    evidence_store = EvidenceStore(base_dir=tmp_path / "privacy_evidence")
    record = evidence_store.store_evidence(
        event_id="evt_masked_01",
        camera_id="cam_entry",
        data=masked_frame_image.tobytes(),
        metadata={"masked": True},
    )

    # Retrieve and verify the stored data is masked
    _, stored_bytes = evidence_store.retrieve_evidence("evt_masked_01")
    reconstructed = np.frombuffer(stored_bytes, dtype=np.uint8).reshape((200, 200, 3))

    # Center of private zone must be black (masked)
    assert np.all(reconstructed[100, 100] == [0, 0, 0])
    # Outside zone remains unmodified
    assert np.all(reconstructed[10, 10] == [255, 255, 255])


@pytest.mark.integration
def test_evidence_chain_end_to_end(tmp_path: Path) -> None:
    """Verify complete evidence storage lifecycle with AES-256-GCM encryption and hash chain audit."""
    evidence_dir = tmp_path / "secure_evidence"
    store = EvidenceStore(base_dir=evidence_dir)

    payloads = [
        ("evt_1", "cam_1", b"high_res_snapshot_1"),
        ("evt_2", "cam_1", b"high_res_snapshot_2"),
        ("evt_3", "cam_2", b"high_res_snapshot_3"),
    ]

    records = []
    for eid, cid, data in payloads:
        rec = store.store_evidence(event_id=eid, camera_id=cid, data=data)
        records.append(rec)

    # Validate full chain integrity
    is_valid, count, errors = store.verify_full_chain()
    assert is_valid is True
    assert count == 3
    assert len(errors) == 0

    # Retrieve and verify each item matches decrypted payload
    for eid, _, expected_data in payloads:
        rec, dec = store.retrieve_evidence(eid)
        assert dec == expected_data
        assert store.verify_record(rec) is True


@pytest.mark.integration
def test_human_verification_workflow_end_to_end(tmp_path: Path) -> None:
    """Verify human-in-the-loop verification workflow transitions event state and creates tamper-evident audit record."""
    audit_file = tmp_path / "hitl_audit.jsonl"
    audit_logger = AuditLogger(log_path=audit_file)
    event_detector = EventDetector()

    # 1. Event detected by AI model
    event = Event(
        event_id="evt_hitl_999",
        event_type=EventType.ZONE_INTRUSION,
        severity=EventSeverity.CRITICAL,
        confidence=0.96,
        camera_id="cam_vault",
        timestamp=datetime.now(timezone.utc),
        requires_verification=True,
        description="Person detected in high-security bank vault",
        is_prediction=True,
    )

    # High severity event enters PENDING_VERIFICATION state
    assert event.requires_verification is True
    event_detector.transition_event_state(event.event_id, "pending_verification")
    assert event_detector.get_event_state(event.event_id) == "pending_verification"

    # 2. Human operator confirms/accepts the alert
    operator_user = "operator_sarah"
    verification_success = event_detector.transition_event_state(event.event_id, "verified")
    assert verification_success is True
    assert event_detector.get_event_state(event.event_id) == "verified"

    # 3. Log verification action into tamper-evident audit log
    audit_entry = audit_logger.log(
        actor=operator_user,
        action=AuditAction.EVENT_VERIFICATION,
        resource=f"event:{event.event_id}",
        result="SUCCESS",
        details={
            "original_prediction_confidence": event.confidence,
            "decision": "verified_authorized_entry",
            "is_prediction": event.is_prediction,
        },
    )

    assert audit_entry.actor == operator_user
    assert audit_entry.action == AuditAction.EVENT_VERIFICATION

    # Verify audit log chain validity
    is_valid, count, errors = audit_logger.verify_integrity()
    assert is_valid is True
    assert count == 1
    assert len(errors) == 0
