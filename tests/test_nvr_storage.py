"""
Unit tests for CAMserv NVR relational storage schemas and query methods in SQLiteStore.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from camserv.storage.sqlite_store import SQLiteStore


@pytest.mark.unit
def test_nvr_recordings_and_segments_crud(tmp_path: Path) -> None:
    """Test full lifecycle of recording sessions and segmented chunks."""
    db_file = tmp_path / "nvr_test.db"
    store = SQLiteStore(db_path=db_file)

    # 1. Upsert recording session
    rec_data = {
        "recording_id": "rec_20261115_001",
        "camera_id": "cam_gate",
        "start_time_utc": "2026-11-15T20:00:00Z",
        "recording_type": "continuous",
        "status": "recording",
        "storage_tier": "operational",
        "total_size_bytes": 0,
        "metadata": {"fps": 30, "codec": "h264"},
    }
    store.upsert_recording(rec_data)

    retrieved = store.get_recording("rec_20261115_001")
    assert retrieved is not None
    assert retrieved["camera_id"] == "cam_gate"
    assert retrieved["status"] == "recording"
    assert retrieved["metadata"]["fps"] == 30

    # 2. Store multiple segments
    seg1 = {
        "segment_id": "seg_001",
        "recording_id": "rec_20261115_001",
        "camera_id": "cam_gate",
        "segment_index": 0,
        "start_time_utc": "2026-11-15T20:00:00Z",
        "end_time_utc": "2026-11-15T20:01:00Z",
        "duration_seconds": 60.0,
        "file_path": "/var/camserv/recordings/cam_gate/20261115_200000.mp4",
        "file_size_bytes": 10485760,
        "sha256_hash": "a" * 64,
        "has_motion": False,
        "has_event": False,
    }
    seg2 = {
        "segment_id": "seg_002",
        "recording_id": "rec_20261115_001",
        "camera_id": "cam_gate",
        "segment_index": 1,
        "start_time_utc": "2026-11-15T20:01:00Z",
        "end_time_utc": "2026-11-15T20:02:00Z",
        "duration_seconds": 60.0,
        "file_path": "/var/camserv/recordings/cam_gate/20261115_200100.mp4",
        "file_size_bytes": 12582912,
        "sha256_hash": "b" * 64,
        "has_motion": True,
        "has_event": True,
        "event_ids": ["evt_123"],
    }
    store.store_recording_segment(seg1)
    store.store_recording_segment(seg2)

    segments = store.list_recording_segments("rec_20261115_001")
    assert len(segments) == 2
    assert segments[0]["segment_index"] == 0
    assert segments[1]["has_motion"] is True
    assert "evt_123" in segments[1]["event_ids"]

    # 3. Query segments by time range
    range_segs = store.query_segments_by_time_range(
        camera_id="cam_gate",
        start_time_utc="2026-11-15T20:00:30Z",
        end_time_utc="2026-11-15T20:01:30Z",
    )
    assert len(range_segs) == 2

    # 4. Finalize recording session
    assert store.finalize_recording(
        recording_id="rec_20261115_001",
        end_time_utc="2026-11-15T20:02:00Z",
        total_size_bytes=23068672,
    ) is True

    final_rec = store.get_recording("rec_20261115_001")
    assert final_rec["status"] == "finalized"
    assert final_rec["total_size_bytes"] == 23068672


@pytest.mark.unit
def test_nvr_schedules_ptz_groups_crud(tmp_path: Path) -> None:
    """Test schedules, PTZ presets, and camera groups relational tables."""
    db_file = tmp_path / "nvr_aux_test.db"
    store = SQLiteStore(db_path=db_file)

    # 1. Schedules
    store.upsert_recording_schedule({
        "schedule_id": "sched_01",
        "camera_id": "cam_lobby",
        "day_of_week": 1,  # Tuesday
        "start_time": "08:00",
        "end_time": "18:00",
        "mode": "continuous",
        "is_active": True,
    })
    schedules = store.list_recording_schedules("cam_lobby")
    assert len(schedules) == 1
    assert schedules[0]["mode"] == "continuous"
    assert store.delete_recording_schedule("sched_01") is True
    assert len(store.list_recording_schedules("cam_lobby")) == 0

    # 2. PTZ Presets
    store.upsert_ptz_preset({
        "preset_id": "preset_gate",
        "camera_id": "cam_ptz_01",
        "name": "Gate Closeup",
        "pan": 120.5,
        "tilt": -15.2,
        "zoom": 3.0,
        "token": "token_01",
    })
    presets = store.list_ptz_presets("cam_ptz_01")
    assert len(presets) == 1
    assert presets[0]["name"] == "Gate Closeup"
    assert presets[0]["pan"] == 120.5
    assert store.delete_ptz_preset("preset_gate") is True
    assert len(store.list_ptz_presets("cam_ptz_01")) == 0

    # 3. Camera Groups
    store.upsert_camera_group({
        "group_id": "grp_warehouse",
        "name": "Warehouse North",
        "description": "Storage area cameras",
        "camera_ids": ["cam_w1", "cam_w2"],
        "site_id": "site_logistics",
        "tags": ["storage", "hazardous"],
    })
    grp = store.get_camera_group("grp_warehouse")
    assert grp is not None
    assert grp["name"] == "Warehouse North"
    assert "cam_w1" in grp["camera_ids"]
    assert "hazardous" in grp["tags"]

    groups = store.list_camera_groups(site_id="site_logistics")
    assert len(groups) == 1
    assert store.delete_camera_group("grp_warehouse") is True
    assert store.get_camera_group("grp_warehouse") is None
