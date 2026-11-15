"""
tests.test_central_enterprise_sync
===================================

Phase 8 automated tests:
- Edge appliance recording manifest packaging and WAN data minimization.
- Store-and-forward offline buffer queueing and flush upon network reconnection.
- Central recording federation and multi-site search indexing.
- Fleet-wide camera discovery across distributed edge appliances.
"""

from __future__ import annotations

from pathlib import Path
import time
import pytest

from camserv.central.comm import OfflineMessageBuffer
from camserv.central.sync import (
    CentralSyncEngine,
    EdgeSyncClient,
    FleetCameraInfo,
    FleetRecordingRecord,
)
from camserv.storage.sqlite_store import SQLiteStore


@pytest.fixture
def temp_store(tmp_path: Path) -> SQLiteStore:
    db_path = tmp_path / "edge_sync.db"
    return SQLiteStore(str(db_path))


def test_edge_sync_package_recording_manifest(temp_store: SQLiteStore) -> None:
    """Test packaging an edge recording manifest strictly adhering to WAN data minimization."""
    # Seed recording
    rec_id = "rec_edge_101"
    cam_id = "cam_alpha"
    temp_store.store_recording({
        "recording_id": rec_id,
        "camera_id": cam_id,
        "start_time_utc": "2026-11-15T09:00:00Z",
        "end_time_utc": "2026-11-15T09:10:00Z",
        "recording_type": "continuous",
        "status": "completed",
        "storage_tier": "operational_fast",
        "total_size_bytes": 5000000,
        "metadata": {"judicial_hold": True, "judicial_hold_reason": "Auditor verification"},
    })
    temp_store.store_recording_segment({
        "segment_id": "seg_edge_01",
        "recording_id": rec_id,
        "camera_id": cam_id,
        "segment_index": 0,
        "start_time_utc": "2026-11-15T09:00:00Z",
        "end_time_utc": "2026-11-15T09:10:00Z",
        "duration_seconds": 600.0,
        "file_path": "data/recordings/cam_alpha_01.mp4",
        "file_size_bytes": 5000000,
        "sha256_hash": "a1b2c3d4e5f60718293a",
        "has_event": True,
        "event_ids": ["EV-999"],
    })

    client = EdgeSyncClient(
        appliance_id="appliance_berlin_01",
        site_id="site_berlin",
        store=temp_store,
    )

    envelope = client.package_recording_manifest(rec_id)
    assert envelope.sender_id == "appliance_berlin_01"
    assert envelope.recipient_id == "central"
    assert envelope.signature is not None
    assert envelope.verify_signature(client.public_key) is True

    # Validate WAN minimization: manifest contains hashes and metadata, zero raw video bytes
    data = envelope.payload_data
    assert data["recording_id"] == rec_id
    assert data["camera_id"] == cam_id
    assert data["segment_count"] == 1
    assert data["segments"][0]["sha256"] == "a1b2c3d4e5f60718293a"
    assert data["judicial_hold"] is True
    assert "video_bytes" not in data
    assert "frame_data" not in data


def test_edge_sync_offline_buffer_and_reconnection(temp_store: SQLiteStore) -> None:
    """Test offline store-and-forward queueing and flushing upon WAN link recovery."""
    client = EdgeSyncClient(
        appliance_id="appliance_paris_02",
        site_id="site_paris",
        store=temp_store,
    )

    # Seed 3 recordings
    for i in range(1, 4):
        rec_id = f"rec_offline_{i}"
        temp_store.store_recording({
            "recording_id": rec_id,
            "camera_id": "cam_lobby",
            "start_time_utc": f"2026-11-15T1{i}:00:00Z",
            "end_time_utc": f"2026-11-15T1{i}:10:00Z",
            "recording_type": "continuous",
            "status": "completed",
            "storage_tier": "operational_fast",
            "total_size_bytes": 1000 * i,
        })
        client.queue_recording_for_sync(rec_id)

    assert client.buffer.get_pending_count() == 3

    # WAN is currently down: dispatch fails
    flushed_offline = client.flush_offline_queue(lambda env: False)
    assert flushed_offline == 0
    assert client.buffer.get_pending_count() == 3

    # WAN is restored: dispatch succeeds
    dispatched_envelopes = []

    def mock_central_receiver(envelope):
        dispatched_envelopes.append(envelope)
        return True

    flushed_online = client.flush_offline_queue(mock_central_receiver)
    assert flushed_online == 3
    assert client.buffer.get_pending_count() == 0
    assert len(dispatched_envelopes) == 3
    assert client.get_status()["total_synced_recordings"] == 3


def test_central_sync_ingest_and_fleet_queries(temp_store: SQLiteStore) -> None:
    """Test central sync engine indexing multi-site appliance data and answering queries."""
    central = CentralSyncEngine()

    # 1. Edge Client Berlin
    client_berlin = EdgeSyncClient("app_de_01", "site_berlin", temp_store)
    disc_berlin = client_berlin.publish_camera_discovery([
        {"id": "cam_berlin_gate", "name": "Berlin Gate", "enabled": True, "fps": 25.0, "width": 1920, "height": 1080},
    ])
    central.ingest_sync_envelope(disc_berlin)

    # 2. Edge Client Paris
    client_paris = EdgeSyncClient("app_fr_01", "site_paris", temp_store)
    disc_paris = client_paris.publish_camera_discovery([
        {"id": "cam_paris_hq", "name": "Paris HQ", "enabled": True, "fps": 30.0, "width": 3840, "height": 2160},
    ])
    central.ingest_sync_envelope(disc_paris)

    # Verify camera discovery across fleet
    all_cams = central.discover_fleet_cameras()
    assert len(all_cams) == 2
    paris_cams = central.discover_fleet_cameras(site_id="site_paris")
    assert len(paris_cams) == 1
    assert paris_cams[0]["camera_id"] == "cam_paris_hq"

    # 3. Ingest recording manifests from both appliances
    temp_store.store_recording({
        "recording_id": "rec_de_001",
        "camera_id": "cam_berlin_gate",
        "start_time_utc": "2026-11-15T08:00:00Z",
        "end_time_utc": "2026-11-15T08:30:00Z",
        "recording_type": "continuous",
        "status": "completed",
        "storage_tier": "operational",
        "total_size_bytes": 1024 * 1024 * 100,
        "metadata": {"judicial_hold": True},
    })
    temp_store.store_recording_segment({
        "segment_id": "seg_de_001",
        "recording_id": "rec_de_001",
        "camera_id": "cam_berlin_gate",
        "segment_index": 0,
        "start_time_utc": "2026-11-15T08:00:00Z",
        "end_time_utc": "2026-11-15T08:30:00Z",
        "duration_seconds": 1800.0,
        "file_path": "path_de.mp4",
        "file_size_bytes": 1024 * 1024 * 100,
        "sha256_hash": "sha_de",
        "has_event": False,
        "event_ids": [],
    })
    env_de = client_berlin.package_recording_manifest("rec_de_001")
    central.ingest_sync_envelope(env_de)

    temp_store.store_recording({
        "recording_id": "rec_fr_001",
        "camera_id": "cam_paris_hq",
        "start_time_utc": "2026-11-15T08:15:00Z",
        "end_time_utc": "2026-11-15T08:45:00Z",
        "recording_type": "event",
        "status": "completed",
        "storage_tier": "operational",
        "total_size_bytes": 1024 * 1024 * 50,
        "metadata": {"judicial_hold": False},
    })
    temp_store.store_recording_segment({
        "segment_id": "seg_fr_001",
        "recording_id": "rec_fr_001",
        "camera_id": "cam_paris_hq",
        "segment_index": 0,
        "start_time_utc": "2026-11-15T08:15:00Z",
        "end_time_utc": "2026-11-15T08:45:00Z",
        "duration_seconds": 1800.0,
        "file_path": "path_fr.mp4",
        "file_size_bytes": 1024 * 1024 * 50,
        "sha256_hash": "sha_fr",
        "has_event": True,
        "event_ids": ["EV-ALERT-1"],
    })
    env_fr = client_paris.package_recording_manifest("rec_fr_001")
    central.ingest_sync_envelope(env_fr)

    # Query fleet recordings
    all_recs = central.query_fleet_recordings()
    assert len(all_recs) == 2

    # Filter by site
    de_recs = central.query_fleet_recordings(site_id="site_berlin")
    assert len(de_recs) == 1
    assert de_recs[0]["recording_id"] == "rec_de_001"

    # Filter by judicial hold
    held_recs = central.query_fleet_recordings(judicial_hold=True)
    assert len(held_recs) == 1
    assert held_recs[0]["recording_id"] == "rec_de_001"

    # Filter by event
    event_recs = central.query_fleet_recordings(has_event=True)
    assert len(event_recs) == 1
    assert event_recs[0]["recording_id"] == "rec_fr_001"

    # Query fleet timeline for a camera
    timeline = central.query_fleet_timeline(
        camera_id="cam_berlin_gate",
        start_time_utc="2026-11-15T08:00:00Z",
        end_time_utc="2026-11-15T09:00:00Z",
    )
    assert timeline["camera_id"] == "cam_berlin_gate"
    assert timeline["appliance_id"] == "app_de_01"
    assert timeline["site_id"] == "site_berlin"
    assert timeline["segment_count"] == 1

    # Check fleet stats
    stats = central.get_fleet_stats()
    assert stats["sites_count"] == 2
    assert stats["appliances_count"] == 2
    assert stats["cameras_count"] == 2
    assert stats["recordings_count"] == 2
    assert stats["judicial_holds_count"] == 1
