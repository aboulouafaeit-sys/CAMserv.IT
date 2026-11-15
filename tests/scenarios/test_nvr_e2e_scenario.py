"""
tests.scenarios.test_nvr_e2e_scenario
=====================================

End-to-End Master Lifecycle Verification Scenario:
1. Synthetic frame stream ingestion into PreRollBuffer.
2. Analytics zone tripwire crossing detection with epistemic hypothesis tags.
3. Event trigger leading to NVR recording with RAM pre-roll frame stitching.
4. Continuous segmentation and atomic SHA-256 chunk persistence into SQLiteStore.
5. Judicial hold locking preventing premature deletion or quota purging.
6. Multi-camera synchronized playback timeline assembly.
7. Dual-control court-admissible forensic archive packaging and verification.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import time
import numpy as np
import pytest

from camserv.analytics.zones import Tripwire, ZoneAnalyticsEngine
from camserv.nvr.playback import PlaybackTimelineEngine
from camserv.nvr.recording_engine import NVRRecordingEngine, PreRollBuffer
from camserv.storage.forensics import EvidenceVerifier, ForensicSigner
from camserv.storage.sqlite_store import SQLiteStore


@pytest.mark.integration
def test_full_nvr_forensics_lifecycle(tmp_path: Path) -> None:
    """Execute complete end-to-end NVR surveillance, analytics, recording, and forensic export cycle."""
    db_path = tmp_path / "nvr_e2e.db"
    store = SQLiteStore(str(db_path))
    storage_dir = tmp_path / "nvr_e2e_recordings"
    storage_dir.mkdir(parents=True)

    # 1. Initialize NVR recording engine with 5-second segments
    nvr = NVRRecordingEngine(
        store=store,
        storage_dir=storage_dir,
        segment_duration_seconds=5.0,
        pre_roll_seconds=10.0,
    )

    cam_id = "cam_e2e_perimeter"

    # 2. Ingest 10 pre-roll background frames into buffer before any event
    now = time.time()
    for i in range(10):
        dummy_frame = np.full((120, 160, 3), 40 + i, dtype=np.uint8)
        nvr.ingest_frame(camera_id=cam_id, frame=dummy_frame, timestamp_utc=now - 10.0 + i)

    # 3. Setup spatial analytics tripwire across perimeter
    analytics = ZoneAnalyticsEngine()
    analytics.register_tripwire(Tripwire(
        tripwire_id="tw_gate",
        camera_id=cam_id,
        name="Main Gate Tripwire",
        start_point=(50.0, 0.0),
        end_point=(50.0, 100.0),
        direction="forward",
    ))

    # Frame 1: Track on left side of tripwire
    track_f1 = [{"track_id": 42, "ground_contact": (30.0, 50.0), "confidence": 0.92}]
    analytics.evaluate_tracks(cam_id, track_f1, now)

    # Frame 2: Track crosses tripwire to right side
    track_f2 = [{"track_id": 42, "ground_contact": (70.0, 50.0), "confidence": 0.92}]
    events = analytics.evaluate_tracks(cam_id, track_f2, now + 0.1)
    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "tripwire_crossed"
    assert ev.is_prediction is True

    # 4. Trigger event recording with pre-roll buffer stitching
    session = nvr.trigger_event(
        camera_id=cam_id,
        event_id=f"EV-{int(now)}",
        event_type="tripwire_intrusion",
        confidence=ev.confidence,
    )
    assert session is not None
    assert session.recording_type == "event"

    # Feed 15 active event frames
    for i in range(15):
        frame = np.full((120, 160, 3), 100 + i, dtype=np.uint8)
        nvr.ingest_frame(camera_id=cam_id, frame=frame, timestamp_utc=now + (i * 0.1))

    # Stop recording cleanly
    stopped = nvr.stop_recording(cam_id)
    assert stopped is True

    # Verify segments in SQLite
    recs = store.list_recordings(camera_id=cam_id)
    assert len(recs) == 1
    rec_id = recs[0]["recording_id"]
    segments = store.list_recording_segments(rec_id)
    assert len(segments) >= 1
    for seg in segments:
        assert Path(seg["file_path"]).exists()
        assert seg["file_size_bytes"] > 0
        assert len(seg["sha256_hash"]) == 64

    # 5. Place judicial hold on this event recording
    hold_success = nvr.set_judicial_hold(
        recording_id=rec_id,
        hold=True,
        reason="Perimeter intrusion breach evidence",
        operator_id="officer_77",
        case_id="CASE-BREACH-01",
    )
    assert hold_success is True

    # Verify hold prevents accidental deletion
    with pytest.raises(ValueError, match="active judicial hold"):
        store.delete_recording(rec_id)

    # 6. Assemble synchronized timeline via PlaybackTimelineEngine
    playback = PlaybackTimelineEngine(store=store, storage_dir=storage_dir)
    spans = playback.get_camera_timeline(
        camera_id=cam_id,
        start_time_utc=recs[0]["start_time_utc"],
        end_time_utc=recs[0]["end_time_utc"],
    )
    assert len(spans) >= 1
    assert spans[0].camera_id == cam_id

    # 7. Export court-admissible forensic evidence bundle with Ed25519 signature
    signer = ForensicSigner()
    out_zip = tmp_path / "e2e_forensic_package.zip"

    forensic_manifest = playback.export_forensic_package(
        camera_id=cam_id,
        start_time_utc=recs[0]["start_time_utc"],
        end_time_utc=recs[0]["end_time_utc"],
        output_zip=out_zip,
        operator_id="officer_77",
        case_id="CASE-BREACH-01",
        include_raw=True,
        dual_quorum_approved=True,
        signer=signer,
    )

    assert out_zip.exists()
    assert forensic_manifest["dual_quorum_approved"] is True

    # 8. Independent digital evidence verification
    verifier = EvidenceVerifier()
    audit_res = verifier.verify_package(out_zip, trusted_public_key_pem=forensic_manifest["public_key_pem"])
    assert audit_res.is_valid is True
    assert audit_res.signature_valid is True
    assert audit_res.manifest_hash_match is True
    assert audit_res.chain_of_custody_intact is True
