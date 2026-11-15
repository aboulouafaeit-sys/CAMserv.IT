"""
Unit tests for CAMserv NVR streaming gateway, ONVIF Profile S PTZ controller,
and synchronized playback timeline engine.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import numpy as np
import pytest

from camserv.nvr.playback import PlaybackTimelineEngine
from camserv.nvr.ptz import PTZCapabilities, PTZController, PTZUnsupportedError, PTZVector
from camserv.nvr.streaming import StreamingGateway
from camserv.pipeline.interfaces import Event, EventSeverity
from camserv.storage.sqlite_store import SQLiteStore


@pytest.mark.unit
def test_ptz_controller_continuous_move_and_capabilities(tmp_path: Path) -> None:
    """Test PTZ controller movement and capability enforcement."""
    db_file = tmp_path / "ptz_test.db"
    store = SQLiteStore(db_path=db_file)
    controller = PTZController(store=store)

    # 1. Register PTZ-capable camera
    controller.register_camera_capabilities("cam_ptz_dome", is_ptz=True)
    caps = controller.get_capabilities("cam_ptz_dome")
    assert caps.is_ptz_capable is True
    assert caps.supports_continuous_move is True

    # Initial position
    pos0 = controller.get_position("cam_ptz_dome")
    assert pos0 == (0.0, 0.0, 1.0)

    # Continuous move (pan right, tilt up, zoom in)
    controller.continuous_move("cam_ptz_dome", PTZVector(pan=0.5, tilt=0.3, zoom=0.2))
    pos1 = controller.get_position("cam_ptz_dome")
    assert pos1[0] > pos0[0]  # Pan moved right
    assert pos1[1] > pos0[1]  # Tilt moved up
    assert pos1[2] > pos0[2]  # Zoom increased

    # Stop motion
    controller.stop("cam_ptz_dome")

    # 2. Preset Save and Recall
    preset = controller.save_preset("cam_ptz_dome", name="Front Gate Zoom")
    assert preset.name == "Front Gate Zoom"
    assert preset.camera_id == "cam_ptz_dome"

    presets = controller.list_presets("cam_ptz_dome")
    assert len(presets) == 1
    assert presets[0].name == "Front Gate Zoom"

    # Move camera away and recall preset
    controller.relative_move("cam_ptz_dome", pan_delta=-20.0, tilt_delta=-10.0, zoom_delta=0.0)
    assert controller.goto_preset("cam_ptz_dome", "Front Gate Zoom") is True
    assert controller.get_position("cam_ptz_dome") == (preset.pan, preset.tilt, preset.zoom)

    # 3. Fixed camera refusal invariant
    controller.register_camera_capabilities("cam_fixed_bullet", is_ptz=False)
    fixed_caps = controller.get_capabilities("cam_fixed_bullet")
    assert fixed_caps.is_ptz_capable is False

    with pytest.raises(PTZUnsupportedError, match="unsupported"):
        controller.continuous_move("cam_fixed_bullet", PTZVector(pan=1.0))

    with pytest.raises(PTZUnsupportedError, match="unsupported"):
        controller.save_preset("cam_fixed_bullet", name="Illegal Preset")


@pytest.mark.unit
def test_streaming_gateway_mjpeg_and_webrtc() -> None:
    """Test multi-protocol streaming gateway MJPEG frames, WebRTC negotiation, and HLS playlist."""
    gateway = StreamingGateway(privacy_pipeline=None)
    cam_id = "cam_stream_01"

    # Update frame
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[100:200, 100:200] = [0, 255, 0]  # Green box
    gateway.update_camera_frame(cam_id, frame)

    latest = gateway.get_latest_frame(cam_id)
    assert latest is not None
    assert latest.shape == (480, 640, 3)

    # Test WebRTC Session Creation and SDP Negotiation
    rtc_session = gateway.create_webrtc_session(cam_id)
    assert rtc_session.camera_id == cam_id
    assert rtc_session.state == "new"

    client_offer = "v=0\r\no=- 12345 2 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n"
    answer_sdp = gateway.handle_webrtc_offer(rtc_session.session_id, client_offer)
    assert "m=video" in answer_sdp
    assert "a=sendonly" in answer_sdp
    assert rtc_session.state == "established"

    # Test HLS Playlist Generation
    playlist = gateway.generate_hls_playlist(cam_id)
    assert "#EXTM3U" in playlist
    assert "#EXT-X-TARGETDURATION:2" in playlist

    # Test MJPEG async stream generation
    async def _test_mjpeg() -> None:
        generator = gateway.generate_mjpeg_stream(cam_id, target_fps=30.0)
        chunk = await anext(generator)
        assert b"--frame" in chunk
        assert b"Content-Type: image/jpeg" in chunk
        await generator.aclose()

    asyncio.run(_test_mjpeg())


@pytest.mark.unit
def test_playback_timeline_engine_and_clipped_export(tmp_path: Path) -> None:
    """Test timeline assembly, multi-camera aggregation, and clipped video range export."""
    db_file = tmp_path / "playback_test.db"
    store = SQLiteStore(db_path=db_file)
    storage_dir = tmp_path / "recordings"
    storage_dir.mkdir(parents=True, exist_ok=True)

    # 1. Store synthetic segments in SQLiteStore
    seg1_file = storage_dir / "seg1.mp4"
    seg2_file = storage_dir / "seg2.mp4"
    seg1_file.write_bytes(b"SEGMENT_1_CONTENT_12345")
    seg2_file.write_bytes(b"SEGMENT_2_CONTENT_67890")

    store.upsert_recording({
        "recording_id": "rec_001",
        "camera_id": "cam_hallway",
        "start_time_utc": "2026-11-15T10:00:00Z",
        "status": "finalized",
        "recording_type": "continuous",
        "storage_tier": "operational",
    })

    store.store_recording_segment({
        "segment_id": "seg_001",
        "recording_id": "rec_001",
        "camera_id": "cam_hallway",
        "segment_index": 0,
        "start_time_utc": "2026-11-15T10:00:00Z",
        "end_time_utc": "2026-11-15T10:01:00Z",
        "duration_seconds": 60.0,
        "file_path": str(seg1_file),
        "file_size_bytes": seg1_file.stat().st_size,
        "sha256_hash": "1" * 64,
        "has_motion": False,
        "has_event": False,
    })

    store.store_recording_segment({
        "segment_id": "seg_002",
        "recording_id": "rec_001",
        "camera_id": "cam_hallway",
        "segment_index": 1,
        "start_time_utc": "2026-11-15T10:01:00Z",
        "end_time_utc": "2026-11-15T10:02:00Z",
        "duration_seconds": 60.0,
        "file_path": str(seg2_file),
        "file_size_bytes": seg2_file.stat().st_size,
        "sha256_hash": "2" * 64,
        "has_motion": True,
        "has_event": True,
        "event_ids": ["evt_motion_01"],
    })

    # Store event for marker verification
    store.store_event(
        Event(
            event_id="evt_motion_01",
            camera_id="cam_hallway",
            timestamp="2026-11-15T10:01:30Z",
            event_type="person_motion",
            severity=EventSeverity.HIGH,
            confidence=0.89,
            description="Motion detected in hallway",
            requires_verification=True,
        )
    )

    playback = PlaybackTimelineEngine(store=store, storage_dir=storage_dir)

    # 2. Query timeline spans
    spans = playback.get_camera_timeline(
        camera_id="cam_hallway",
        start_time_utc="2026-11-15T10:00:00Z",
        end_time_utc="2026-11-15T10:02:00Z",
    )
    assert len(spans) == 2
    assert spans[0].segment_ids == ["seg_001"]
    assert spans[1].segment_ids == ["seg_002"]
    assert spans[1].has_event is True
    assert len(spans[1].markers) == 1
    assert spans[1].markers[0].event_id == "evt_motion_01"

    # Multi-camera query
    multi = playback.get_multi_camera_timeline(
        camera_ids=["cam_hallway"],
        start_time_utc="2026-11-15T10:00:00Z",
        end_time_utc="2026-11-15T10:02:00Z",
    )
    assert "cam_hallway" in multi
    assert len(multi["cam_hallway"]) == 2

    # 3. Interactive Playback Session
    session = playback.create_playback_session(
        session_id="session_01",
        camera_ids=["cam_hallway"],
        start_position_utc="2026-11-15T10:00:30Z",
    )
    assert session.speed == 1.0
    session.set_speed(4.0)
    assert session.speed == 4.0
    assert session.toggle_pause() is True
    assert session.is_paused is True

    # 4. Clipped Video Export
    export_file = tmp_path / "exports" / "clipped_evidence.mp4"
    manifest = playback.export_clipped_range(
        camera_id="cam_hallway",
        start_time_utc="2026-11-15T10:00:00Z",
        end_time_utc="2026-11-15T10:02:00Z",
        output_path=export_file,
    )
    assert export_file.exists()
    assert export_file.stat().st_size == (seg1_file.stat().st_size + seg2_file.stat().st_size)
    assert manifest["file_size_bytes"] == export_file.stat().st_size
    assert len(manifest["sha256_hash"]) == 64
    assert len(manifest["segments_included"]) == 2
