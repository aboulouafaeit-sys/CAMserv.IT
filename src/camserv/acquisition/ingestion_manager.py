"""High-Level Video Ingestion Manager & Multi-Camera Coordinator (Phase 1B & 1C).

Manages:
* Dynamic registration and lifecycle of supervised camera workers.
* Zero-copy shared memory frame dispatch to downstream consumers.
* System-wide ingestion telemetry, dropped frame metrics, and crash restarts.
* Graceful multi-camera startup and teardown.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict

import structlog

from camserv.acquisition.supervisor import CameraWorkerSupervisor, WorkerStatus
from camserv.pipeline.interfaces import Frame

logger = structlog.get_logger(__name__)


class IngestionManager:
    """Coordinates supervised camera ingestion processes across all configured streams."""

    def __init__(self) -> None:
        self._supervisors: dict[str, CameraWorkerSupervisor] = {}
        self._running = False

    @property
    def active_cameras(self) -> list[str]:
        """List registered camera IDs."""
        return list(self._supervisors.keys())

    def register_camera(
        self,
        camera_id: str,
        source_url: str,
        target_fps: float = 30.0,
        num_slots: int = 5,
        max_width: int = 1920,
        max_height: int = 1080,
    ) -> CameraWorkerSupervisor:
        """Register a new camera source and initialize its worker supervisor."""
        if camera_id in self._supervisors:
            self._supervisors[camera_id].stop()

        sup = CameraWorkerSupervisor(
            camera_id=camera_id,
            source_url=source_url,
            target_fps=target_fps,
            num_slots=num_slots,
            max_width=max_width,
            max_height=max_height,
        )
        self._supervisors[camera_id] = sup
        if self._running:
            sup.start()
        return sup

    def unregister_camera(self, camera_id: str) -> None:
        """Stop and remove a camera ingestion supervisor."""
        if camera_id in self._supervisors:
            self._supervisors[camera_id].stop()
            del self._supervisors[camera_id]

    def start_all(self) -> None:
        """Start all registered camera supervisors."""
        self._running = True
        for sup in self._supervisors.values():
            sup.start()
        logger.info("ingestion_manager.all_workers_started", count=len(self._supervisors))

    def stop_all(self) -> None:
        """Stop all camera supervisors and release shared memory resources."""
        self._running = False
        for sup in self._supervisors.values():
            sup.stop()
        self._supervisors.clear()
        logger.info("ingestion_manager.all_workers_stopped")

    async def stream_frames(self, camera_id: str) -> AsyncIterator[Frame]:
        """Async iterator yielding Frame objects from a camera's shared memory ring buffer."""
        sup = self._supervisors.get(camera_id)
        if sup is None:
            raise KeyError(f"Camera '{camera_id}' is not registered in IngestionManager")

        frame_interval = 1.0 / sup.target_fps if sup.target_fps > 0 else 0.033

        while self._running:
            res = sup.read_frame()
            if res is not None:
                img, ts_epoch, seq = res
                now_dt = datetime.fromtimestamp(ts_epoch, tz=timezone.utc)
                yield Frame(
                    image=img,
                    camera_id=camera_id,
                    timestamp=now_dt,
                    frame_id=seq,
                    metadata={"source_url": sup.source_url, "ipc": "shared_memory_ring"},
                )
            await asyncio.sleep(frame_interval * 0.5)

    def get_telemetry(self) -> dict[str, Any]:
        """Collect aggregated ingestion telemetry across all camera supervisors."""
        report: dict[str, Any] = {}
        for cam_id, sup in self._supervisors.items():
            report[cam_id] = {
                "status": sup.status.value,
                "is_alive": sup.is_alive,
                "restart_count": sup.restart_count,
                "target_fps": sup.target_fps,
                "shm_name": sup.shm_name,
            }
        return report
