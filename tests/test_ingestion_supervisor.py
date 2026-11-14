"""Tests for Process-Isolated Video Ingestion & Shared Memory Ring Buffers (Phase 1B & 1C)."""
from __future__ import annotations

import time
import numpy as np
import pytest

from camserv.acquisition.ingestion_manager import IngestionManager
from camserv.acquisition.shared_memory import SharedMemoryRingBuffer
from camserv.acquisition.supervisor import CameraWorkerSupervisor, WorkerStatus


@pytest.mark.unit
def test_shared_memory_ring_buffer_read_write() -> None:
    """Verify writing and reading raw frames through the shared memory ring buffer."""
    buf_name = "test_shm_rw_slot"
    ring = SharedMemoryRingBuffer(name=buf_name, num_slots=3, max_width=640, max_height=480, create=True)
    try:
        # Generate dummy 640x480 frame
        img1 = np.ones((480, 640, 3), dtype=np.uint8) * 100
        t1 = time.time()
        slot_idx = ring.write_frame(img1, timestamp=t1, sequence=1)
        assert slot_idx == 1

        # Read back latest frame
        read_res = ring.read_latest_frame()
        assert read_res is not None
        read_img, read_ts, read_seq = read_res
        assert read_seq == 1
        assert abs(read_ts - t1) < 1e-4
        assert np.array_equal(read_img, img1)

        # Subsequent immediate read should yield None (no new frame)
        assert ring.read_latest_frame() is None
    finally:
        ring.unlink()


@pytest.mark.unit
def test_shared_memory_drop_oldest_overrun() -> None:
    """Verify bounded ring buffer overwrites oldest slots without corrupting data."""
    buf_name = "test_shm_overrun"
    ring = SharedMemoryRingBuffer(name=buf_name, num_slots=3, max_width=320, max_height=240, create=True)
    try:
        # Write 5 frames to 3-slot buffer (overrunning slots 0 and 1)
        for seq in range(1, 6):
            frame = np.ones((240, 320, 3), dtype=np.uint8) * seq
            ring.write_frame(frame, timestamp=time.time(), sequence=seq)

        # Reading latest frame should yield sequence 5
        read_res = ring.read_latest_frame()
        assert read_res is not None
        read_img, _, read_seq = read_res
        assert read_seq == 5
        assert read_img[0, 0, 0] == 5
    finally:
        ring.unlink()


@pytest.mark.unit
def test_camera_worker_supervisor_lifecycle() -> None:
    """Verify child worker process spawning, frame generation, and graceful termination."""
    sup = CameraWorkerSupervisor(
        camera_id="cam-super-01",
        source_url="synthetic",
        target_fps=20.0,
        num_slots=3,
        max_width=640,
        max_height=480,
    )
    try:
        sup.start()
        assert sup.status == WorkerStatus.STREAMING

        # Allow child process to write frames
        time.sleep(0.3)
        res = sup.read_frame()
        assert res is not None
        img, ts, seq = res
        assert seq > 0
        assert img.shape == (480, 640, 3)
    finally:
        sup.stop()
        assert sup.status == WorkerStatus.STOPPED


@pytest.mark.unit
def test_supervisor_crash_recovery() -> None:
    """Verify supervisor detects terminated child worker and respawns it (< 500ms)."""
    sup = CameraWorkerSupervisor(
        camera_id="cam-crash-01",
        source_url="synthetic",
        target_fps=20.0,
        num_slots=3,
        max_width=640,
        max_height=480,
    )
    try:
        sup.start()
        time.sleep(0.2)
        assert sup.is_alive

        # Simulate abrupt worker crash (SIGKILL / terminate)
        if sup._process is not None:
            sup._process.terminate()
            sup._process.join(timeout=0.2)

        # Process should be dead
        assert not sup._process.is_alive()

        # check_health_and_recover should detect crash and respawn in < 500ms
        t0 = time.monotonic()
        recovered = sup.check_health_and_recover()
        elapsed = time.monotonic() - t0

        assert recovered is True
        assert elapsed < 0.5, f"Recovery took {elapsed:.3f}s, must be < 500ms"
        assert sup.restart_count == 1
        assert sup.is_alive
    finally:
        sup.stop()


@pytest.mark.unit
def test_ingestion_manager_multi_camera() -> None:
    """Verify IngestionManager coordinates multiple camera streams and reports telemetry."""
    mgr = IngestionManager()
    try:
        mgr.register_camera("cam-01", "synthetic", target_fps=15.0, num_slots=3, max_width=640, max_height=480)
        mgr.register_camera("cam-02", "synthetic", target_fps=15.0, num_slots=3, max_width=640, max_height=480)
        mgr.start_all()

        time.sleep(0.2)
        telemetry = mgr.get_telemetry()
        assert "cam-01" in telemetry
        assert "cam-02" in telemetry
        assert telemetry["cam-01"]["status"] == "streaming"
        assert telemetry["cam-02"]["status"] == "streaming"
    finally:
        mgr.stop_all()
