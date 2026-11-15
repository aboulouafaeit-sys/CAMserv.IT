"""
Unit and integration tests for CAMserv NVR recording engine, pre-roll buffer,
recording scheduler, crash recovery, and storage quota management.
"""

from __future__ import annotations

import time
from datetime import datetime, time as dtime, timezone
from pathlib import Path
import numpy as np
import pytest

from camserv.nvr.recording_engine import (
    NVRRecordingEngine,
    PreRollBuffer,
    SegmentWriter,
)
from camserv.nvr.recording_scheduler import RecordingScheduler
from camserv.storage.sqlite_store import SQLiteStore


@pytest.mark.unit
def test_pre_roll_buffer_sliding_window() -> None:
    """Test that PreRollBuffer accurately retains only the last 15s of frames."""
    buffer = PreRollBuffer(pre_roll_seconds=2.0)
    now = time.time()

    # Push 3 frames at different historical times
    f1 = np.ones((100, 100, 3), dtype=np.uint8) * 10
    f2 = np.ones((100, 100, 3), dtype=np.uint8) * 20
    f3 = np.ones((100, 100, 3), dtype=np.uint8) * 30

    buffer.push(now - 5.0, f1)  # 5s ago (should be pruned)
    buffer.push(now - 1.0, f2)  # 1s ago (within 2s window)
    buffer.push(now, f3)        # now (within 2s window)

    # Frame 1 should have been pruned
    assert len(buffer) == 2
    snapshot = buffer.get_snapshot()
    assert len(snapshot) == 2
    assert snapshot[0][0] == now - 1.0
    assert snapshot[1][0] == now

    # Flush clears buffer
    flushed = buffer.flush()
    assert len(flushed) == 2
    assert len(buffer) == 0


@pytest.mark.unit
def test_recording_scheduler_evaluation(tmp_path: Path) -> None:
    """Test day-of-week and time-of-day recording schedule matching."""
    db_file = tmp_path / "sched_test.db"
    store = SQLiteStore(db_path=db_file)
    scheduler = RecordingScheduler(store=store, default_mode="disabled")

    # Add schedule: Tuesday (weekday=1) between 09:00 and 17:00 -> continuous
    scheduler.add_schedule(
        schedule_id="sched_tue_work",
        camera_id="cam_main",
        day_of_week=1,
        start_time_str="09:00",
        end_time_str="17:00",
        mode="continuous",
    )

    # Test Tuesday at 12:00 -> Should record continuous
    dt_active = datetime(2026, 11, 17, 12, 0, 0, tzinfo=timezone.utc)  # Nov 17 2026 is Tuesday
    assert dt_active.weekday() == 1
    should_record, mode = scheduler.evaluate_schedule("cam_main", dt_active)
    assert should_record is True
    assert mode == "continuous"

    # Test Tuesday at 20:00 -> Outside window -> False
    dt_evening = datetime(2026, 11, 17, 20, 0, 0, tzinfo=timezone.utc)
    should_record, mode = scheduler.evaluate_schedule("cam_main", dt_evening)
    assert should_record is False
    assert mode == "disabled"

    # Test Wednesday (weekday=2) -> False
    dt_wed = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
    should_record, mode = scheduler.evaluate_schedule("cam_main", dt_wed)
    assert should_record is False


@pytest.mark.unit
def test_segment_writer_atomic_finalization(tmp_path: Path) -> None:
    """Test that SegmentWriter writes to .part and renames atomically to .mp4 with SHA-256."""
    output_file = tmp_path / "test_seg001.mp4"
    writer = SegmentWriter(output_path=output_file, fps=10.0, width=320, height=240)

    # Write 10 synthetic frames
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    for _ in range(10):
        writer.write_frame(frame)

    assert writer.part_path.exists()
    assert not output_file.exists()

    final_path, file_size, sha256_hash, duration = writer.close()
    assert final_path == output_file
    assert output_file.exists()
    assert not writer.part_path.exists()
    assert file_size > 0
    assert len(sha256_hash) == 64
    assert duration == 1.0  # 10 frames at 10 FPS


@pytest.mark.unit
def test_nvr_engine_continuous_recording_and_segmentation(tmp_path: Path) -> None:
    """Test full NVR engine continuous recording with segment splitting."""
    db_file = tmp_path / "nvr_engine.db"
    store = SQLiteStore(db_path=db_file)
    storage_dir = tmp_path / "recordings"

    engine = NVRRecordingEngine(
        storage_dir=storage_dir,
        store=store,
        segment_duration_seconds=0.5,  # Short 0.5s segment for test speed
    )

    cam_id = "cam_east_gate"
    rec_id = engine.start_recording(cam_id, recording_type="continuous")
    assert rec_id.startswith("rec_cam_east_gate_")

    frame = np.ones((240, 320, 3), dtype=np.uint8) * 50
    now = time.time()

    # Ingest frames over 1.2 seconds (should create at least 2 segments with duration 0.5s)
    engine.ingest_frame(cam_id, frame, timestamp_utc=now, fps=10.0)
    engine.ingest_frame(cam_id, frame, timestamp_utc=now + 0.3, fps=10.0)
    engine.ingest_frame(cam_id, frame, timestamp_utc=now + 0.6, fps=10.0)  # Trigger split
    engine.ingest_frame(cam_id, frame, timestamp_utc=now + 1.1, fps=10.0)  # Trigger split

    assert engine.stop_recording(cam_id) is True

    # Verify segments in SQLiteStore
    segments = store.list_recording_segments(rec_id)
    assert len(segments) >= 2
    for s in segments:
        assert Path(s["file_path"]).exists()
        assert s["file_size_bytes"] > 0
        assert len(s["sha256_hash"]) == 64


@pytest.mark.unit
def test_nvr_engine_event_trigger_with_preroll_stitching(tmp_path: Path) -> None:
    """Test that triggering an event stitches the 15s RAM pre-roll buffer to the recording."""
    db_file = tmp_path / "nvr_preroll.db"
    store = SQLiteStore(db_path=db_file)
    storage_dir = tmp_path / "recordings"

    engine = NVRRecordingEngine(
        storage_dir=storage_dir,
        store=store,
        pre_roll_seconds=5.0,
        post_roll_seconds=1.0,
    )

    cam_id = "cam_vault"
    frame = np.ones((240, 320, 3), dtype=np.uint8) * 100
    now = time.time()

    # Ingest frames while NOT recording (populates pre-roll buffer)
    engine.ingest_frame(cam_id, frame, timestamp_utc=now - 2.0)
    engine.ingest_frame(cam_id, frame, timestamp_utc=now - 1.0)
    engine.ingest_frame(cam_id, frame, timestamp_utc=now)

    assert len(engine.pre_roll_buffers[cam_id]) == 3

    # Trigger event
    engine.trigger_event(cam_id, event_id="evt_intrusion_999")

    # Verify pre-roll buffer was flushed and session is active
    assert len(engine.pre_roll_buffers[cam_id]) == 0
    assert cam_id in engine.active_sessions
    session = engine.active_sessions[cam_id]
    assert session.recording_type == "event"
    assert "evt_intrusion_999" in session.event_ids
    assert session.has_event is True

    # Stop recording
    engine.stop_recording(cam_id)
    segments = store.list_recording_segments(session.recording_id)
    assert len(segments) == 1
    assert segments[0]["has_event"] is True
    assert "evt_intrusion_999" in segments[0]["event_ids"]


@pytest.mark.unit
def test_nvr_engine_crash_recovery(tmp_path: Path) -> None:
    """Test that abandoned .part files from unexpected shutdown are recovered."""
    db_file = tmp_path / "nvr_recovery.db"
    store = SQLiteStore(db_path=db_file)
    storage_dir = tmp_path / "recordings"
    storage_dir.mkdir(parents=True, exist_ok=True)

    # Create abandoned .part file
    cam_dir = storage_dir / "cam_dock" / "2026-11-15"
    cam_dir.mkdir(parents=True, exist_ok=True)
    part_file = cam_dir / "rec_cam_dock_abandoned_seg0000.part"
    part_file.write_bytes(b"TEST_ABANDONED_VIDEO_PAYLOAD_CHUNK")

    engine = NVRRecordingEngine(storage_dir=storage_dir, store=store)
    recovered = engine.recover_incomplete_recordings()

    assert len(recovered) == 1
    final_mp4 = Path(recovered[0])
    assert final_mp4.suffix == ".mp4"
    assert final_mp4.exists()
    assert not part_file.exists()

    # Verify database entry created
    recordings = store.list_recordings(camera_id="cam_dock")
    assert len(recordings) == 1
    assert recordings[0]["recording_type"] == "recovered"
    assert recordings[0]["status"] == "finalized"
