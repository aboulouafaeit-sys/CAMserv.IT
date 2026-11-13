"""
camserv.acquisition.camera
==========================

Camera management and streaming for the CAMserv platform.

Provides:
- :class:`CameraStream`: An async generator reading from RTSP/HTTP/file sources
  via OpenCV with automatic exponential-backoff reconnection, frame sequencing,
  and health monitoring.
- :class:`CameraManager`: High-level manager coordinating multiple concurrent
  camera streams.
- :class:`CameraHealth`: Dataclass capturing real-time operational status.
"""

from __future__ import annotations

import asyncio
import enum
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator

try:
    import numpy as np
except ImportError:
    class _MockNDArray:
        shape: tuple[int, ...] = (480, 640, 3)
        dtype = "uint8"
        nbytes: int = 480 * 640 * 3
    class _MockNumpy:
        ndarray = _MockNDArray
        uint8 = "uint8"
        def zeros(self, shape: tuple[int, ...], dtype: Any = None) -> Any:
            class _ZeroArray(_MockNDArray):
                def __init__(self, s: tuple[int, ...]):
                    self.shape = s
                def __setitem__(self, key: Any, val: Any) -> None:
                    pass
            return _ZeroArray(shape)
    np = _MockNumpy()  # type: ignore[assignment]

try:
    import structlog
except ImportError:
    import logging
    class _FallbackLogger:
        def __init__(self, name: str = "camserv") -> None:
            self._logger = logging.getLogger(name)
        def bind(self, **kwargs: Any) -> _FallbackLogger:
            return self
        def info(self, event: str, **kwargs: Any) -> None:
            self._logger.info(f"{event} {kwargs}" if kwargs else event)
        def warning(self, event: str, **kwargs: Any) -> None:
            self._logger.warning(f"{event} {kwargs}" if kwargs else event)
        def error(self, event: str, **kwargs: Any) -> None:
            self._logger.error(f"{event} {kwargs}" if kwargs else event)
        def debug(self, event: str, **kwargs: Any) -> None:
            self._logger.debug(f"{event} {kwargs}" if kwargs else event)
        def critical(self, event: str, **kwargs: Any) -> None:
            self._logger.critical(f"{event} {kwargs}" if kwargs else event)
    class _MockStructlog:
        @staticmethod
        def get_logger(name: str | None = None) -> _FallbackLogger:
            return _FallbackLogger(name or "camserv")
    structlog = _MockStructlog()  # type: ignore[assignment]


from camserv.pipeline.interfaces import Frame, FrameSource

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Exceptions & Status Enums
# ---------------------------------------------------------------------------

class AcquisitionError(Exception):
    """Base exception for camera acquisition failures."""


class CameraConnectionError(AcquisitionError):
    """Raised when connecting or reconnecting to a camera source fails."""


class CameraStatus(enum.Enum):
    """Lifecycle status of a camera stream."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    STREAMING = "streaming"
    RECONNECTING = "reconnecting"
    ERROR = "error"
    STOPPED = "stopped"


# ---------------------------------------------------------------------------
# Configuration & Health Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class StreamConfig:
    """Configuration settings for a single camera source."""

    camera_id: str
    source_url: str  # RTSP/HTTP URL, local file path, or 'synthetic'
    target_fps: float = 30.0
    reconnect_initial_delay: float = 1.0
    reconnect_max_delay: float = 30.0
    reconnect_backoff_factor: float = 2.0
    max_reconnect_attempts: int = 0  # 0 means retry indefinitely
    frame_width: int | None = None
    frame_height: int | None = None
    loop_video_file: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CameraHealth:
    """Operational telemetry snapshot for a camera stream."""

    camera_id: str
    status: CameraStatus
    current_fps: float
    total_frames_read: int
    total_frames_dropped: int
    reconnect_count: int
    last_frame_timestamp: datetime | None
    last_error: str | None
    uptime_seconds: float


# ---------------------------------------------------------------------------
# CameraStream Implementation
# ---------------------------------------------------------------------------

class CameraStream:
    """Async frame generator for a single video source with auto-reconnect.

    Satisfies the :class:`~camserv.pipeline.interfaces.FrameSource` protocol.
    Reads frames via OpenCV in a background thread to prevent blocking the
    asyncio event loop.
    """

    def __init__(self, config: StreamConfig) -> None:
        self.config = config
        self._camera_id = config.camera_id
        self._status = CameraStatus.DISCONNECTED

        self._cap: Any = None
        self._frame_seq: int = 0
        self._total_dropped: int = 0
        self._reconnect_count: int = 0
        self._last_frame_time: datetime | None = None
        self._last_error: str | None = None

        self._start_time: float = 0.0
        self._fps_window: list[float] = []
        self._fps_window_size: int = 30

        self._running = False
        self._stop_event = asyncio.Event()
        self._frame_interval = 1.0 / config.target_fps if config.target_fps > 0 else 0.033

        self._log = logger.bind(camera_id=self._camera_id, source=config.source_url)

    # -- Properties -----------------------------------------------------------

    @property
    def camera_id(self) -> str:
        """Return the unique camera identifier."""
        return self._camera_id

    @property
    def is_alive(self) -> bool:
        """Return True if currently active and streaming."""
        return self._running and self._status is CameraStatus.STREAMING

    @property
    def status(self) -> CameraStatus:
        """Current lifecycle status."""
        return self._status

    # -- Lifecycle ------------------------------------------------------------

    async def start(self) -> None:
        """Initialize and open the video stream."""
        if self._running:
            return

        self._log.info("starting_camera_stream")
        self._running = True
        self._stop_event.clear()
        self._start_time = time.monotonic()
        await self._connect()

    async def stop(self) -> None:
        """Stop acquisition and release capture resources."""
        if not self._running:
            return

        self._log.info("stopping_camera_stream")
        self._running = False
        self._stop_event.set()
        await self._release_capture()
        self._status = CameraStatus.STOPPED

    async def __aiter__(self) -> AsyncIterator[Frame]:
        """Async iterator yielding Frame objects continuously."""
        while self._running and not self._stop_event.is_set():
            try:
                frame = await self.__anext__()
                yield frame
            except StopAsyncIteration:
                break

    async def __anext__(self) -> Frame:
        """Fetch the next frame from the camera stream."""
        if not self._running or self._stop_event.is_set():
            raise StopAsyncIteration

        loop_start = time.monotonic()
        while self._running and not self._stop_event.is_set():
            if self._cap is None:
                reconnected = await self._reconnect_loop()
                if not reconnected:
                    raise StopAsyncIteration

            # Read frame using thread pool to avoid blocking asyncio loop
            success, raw_img = await asyncio.to_thread(self._read_frame_sync)

            if success and raw_img is not None:
                self._frame_seq += 1
                now_dt = datetime.now(timezone.utc)
                self._last_frame_time = now_dt

                # Track FPS calculation
                now_m = time.monotonic()
                self._fps_window.append(now_m)
                if len(self._fps_window) > self._fps_window_size:
                    self._fps_window.pop(0)

                frame = Frame(
                    image=raw_img,
                    camera_id=self._camera_id,
                    timestamp=now_dt,
                    frame_id=self._frame_seq,
                    metadata={
                        "source_url": self.config.source_url,
                        "capture_duration_ms": (time.monotonic() - loop_start) * 1000.0,
                    },
                )

                # Rate limiting to target FPS if processing was faster than target
                elapsed = time.monotonic() - loop_start
                sleep_needed = self._frame_interval - elapsed
                if sleep_needed > 0:
                    await asyncio.sleep(sleep_needed)

                return frame
            else:
                # Read failed
                self._total_dropped += 1
                self._log.warning("frame_read_failed_reconnecting")
                await self._release_capture()
                reconnected = await self._reconnect_loop()
                if not reconnected:
                    raise StopAsyncIteration

        raise StopAsyncIteration

    # -- Internal Capture Helpers ---------------------------------------------

    def _read_frame_sync(self) -> tuple[bool, np.ndarray | None]:
        """Synchronous frame read execution."""
        # Synthetic generator fallback
        if self.config.source_url.lower() == "synthetic" or self._cap == "synthetic":
            w = self.config.frame_width or 640
            h = self.config.frame_height or 480
            # Generate synthetic test pattern with sequence counter
            img = np.zeros((h, w, 3), dtype=np.uint8)
            img[:] = (20, 20, 20)
            return True, img

        if self._cap is None:
            return False, None

        try:
            ret, frame = self._cap.read()
            if not ret:
                # If file and configured to loop, rewind to beginning
                if self.config.loop_video_file:
                    try:
                        import cv2  # type: ignore[import-untyped]
                        self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ret, frame = self._cap.read()
                    except Exception:
                        ret = False
            return ret, frame
        except Exception as exc:
            self._last_error = str(exc)
            return False, None

    async def _connect(self) -> bool:
        """Establish connection to the camera source."""
        self._status = CameraStatus.CONNECTING
        self._log.info("connecting_to_camera_source")

        if self.config.source_url.lower() == "synthetic":
            self._cap = "synthetic"
            self._status = CameraStatus.STREAMING
            self._last_error = None
            return True

        def _open_capture() -> Any:
            try:
                import cv2  # type: ignore[import-untyped]
                cap = cv2.VideoCapture(self.config.source_url)
                if self.config.frame_width:
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.frame_width)
                if self.config.frame_height:
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.frame_height)
                return cap
            except ImportError:
                # OpenCV not installed, fallback to synthetic mode with warning
                return "synthetic"
            except Exception as exc:
                self._last_error = str(exc)
                return None

        cap = await asyncio.to_thread(_open_capture)
        if cap == "synthetic":
            self._log.warning("opencv_missing_falling_back_to_synthetic")
            self._cap = "synthetic"
            self._status = CameraStatus.STREAMING
            return True
        elif cap is not None and getattr(cap, "isOpened", lambda: True)():
            self._cap = cap
            self._status = CameraStatus.STREAMING
            self._last_error = None
            self._log.info("camera_connected_successfully")
            return True
        else:
            self._status = CameraStatus.ERROR
            self._last_error = "Failed to open video source"
            self._log.error("camera_connection_failed")
            return False

    async def _release_capture(self) -> None:
        """Release underlying OpenCV capture handle."""
        if self._cap is not None and self._cap != "synthetic":
            cap = self._cap
            self._cap = None
            def _release() -> None:
                try:
                    cap.release()
                except Exception:
                    pass
            await asyncio.to_thread(_release)
        else:
            self._cap = None

    async def _reconnect_loop(self) -> bool:
        """Attempt reconnection using exponential backoff."""
        self._status = CameraStatus.RECONNECTING
        delay = self.config.reconnect_initial_delay
        attempts = 0

        while self._running and not self._stop_event.is_set():
            attempts += 1
            self._reconnect_count += 1
            if self.config.max_reconnect_attempts > 0 and attempts > self.config.max_reconnect_attempts:
                self._status = CameraStatus.ERROR
                self._log.error("max_reconnect_attempts_exceeded", attempts=attempts)
                return False

            self._log.info("reconnecting_to_camera", attempt=attempts, delay_seconds=delay)
            await asyncio.sleep(delay)

            success = await self._connect()
            if success:
                self._log.info("camera_reconnected_successfully", attempt=attempts)
                return True

            delay = min(delay * self.config.reconnect_backoff_factor, self.config.reconnect_max_delay)

        return False

    # -- Telemetry ------------------------------------------------------------

    def health(self) -> CameraHealth:
        """Return operational telemetry."""
        now = time.monotonic()
        uptime = (now - self._start_time) if self._running else 0.0

        fps = 0.0
        if len(self._fps_window) >= 2:
            elapsed = self._fps_window[-1] - self._fps_window[0]
            if elapsed > 0:
                fps = (len(self._fps_window) - 1) / elapsed

        return CameraHealth(
            camera_id=self._camera_id,
            status=self._status,
            current_fps=round(fps, 2),
            total_frames_read=self._frame_seq,
            total_frames_dropped=self._total_dropped,
            reconnect_count=self._reconnect_count,
            last_frame_timestamp=self._last_frame_time,
            last_error=self._last_error,
            uptime_seconds=round(uptime, 2),
        )


# ---------------------------------------------------------------------------
# CameraManager
# ---------------------------------------------------------------------------

class CameraManager:
    """Manages lifecycle and pooling for multiple camera streams."""

    def __init__(self) -> None:
        self._streams: dict[str, CameraStream] = {}
        self._log = logger.bind(component="camera_manager")

    def register_camera(self, config: StreamConfig) -> CameraStream:
        """Register and create a new CameraStream."""
        if config.camera_id in self._streams:
            raise AcquisitionError(f"Camera '{config.camera_id}' is already registered.")

        stream = CameraStream(config)
        self._streams[config.camera_id] = stream
        self._log.info("camera_registered", camera_id=config.camera_id)
        return stream

    def get_stream(self, camera_id: str) -> CameraStream | None:
        """Retrieve an existing camera stream by ID."""
        return self._streams.get(camera_id)

    async def start_camera(self, camera_id: str) -> None:
        """Start a specific camera stream."""
        stream = self.get_stream(camera_id)
        if stream is None:
            raise AcquisitionError(f"Camera '{camera_id}' not found.")
        await stream.start()

    async def stop_camera(self, camera_id: str) -> None:
        """Stop a specific camera stream."""
        stream = self.get_stream(camera_id)
        if stream is not None:
            await stream.stop()

    async def start_all(self) -> None:
        """Start all registered camera streams in parallel."""
        self._log.info("starting_all_cameras", count=len(self._streams))
        await asyncio.gather(*(s.start() for s in self._streams.values()), return_exceptions=True)

    async def stop_all(self) -> None:
        """Stop all registered camera streams in parallel."""
        self._log.info("stopping_all_cameras", count=len(self._streams))
        await asyncio.gather(*(s.stop() for s in self._streams.values()), return_exceptions=True)

    def health_report(self) -> dict[str, CameraHealth]:
        """Return health summaries for all registered cameras."""
        return {cid: stream.health() for cid, stream in self._streams.items()}

    def active_cameras(self) -> list[str]:
        """Return list of camera IDs currently alive and streaming."""
        return [cid for cid, s in self._streams.items() if s.is_alive]
