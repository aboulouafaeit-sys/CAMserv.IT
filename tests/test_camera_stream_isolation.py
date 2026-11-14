"""
tests.test_camera_stream_isolation
===================================

Integration tests for CameraStream process isolation via shared memory ring buffer.
"""

import asyncio
import pytest

from camserv.acquisition.camera import CameraManager, CameraStatus, CameraStream, StreamConfig


@pytest.mark.asyncio
async def test_camera_stream_with_process_isolation_streaming() -> None:
    """Verify CameraStream with process isolation spawns child worker and yields Frames."""
    config = StreamConfig(
        camera_id="cam-isolated-01",
        source_url="synthetic",
        target_fps=20.0,
        frame_width=640,
        frame_height=480,
        use_process_isolation=True,
        num_shm_slots=3,
    )
    stream = CameraStream(config)
    try:
        await stream.start()
        assert stream.status == CameraStatus.STREAMING
        assert stream.is_alive is True

        frames = []
        async for frame in stream:
            frames.append(frame)
            if len(frames) >= 3:
                break

        assert len(frames) == 3
        for f in frames:
            assert f.camera_id == "cam-isolated-01"
            assert f.image.shape == (480, 640, 3)
            assert f.metadata.get("process_isolated") is True
            assert "shm_name" in f.metadata
    finally:
        await stream.stop()
        assert stream.status == CameraStatus.STOPPED


@pytest.mark.asyncio
async def test_camera_manager_with_isolated_streams() -> None:
    """Verify CameraManager coordinating multiple isolated streams."""
    manager = CameraManager()
    cfg1 = StreamConfig(
        camera_id="cam-mgr-iso-01",
        source_url="synthetic",
        target_fps=25.0,
        frame_width=320,
        frame_height=240,
        use_process_isolation=True,
        num_shm_slots=3,
    )
    stream1 = manager.register_camera(cfg1)
    try:
        await manager.start_all()
        assert stream1.is_alive

        # Read 1 frame
        frame = await stream1.__anext__()
        assert frame.image.shape == (240, 320, 3)
        assert frame.metadata.get("process_isolated") is True

        health = manager.health_report()
        assert "cam-mgr-iso-01" in health
        assert health["cam-mgr-iso-01"].status == CameraStatus.STREAMING
    finally:
        await manager.stop_all()
        assert not stream1.is_alive
