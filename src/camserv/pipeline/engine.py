"""
camserv.pipeline.engine
========================

The asynchronous pipeline orchestrator for the CAMserv platform.

The :class:`PipelineEngine` coordinates the end-to-end processing lifecycle:
1. **Acquisition**: Reads raw frames from one or more :class:`~camserv.pipeline.interfaces.FrameSource` instances.
2. **Decoding**: Converts and pre-processes frames via :class:`~camserv.pipeline.interfaces.FrameDecoder`.
3. **Inference**: Executes object detection via :class:`~camserv.pipeline.interfaces.ObjectDetector`.
4. **Tracking**: Maintains cross-frame object identity via :class:`~camserv.pipeline.interfaces.ObjectTracker`.
5. **Event Detection & Privacy**: Evaluates security rules via :class:`~camserv.pipeline.interfaces.EventDetector`
   and optionally masks sensitive regions via :class:`~camserv.pipeline.interfaces.PrivacyFilter`.
6. **Storage**: Persists detections, events, and metrics via :class:`~camserv.pipeline.interfaces.StorageBackend`.

Stages communicate through bounded :class:`~camserv.pipeline.backpressure.BackpressureQueue`
instances with drop-oldest policies to maintain bounded memory and low latency under backpressure.
"""

from __future__ import annotations

import asyncio
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

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


from camserv.pipeline.backpressure import BackpressureQueue, DropPolicy
from camserv.pipeline.interfaces import (
    Detection,
    Event,
    EventDetector,
    Frame,
    FrameDecoder,
    FrameSource,
    ObjectDetector,
    ObjectTracker,
    PipelineError,
    PrivacyFilter,
    StorageBackend,
    Track,
)
from camserv.pipeline.metrics import MetricsRegistry

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Stage Data Payloads
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DecodedPayload:
    """Carries a decoded frame and its acquisition timestamp."""

    frame: Frame
    enqueued_at: float = field(default_factory=time.monotonic)


@dataclass(slots=True)
class InferencePayload:
    """Carries a decoded frame and its model detections."""

    frame: Frame
    detections: list[Detection]
    enqueued_at: float = field(default_factory=time.monotonic)


@dataclass(slots=True)
class TrackingPayload:
    """Carries frame, detections, and active tracks."""

    frame: Frame
    detections: list[Detection]
    tracks: list[Track]
    enqueued_at: float = field(default_factory=time.monotonic)


@dataclass(slots=True)
class StoragePayload:
    """Carries all processed artifacts ready for persistence and downstream dispatch."""

    frame: Frame
    detections: list[Detection]
    tracks: list[Track]
    events: list[Event]
    enqueued_at: float = field(default_factory=time.monotonic)


# ---------------------------------------------------------------------------
# Engine Configuration & Status
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class EngineConfig:
    """Configuration parameters for pipeline execution and memory limits."""

    raw_queue_size: int = 60
    decoded_queue_size: int = 60
    inference_queue_size: int = 40
    tracking_queue_size: int = 40
    storage_queue_size: int = 100

    # Memory limit in Megabytes (0 means unconstrained)
    max_memory_mb: float = 2048.0
    # Enable privacy filter step if component is provided
    enable_privacy_filtering: bool = True
    # Cooldown period for storage batching or idle sleep (seconds)
    idle_sleep_seconds: float = 0.005
    # Warning threshold for stage latency in milliseconds
    stage_latency_warning_ms: float = 100.0


@dataclass(slots=True)
class PipelineStatus:
    """Snapshot of overall pipeline health and performance."""

    is_running: bool
    uptime_seconds: float
    total_frames_acquired: int
    total_frames_processed: int
    total_frames_dropped: int
    total_events_emitted: int
    active_sources: list[str]
    stage_health: dict[str, bool]
    queue_depths: dict[str, int]
    memory_rss_mb: float
    gpu_memory_used_mb: float | None
    metrics_summary: dict[str, Any]


# ---------------------------------------------------------------------------
# PipelineEngine Orchestrator
# ---------------------------------------------------------------------------

class PipelineEngine:
    """Orchestrates async stages, queues, metrics, and lifecycle for video analytics.

    Parameters
    ----------
    config:
        Engine configuration tuning buffer sizes and safety limits.
    sources:
        Dictionary mapping camera_id to :class:`FrameSource`.
    decoder:
        Frame decoder component.
    detector:
        Object detector component.
    tracker:
        Object tracker component.
    event_detector:
        Event rule evaluation component.
    storage:
        Storage backend for persistence.
    privacy_filter:
        Optional privacy filter for blurring or masking regions.
    metrics_registry:
        Optional central metrics registry.
    """

    def __init__(
        self,
        config: EngineConfig | None = None,
        sources: dict[str, FrameSource] | None = None,
        decoder: FrameDecoder | None = None,
        detector: ObjectDetector | None = None,
        tracker: ObjectTracker | None = None,
        event_detector: EventDetector | None = None,
        storage: StorageBackend | None = None,
        privacy_filter: PrivacyFilter | None = None,
        metrics_registry: MetricsRegistry | None = None,
    ) -> None:
        self.config = config or EngineConfig()
        self.sources: dict[str, FrameSource] = sources or {}
        self.decoder = decoder
        self.detector = detector
        self.tracker = tracker
        self.event_detector = event_detector
        self.storage = storage
        self.privacy_filter = privacy_filter

        # Metrics
        self.metrics = metrics_registry or MetricsRegistry()
        self._lat_acquire = self.metrics.create_latency("acquire")
        self._lat_decode = self.metrics.create_latency("decode")
        self._lat_inference = self.metrics.create_latency("inference")
        self._lat_tracking = self.metrics.create_latency("tracking")
        self._lat_event = self.metrics.create_latency("event")
        self._lat_storage = self.metrics.create_latency("storage")
        self._lat_e2e = self.metrics.create_latency("e2e")

        self._fps_acquire = self.metrics.create_throughput("acquire")
        self._fps_processed = self.metrics.create_throughput("processed")
        self._fps_events = self.metrics.create_throughput("events")

        # Queues with Backpressure Drop-Oldest
        self.raw_queue: BackpressureQueue[Frame] = BackpressureQueue(
            name="raw_frames",
            maxsize=self.config.raw_queue_size,
            drop_policy=DropPolicy.DROP_OLDEST,
        )
        self.decoded_queue: BackpressureQueue[DecodedPayload] = BackpressureQueue(
            name="decoded_frames",
            maxsize=self.config.decoded_queue_size,
            drop_policy=DropPolicy.DROP_OLDEST,
        )
        self.inference_queue: BackpressureQueue[InferencePayload] = BackpressureQueue(
            name="inference_results",
            maxsize=self.config.inference_queue_size,
            drop_policy=DropPolicy.DROP_OLDEST,
        )
        self.tracking_queue: BackpressureQueue[TrackingPayload] = BackpressureQueue(
            name="tracking_results",
            maxsize=self.config.tracking_queue_size,
            drop_policy=DropPolicy.DROP_OLDEST,
        )
        self.storage_queue: BackpressureQueue[StoragePayload] = BackpressureQueue(
            name="storage_queue",
            maxsize=self.config.storage_queue_size,
            # Block or prioritize events for storage so alerts are not lost
            drop_policy=DropPolicy.DROP_OLDEST,
            enable_priority=True,
        )

        # Lifecycle & Tasks
        self._is_running = False
        self._start_time: float = 0.0
        self._tasks: list[asyncio.Task[None]] = []
        self._stop_event = asyncio.Event()
        self._stage_health: dict[str, bool] = {
            "acquisition": False,
            "decoding": False,
            "inference": False,
            "tracking": False,
            "event_detection": False,
            "storage": False,
        }

        # Counters
        self._total_acquired: int = 0
        self._total_processed: int = 0
        self._total_events: int = 0

        self._log = logger.bind(component="pipeline_engine")

    # ---------------------------------------------------------------------------
    # Source Registration
    # ---------------------------------------------------------------------------

    def add_source(self, camera_id: str, source: FrameSource) -> None:
        """Register a new frame source for acquisition."""
        self.sources[camera_id] = source
        self._log.info("source_registered", camera_id=camera_id)
        if self._is_running:
            task = asyncio.create_task(
                self._run_source_acquisition(camera_id, source),
                name=f"camserv-acquire-{camera_id}",
            )
            self._tasks.append(task)

    def remove_source(self, camera_id: str) -> None:
        """Remove an existing source."""
        if camera_id in self.sources:
            del self.sources[camera_id]
            self._log.info("source_removed", camera_id=camera_id)

    # ---------------------------------------------------------------------------
    # Lifecycle Control
    # ---------------------------------------------------------------------------

    async def start(self) -> None:
        """Start all stage worker loops and camera sources."""
        if self._is_running:
            self._log.warning("engine_already_running")
            return

        self._log.info("starting_pipeline_engine")
        self._is_running = True
        self._start_time = time.monotonic()
        self._stop_event.clear()

        # Warmup models if supported
        if self.detector is not None:
            try:
                await self.detector.warmup()
            except Exception as exc:
                self._log.warning("detector_warmup_failed", error=str(exc))

        # Start sources
        for camera_id, src in self.sources.items():
            try:
                await src.start()
            except Exception as exc:
                self._log.error("source_start_failed", camera_id=camera_id, error=str(exc))

        # Launch pipeline stage tasks
        self._tasks = [
            asyncio.create_task(self._decoding_stage(), name="camserv-decode"),
            asyncio.create_task(self._inference_stage(), name="camserv-inference"),
            asyncio.create_task(self._tracking_stage(), name="camserv-tracking"),
            asyncio.create_task(self._event_stage(), name="camserv-events"),
            asyncio.create_task(self._storage_stage(), name="camserv-storage"),
            asyncio.create_task(self._health_monitor_loop(), name="camserv-health"),
        ]

        # Launch acquisition tasks for all configured sources
        for camera_id, src in list(self.sources.items()):
            self._tasks.append(
                asyncio.create_task(
                    self._run_source_acquisition(camera_id, src),
                    name=f"camserv-acquire-{camera_id}",
                )
            )

        self._setup_signals()
        self._log.info("pipeline_engine_started", active_sources=list(self.sources.keys()))

    async def stop(self) -> None:
        """Gracefully stop all pipeline processing and flush queues."""
        if not self._is_running:
            return

        self._log.info("stopping_pipeline_engine")
        self._is_running = False
        self._stop_event.set()

        # Stop sources
        for camera_id, src in self.sources.items():
            try:
                await src.stop()
            except Exception as exc:
                self._log.error("source_stop_failed", camera_id=camera_id, error=str(exc))

        # Cancel stage tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()

        # Await completion
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        for stage in self._stage_health:
            self._stage_health[stage] = False

        self._log.info("pipeline_engine_stopped")

    def _setup_signals(self) -> None:
        """Register signal handlers for graceful shutdown on supported platforms."""
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                if sys.platform != "win32":
                    loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))
        except Exception:
            pass  # Fallback gracefully if platform or loop environment disallows

    # ---------------------------------------------------------------------------
    # Stage 1: Acquisition Worker
    # ---------------------------------------------------------------------------

    async def _run_source_acquisition(self, camera_id: str, source: FrameSource) -> None:
        """Consume frames from a single FrameSource and push into raw_queue."""
        self._log.info("source_acquisition_started", camera_id=camera_id)
        self._stage_health["acquisition"] = True

        try:
            async for frame in source:
                if self._stop_event.is_set():
                    break

                t0 = time.monotonic()
                # Enforce memory safety before queuing
                self._check_memory_safety()

                # Add acquisition timestamp to frame metadata
                frame.metadata["acquired_at_monotonic"] = t0
                await self.raw_queue.put(frame)

                self._total_acquired += 1
                self._fps_acquire.tick()
                elapsed = (time.monotonic() - t0) * 1000.0
                self._lat_acquire.record(elapsed)

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._log.error("acquisition_error", camera_id=camera_id, error=str(exc))
        finally:
            self._log.info("source_acquisition_stopped", camera_id=camera_id)

    # ---------------------------------------------------------------------------
    # Stage 2: Decoding Worker
    # ---------------------------------------------------------------------------

    async def _decoding_stage(self) -> None:
        """Dequeue raw frames, apply FrameDecoder, and forward to decoded_queue."""
        self._log.info("decoding_stage_started")
        self._stage_health["decoding"] = True

        while not self._stop_event.is_set():
            try:
                frame = await self.raw_queue.get(timeout=0.1)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            t0 = time.monotonic()
            try:
                if self.decoder is not None:
                    decoded_frame = await self.decoder.decode(frame)
                else:
                    decoded_frame = frame

                payload = DecodedPayload(frame=decoded_frame, enqueued_at=time.monotonic())
                await self.decoded_queue.put(payload)

                elapsed = (time.monotonic() - t0) * 1000.0
                self._lat_decode.record(elapsed)

            except Exception as exc:
                self._log.error("decoding_stage_error", frame_id=frame.frame_id, error=str(exc))
                # Error isolation: continue to next frame

    # ---------------------------------------------------------------------------
    # Stage 3: Inference Worker
    # ---------------------------------------------------------------------------

    async def _inference_stage(self) -> None:
        """Dequeue decoded frames, execute ObjectDetector, forward detections."""
        self._log.info("inference_stage_started")
        self._stage_health["inference"] = True

        while not self._stop_event.is_set():
            try:
                payload = await self.decoded_queue.get(timeout=0.1)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            t0 = time.monotonic()
            frame = payload.frame
            detections: list[Detection] = []

            try:
                if self.detector is not None:
                    detections = await self.detector.detect(frame)

                out = InferencePayload(
                    frame=frame,
                    detections=detections,
                    enqueued_at=time.monotonic(),
                )
                await self.inference_queue.put(out)

                elapsed = (time.monotonic() - t0) * 1000.0
                self._lat_inference.record(elapsed)

            except Exception as exc:
                self._log.error("inference_stage_error", frame_id=frame.frame_id, error=str(exc))
                # Forward with empty detections on error for pipeline continuity
                out = InferencePayload(frame=frame, detections=[], enqueued_at=time.monotonic())
                await self.inference_queue.put(out)

    # ---------------------------------------------------------------------------
    # Stage 4: Tracking Worker
    # ---------------------------------------------------------------------------

    async def _tracking_stage(self) -> None:
        """Dequeue detections, update ObjectTracker, forward active tracks."""
        self._log.info("tracking_stage_started")
        self._stage_health["tracking"] = True

        while not self._stop_event.is_set():
            try:
                payload = await self.inference_queue.get(timeout=0.1)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            t0 = time.monotonic()
            frame = payload.frame
            detections = payload.detections
            tracks: list[Track] = []

            try:
                if self.tracker is not None:
                    tracks = await self.tracker.update(detections, frame)

                out = TrackingPayload(
                    frame=frame,
                    detections=detections,
                    tracks=tracks,
                    enqueued_at=time.monotonic(),
                )
                await self.tracking_queue.put(out)

                elapsed = (time.monotonic() - t0) * 1000.0
                self._lat_tracking.record(elapsed)

            except Exception as exc:
                self._log.error("tracking_stage_error", frame_id=frame.frame_id, error=str(exc))
                out = TrackingPayload(frame=frame, detections=detections, tracks=[], enqueued_at=time.monotonic())
                await self.tracking_queue.put(out)

    # ---------------------------------------------------------------------------
    # Stage 5: Event Detection & Privacy Worker
    # ---------------------------------------------------------------------------

    async def _event_stage(self) -> None:
        """Evaluate events from tracks and apply privacy masking to frames."""
        self._log.info("event_stage_started")
        self._stage_health["event_detection"] = True

        while not self._stop_event.is_set():
            try:
                payload = await self.tracking_queue.get(timeout=0.1)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            t0 = time.monotonic()
            frame = payload.frame
            detections = payload.detections
            tracks = payload.tracks
            events: list[Event] = []

            try:
                # 1. Rule evaluation
                if self.event_detector is not None:
                    events = await self.event_detector.evaluate(tracks, detections, frame)
                    if events:
                        self._total_events += len(events)
                        self._fps_events.tick(len(events))

                # 2. Privacy filter
                processed_frame = frame
                if self.config.enable_privacy_filtering and self.privacy_filter is not None:
                    processed_frame = await self.privacy_filter.apply(frame, detections)

                # Prioritize enqueuing when events are present (priority 0 = high priority)
                priority = 0 if events else 10
                out = StoragePayload(
                    frame=processed_frame,
                    detections=detections,
                    tracks=tracks,
                    events=events,
                    enqueued_at=time.monotonic(),
                )
                await self.storage_queue.put(out, priority=priority)

                elapsed = (time.monotonic() - t0) * 1000.0
                self._lat_event.record(elapsed)

            except Exception as exc:
                self._log.error("event_stage_error", frame_id=frame.frame_id, error=str(exc))

    # ---------------------------------------------------------------------------
    # Stage 6: Storage Worker
    # ---------------------------------------------------------------------------

    async def _storage_stage(self) -> None:
        """Persist detections, events, and update latency statistics."""
        self._log.info("storage_stage_started")
        self._stage_health["storage"] = True

        while not self._stop_event.is_set():
            try:
                payload = await self.storage_queue.get(timeout=0.1)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            t0 = time.monotonic()
            frame = payload.frame

            try:
                if self.storage is not None:
                    if payload.detections:
                        await self.storage.store_detections(payload.detections)
                    for ev in payload.events:
                        await self.storage.store_event(ev)

                self._total_processed += 1
                self._fps_processed.tick()

                # End-to-end latency calculation
                acq_time = frame.metadata.get("acquired_at_monotonic")
                if acq_time:
                    e2e_ms = (time.monotonic() - acq_time) * 1000.0
                    self._lat_e2e.record(e2e_ms)

                elapsed = (time.monotonic() - t0) * 1000.0
                self._lat_storage.record(elapsed)

            except Exception as exc:
                self._log.error("storage_stage_error", frame_id=frame.frame_id, error=str(exc))

    # ---------------------------------------------------------------------------
    # Health Monitoring & Memory Guard
    # ---------------------------------------------------------------------------

    def _check_memory_safety(self) -> None:
        """Check if current process RSS exceeds max_memory_mb; drop frames if needed."""
        if self.config.max_memory_mb <= 0:
            return

        snap = self.metrics.memory.snapshot()
        if snap.process_rss_mb > self.config.max_memory_mb:
            self._log.warning(
                "memory_limit_exceeded_clearing_raw_queue",
                rss_mb=snap.process_rss_mb,
                limit_mb=self.config.max_memory_mb,
            )
            # Emergency shed: clear oldest un-processed raw frames
            asyncio.create_task(self.raw_queue.clear())

    async def _health_monitor_loop(self) -> None:
        """Periodically records queue depths and system memory into metrics."""
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(2.0)
                # Gauge queue depths
                self.metrics.set_gauge("queue_depth_raw", float(self.raw_queue.qsize))
                self.metrics.set_gauge("queue_depth_decoded", float(self.decoded_queue.qsize))
                self.metrics.set_gauge("queue_depth_inference", float(self.inference_queue.qsize))
                self.metrics.set_gauge("queue_depth_tracking", float(self.tracking_queue.qsize))
                self.metrics.set_gauge("queue_depth_storage", float(self.storage_queue.qsize))

                # Check storage backend health if available
                if self.storage is not None:
                    is_ok = await self.storage.health_check()
                    self._stage_health["storage"] = is_ok

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._log.debug("health_monitor_error", error=str(exc))

    # ---------------------------------------------------------------------------
    # Status Reporting
    # ---------------------------------------------------------------------------

    def status(self) -> PipelineStatus:
        """Produce a complete status snapshot of the running pipeline."""
        uptime = (time.monotonic() - self._start_time) if self._is_running else 0.0
        total_dropped = (
            self.raw_queue.dropped_count
            + self.decoded_queue.dropped_count
            + self.inference_queue.dropped_count
            + self.tracking_queue.dropped_count
            + self.storage_queue.dropped_count
        )
        mem = self.metrics.memory.snapshot()

        return PipelineStatus(
            is_running=self._is_running,
            uptime_seconds=round(uptime, 2),
            total_frames_acquired=self._total_acquired,
            total_frames_processed=self._total_processed,
            total_frames_dropped=total_dropped,
            total_events_emitted=self._total_events,
            active_sources=list(self.sources.keys()),
            stage_health=dict(self._stage_health),
            queue_depths={
                "raw": self.raw_queue.qsize,
                "decoded": self.decoded_queue.qsize,
                "inference": self.inference_queue.qsize,
                "tracking": self.tracking_queue.qsize,
                "storage": self.storage_queue.qsize,
            },
            memory_rss_mb=mem.process_rss_mb,
            gpu_memory_used_mb=mem.gpu_used_mb,
            metrics_summary=self.metrics.summary(),
        )
