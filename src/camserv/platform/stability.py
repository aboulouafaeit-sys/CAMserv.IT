"""
camserv.platform.stability
==========================

Zero-Freeze Architecture, Pipeline Bounded Queues, Failure Isolation & Service Supervision.
Ensures CAMserv operates reliably under extreme resource pressure, network interruptions,
accelerator crashes, and camera disconnect storms without UI blocking, recording stalls,
or uncontrolled memory growth.

Key Invariants:
1. UI and Recording paths NEVER block synchronously on network, AI, or slow disk I/O.
2. Ingestion and Recording have absolute priority over optional AI analysis.
3. All inter-subsystem queues are strictly bounded with documented capacity & overflow policies.
4. AI crashes, timeouts, and restarts are isolated and never crash or pause core recording.
5. Camera reconnect storms are mitigated via exponential backoff with randomized jitter.
6. Recording ingestion never silently drops frames: explicit discontinuity metadata is recorded.
7. Hung workers are detected via heartbeats and isolated to prevent duplicate recording workers.
"""

from __future__ import annotations

import asyncio
import collections
import enum
import math
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar

import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class PipelineType(str, enum.Enum):
    """Discrete processing pipelines in CAMserv."""

    RECORDING_INGEST = "recording_ingest"        # Camera RTSP ingest, packet parsing, hash computation
    LIVE_PREVIEW = "live_preview"                # Operator UI display stream (DROP_OLDEST permitted)
    AI_ANALYTICS = "ai_analytics"                # Object detection, classification, tracking
    STORAGE_WRITER = "storage_writer"            # Non-volatile disk write and SQLite index commit


class QueueOverflowPolicy(str, enum.Enum):
    """Documented capacity policies when an internal pipeline queue saturates."""

    DROP_OLDEST = "drop_oldest"          # Evicts oldest items (optimal for preview / transient AI frames)
    DROP_NEWEST = "drop_newest"          # Rejects incoming item (sheds peak transient burst)
    APPLY_BACKPRESSURE = "backpressure"  # Blocks producer with a bounded timeout (used for recording writes)
    FAIL_CLOSED = "fail_closed"          # Raises QueueFull exception (strict deterministic isolation)


class ServicePriority(str, enum.Enum):
    """Subsystem execution priorities."""

    CRITICAL_RECORDING = "critical_recording"    # Highest priority: RTSP ingest, elementary stream write, hashing
    STORAGE_PERSISTENCE = "storage_persistence"  # High priority: SQLite WAL holds, segment commit, rotation
    OPTIONAL_AI_ANALYSIS = "optional_ai"         # Optional priority: Object detection, classification, tracking
    UI_INTERACTIVE = "ui_interactive"            # Operator interface: Rendering, search, forensic export


class WorkerLifecycleState(str, enum.Enum):
    """Lifecycle states of background surveillance worker processes and threads."""

    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    HUNG = "hung"
    CANCELLATION_REQUESTED = "cancellation_requested"
    TERMINATING = "terminating"
    TERMINATED = "terminated"
    TERMINATION_UNCONFIRMED = "termination_unconfirmed"
    RECOVERED = "recovered"


class RecordingContinuityState(str, enum.Enum):
    """Explicit operational and degraded states for recording continuity."""

    CONTINUOUS = "CONTINUOUS"
    TEMPORARY_BACKPRESSURE = "TEMPORARY_BACKPRESSURE"
    FRAME_GAP_DETECTED = "FRAME_GAP_DETECTED"
    CAMERA_DISCONNECTED = "CAMERA_DISCONNECTED"
    STORAGE_BACKPRESSURE = "STORAGE_BACKPRESSURE"
    RECORDING_DEGRADED = "RECORDING_DEGRADED"
    RECORDING_INTERRUPTED = "RECORDING_INTERRUPTED"
    RECOVERY_IN_PROGRESS = "RECOVERY_IN_PROGRESS"
    RECOVERED_WITH_GAP = "RECOVERED_WITH_GAP"


@dataclass(slots=True)
class DiscontinuityEvent:
    """Documented evidence of a gap or discontinuity in an ingested surveillance stream."""

    camera_id: str
    stream_id: str
    segment_id: str | None
    gap_start_utc: str
    gap_end_utc: str
    gap_duration_sec: float
    lost_frames_estimated: int = 0
    reason: str = ""
    detected_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Phase 25.1-A semantic distinctions:
    confirmed_missing_frames: int | None = None
    estimated_missing_frames: int | None = None
    unknown_frame_loss: bool = False
    estimation_method: str = "timestamp_interval"
    confidence: str = "estimated"
    source_metadata: dict[str, Any] = field(default_factory=dict)
    recovery_status: str = "detected"
    first_subsequent_pts: float | None = None
    last_confirmed_pts: float | None = None
    last_confirmed_seq: int | None = None
    subsequent_seq: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "stream_id": self.stream_id,
            "segment_id": self.segment_id,
            "gap_start_utc": self.gap_start_utc,
            "gap_end_utc": self.gap_end_utc,
            "gap_duration_sec": round(self.gap_duration_sec, 3),
            "lost_frames_estimated": self.lost_frames_estimated,
            "confirmed_missing_frames": self.confirmed_missing_frames,
            "estimated_missing_frames": self.estimated_missing_frames,
            "unknown_frame_loss": self.unknown_frame_loss,
            "estimation_method": self.estimation_method,
            "confidence": self.confidence,
            "source_metadata": self.source_metadata,
            "reason": self.reason,
            "detected_at_utc": self.detected_at_utc,
            "recovery_status": self.recovery_status,
            "last_confirmed_pts": self.last_confirmed_pts,
            "first_subsequent_pts": self.first_subsequent_pts,
            "last_confirmed_seq": self.last_confirmed_seq,
            "subsequent_seq": self.subsequent_seq,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiscontinuityEvent:
        return cls(
            camera_id=data["camera_id"],
            stream_id=data["stream_id"],
            segment_id=data.get("segment_id"),
            gap_start_utc=data["gap_start_utc"],
            gap_end_utc=data["gap_end_utc"],
            gap_duration_sec=float(data.get("gap_duration_sec", 0.0)),
            lost_frames_estimated=int(data.get("lost_frames_estimated", 0)),
            reason=data.get("reason", ""),
            detected_at_utc=data.get("detected_at_utc", datetime.now(timezone.utc).isoformat()),
            confirmed_missing_frames=data.get("confirmed_missing_frames"),
            estimated_missing_frames=data.get("estimated_missing_frames"),
            unknown_frame_loss=bool(data.get("unknown_frame_loss", False)),
            estimation_method=data.get("estimation_method", "timestamp_interval"),
            confidence=data.get("confidence", "estimated"),
            source_metadata=data.get("source_metadata", {}),
            recovery_status=data.get("recovery_status", "detected"),
            first_subsequent_pts=data.get("first_subsequent_pts"),
            last_confirmed_pts=data.get("last_confirmed_pts"),
            last_confirmed_seq=data.get("last_confirmed_seq"),
            subsequent_seq=data.get("subsequent_seq"),
        )


@dataclass(slots=True)
class RecordingContinuityRecord:
    """Historical continuity ledger entry for an active camera stream segment."""

    camera_id: str
    stream_id: str
    segment_id: str
    start_timestamp_utc: str
    end_timestamp_utc: str | None = None
    expected_frames: int = 0
    observed_frames: int = 0
    discontinuities: list[DiscontinuityEvent] = field(default_factory=list)
    reconnect_events: int = 0
    storage_write_errors: int = 0
    is_finalized: bool = False
    integrity_verified: bool = False

    # Phase 25.1-A semantic enhancements
    current_state: RecordingContinuityState = RecordingContinuityState.CONTINUOUS
    confirmed_missing_frames_total: int = 0
    estimated_missing_frames_total: int = 0
    unknown_frame_loss_events: int = 0
    last_frame_seq: int | None = None
    last_frame_pts: float | None = None

    def to_dict(self) -> dict[str, Any]:
        continuity_ratio = round(self.observed_frames / max(1, self.expected_frames), 3) if self.expected_frames > 0 else 1.0
        return {
            "camera_id": self.camera_id,
            "stream_id": self.stream_id,
            "segment_id": self.segment_id,
            "start_timestamp_utc": self.start_timestamp_utc,
            "end_timestamp_utc": self.end_timestamp_utc,
            "expected_frames": self.expected_frames,
            "observed_frames": self.observed_frames,
            "continuity_ratio": continuity_ratio,
            "discontinuity_count": len(self.discontinuities),
            "reconnect_events": self.reconnect_events,
            "storage_write_errors": self.storage_write_errors,
            "is_finalized": self.is_finalized,
            "integrity_verified": self.integrity_verified,
            "current_state": self.current_state.value,
            "confirmed_missing_frames_total": self.confirmed_missing_frames_total,
            "estimated_missing_frames_total": self.estimated_missing_frames_total,
            "unknown_frame_loss_events": self.unknown_frame_loss_events,
            "last_frame_seq": self.last_frame_seq,
            "last_frame_pts": self.last_frame_pts,
            "discontinuities": [d.to_dict() for d in self.discontinuities],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecordingContinuityRecord:
        discs = [DiscontinuityEvent.from_dict(d) for d in data.get("discontinuities", [])]
        state_str = data.get("current_state", RecordingContinuityState.CONTINUOUS.value)
        try:
            state = RecordingContinuityState(state_str)
        except ValueError:
            state = RecordingContinuityState.CONTINUOUS

        rec = cls(
            camera_id=data["camera_id"],
            stream_id=data["stream_id"],
            segment_id=data["segment_id"],
            start_timestamp_utc=data["start_timestamp_utc"],
            end_timestamp_utc=data.get("end_timestamp_utc"),
            expected_frames=int(data.get("expected_frames", 0)),
            observed_frames=int(data.get("observed_frames", 0)),
            discontinuities=discs,
            reconnect_events=int(data.get("reconnect_events", 0)),
            storage_write_errors=int(data.get("storage_write_errors", 0)),
            is_finalized=bool(data.get("is_finalized", False)),
            integrity_verified=bool(data.get("integrity_verified", False)),
            current_state=state,
            confirmed_missing_frames_total=int(data.get("confirmed_missing_frames_total", 0)),
            estimated_missing_frames_total=int(data.get("estimated_missing_frames_total", 0)),
            unknown_frame_loss_events=int(data.get("unknown_frame_loss_events", 0)),
            last_frame_seq=data.get("last_frame_seq"),
            last_frame_pts=data.get("last_frame_pts"),
        )
        return rec


class RecordingContinuityLedger:
    """
    Central, thread-safe recording continuity ledger.
    Tracks frame sequence numbers, presentation timestamps (PTS), and detected gaps
    without inventing or fabricating missing frame information.
    Differentiates confirmed missing frames (via sequence numbers) from estimated
    missing frames (via PTS intervals) and unknown frame losses.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, RecordingContinuityRecord] = {}
        self._last_frame_timestamps: dict[str, float] = {}
        self._last_frame_seqs: dict[str, int] = {}
        self._expected_fps: dict[str, float] = {}

    def start_segment(
        self,
        camera_id: str,
        stream_id: str,
        segment_id: str,
        expected_fps: float = 30.0,
    ) -> RecordingContinuityRecord:
        key = f"{camera_id}:{segment_id}"
        with self._lock:
            rec = RecordingContinuityRecord(
                camera_id=camera_id,
                stream_id=stream_id,
                segment_id=segment_id,
                start_timestamp_utc=datetime.now(timezone.utc).isoformat(),
                current_state=RecordingContinuityState.CONTINUOUS,
            )
            self._records[key] = rec
            self._expected_fps[key] = expected_fps
            return rec

    def record_frame(
        self,
        camera_id: str,
        segment_id: str,
        frame_timestamp: float | None = None,
        frame_seq: int | None = None,
        source_metadata: dict[str, Any] | None = None,
    ) -> None:
        key = f"{camera_id}:{segment_id}"
        now = time.time()
        ts = frame_timestamp if frame_timestamp is not None else now
        meta = source_metadata or {}
        with self._lock:
            rec = self._records.get(key)
            if not rec:
                return

            rec.observed_frames += 1
            fps = self._expected_fps.get(key, 30.0)
            expected_interval = 1.0 / max(1.0, fps) if fps > 0 else 0.0333
            last_ts = self._last_frame_timestamps.get(key)
            last_seq = self._last_frame_seqs.get(key)

            # 1. Exact Loss Detection using Source Sequence Numbers
            if frame_seq is not None and last_seq is not None:
                if frame_seq > (last_seq + 1):
                    missing_count = frame_seq - last_seq - 1
                    gap_duration = (ts - last_ts) if last_ts is not None else expected_interval * missing_count
                    gap_event = DiscontinuityEvent(
                        camera_id=camera_id,
                        stream_id=rec.stream_id,
                        segment_id=segment_id,
                        gap_start_utc=datetime.fromtimestamp(last_ts or (ts - gap_duration), timezone.utc).isoformat(),
                        gap_end_utc=datetime.fromtimestamp(ts, timezone.utc).isoformat(),
                        gap_duration_sec=gap_duration,
                        lost_frames_estimated=missing_count,
                        confirmed_missing_frames=missing_count,
                        estimated_missing_frames=None,
                        unknown_frame_loss=False,
                        estimation_method="sequence_number_gap",
                        confidence="confirmed",
                        reason=f"SEQUENCE_NUMBER_GAP: expected {last_seq + 1}, received {frame_seq}",
                        last_confirmed_seq=last_seq,
                        subsequent_seq=frame_seq,
                        last_confirmed_pts=last_ts,
                        first_subsequent_pts=ts,
                        source_metadata=meta,
                    )
                    rec.discontinuities.append(gap_event)
                    rec.confirmed_missing_frames_total += missing_count
                    rec.current_state = RecordingContinuityState.FRAME_GAP_DETECTED
                    logger.warning(
                        "recording_continuity.confirmed_gap_detected",
                        camera_id=camera_id,
                        segment_id=segment_id,
                        missing_frames=missing_count,
                        expected_seq=last_seq + 1,
                        received_seq=frame_seq,
                    )
                elif frame_seq < last_seq:
                    # Out of order frame
                    gap_event = DiscontinuityEvent(
                        camera_id=camera_id,
                        stream_id=rec.stream_id,
                        segment_id=segment_id,
                        gap_start_utc=datetime.fromtimestamp(ts, timezone.utc).isoformat(),
                        gap_end_utc=datetime.fromtimestamp(ts, timezone.utc).isoformat(),
                        gap_duration_sec=0.0,
                        lost_frames_estimated=0,
                        confirmed_missing_frames=0,
                        estimated_missing_frames=None,
                        unknown_frame_loss=False,
                        estimation_method="sequence_number_gap",
                        confidence="confirmed",
                        reason=f"OUT_OF_ORDER_FRAME: last {last_seq}, received {frame_seq}",
                        last_confirmed_seq=last_seq,
                        subsequent_seq=frame_seq,
                        source_metadata=meta,
                    )
                    rec.discontinuities.append(gap_event)
                    logger.warning(
                        "recording_continuity.out_of_order_frame",
                        camera_id=camera_id,
                        last_seq=last_seq,
                        frame_seq=frame_seq,
                    )
            elif frame_seq is None and last_ts is not None:
                # 2. Sequence numbers unavailable; check Timestamp delta
                delta = ts - last_ts
                if delta > (expected_interval * 3.5):
                    if fps <= 0.0 or meta.get("variable_fps", False):
                        # Unreliable / Variable Frame Rate without sequence numbers: Unknown Loss
                        gap_event = DiscontinuityEvent(
                            camera_id=camera_id,
                            stream_id=rec.stream_id,
                            segment_id=segment_id,
                            gap_start_utc=datetime.fromtimestamp(last_ts, timezone.utc).isoformat(),
                            gap_end_utc=datetime.fromtimestamp(ts, timezone.utc).isoformat(),
                            gap_duration_sec=delta,
                            lost_frames_estimated=0,
                            confirmed_missing_frames=None,
                            estimated_missing_frames=None,
                            unknown_frame_loss=True,
                            estimation_method="unknown_insufficient_metadata",
                            confidence="unknown",
                            reason="TIMESTAMP_JUMP_UNKNOWN_OR_VARIABLE_FPS",
                            last_confirmed_pts=last_ts,
                            first_subsequent_pts=ts,
                            source_metadata=meta,
                        )
                        rec.discontinuities.append(gap_event)
                        rec.unknown_frame_loss_events += 1
                        rec.current_state = RecordingContinuityState.FRAME_GAP_DETECTED
                    else:
                        # Nominal FPS estimation
                        lost_est = max(1, int(round((delta - expected_interval) / expected_interval)))
                        gap_event = DiscontinuityEvent(
                            camera_id=camera_id,
                            stream_id=rec.stream_id,
                            segment_id=segment_id,
                            gap_start_utc=datetime.fromtimestamp(last_ts, timezone.utc).isoformat(),
                            gap_end_utc=datetime.fromtimestamp(ts, timezone.utc).isoformat(),
                            gap_duration_sec=delta,
                            lost_frames_estimated=lost_est,
                            confirmed_missing_frames=None,
                            estimated_missing_frames=lost_est,
                            unknown_frame_loss=False,
                            estimation_method="timestamp_interval",
                            confidence="estimated",
                            reason="TIMESTAMP_JUMP_NETWORK_OR_BUFFER_STALL",
                            last_confirmed_pts=last_ts,
                            first_subsequent_pts=ts,
                            source_metadata=meta,
                        )
                        rec.discontinuities.append(gap_event)
                        rec.estimated_missing_frames_total += lost_est
                        rec.current_state = RecordingContinuityState.FRAME_GAP_DETECTED
                        logger.warning(
                            "recording_continuity.gap_detected",
                            camera_id=camera_id,
                            segment_id=segment_id,
                            gap_sec=round(delta, 3),
                            lost_est=lost_est,
                        )

            # State transition after recovery
            if rec.current_state == RecordingContinuityState.RECOVERY_IN_PROGRESS:
                rec.current_state = (
                    RecordingContinuityState.RECOVERED_WITH_GAP
                    if rec.discontinuities
                    else RecordingContinuityState.CONTINUOUS
                )

            self._last_frame_timestamps[key] = ts
            rec.last_frame_pts = ts
            if frame_seq is not None:
                self._last_frame_seqs[key] = frame_seq
                rec.last_frame_seq = frame_seq

    def record_queue_drop(
        self,
        camera_id: str,
        segment_id: str,
        reason: str,
        dropped_count: int = 1,
    ) -> None:
        """Record bounded queue overflow drop on recording path."""
        key = f"{camera_id}:{segment_id}"
        with self._lock:
            rec = self._records.get(key)
            if not rec:
                return
            now_iso = datetime.now(timezone.utc).isoformat()
            gap_event = DiscontinuityEvent(
                camera_id=camera_id,
                stream_id=rec.stream_id,
                segment_id=segment_id,
                gap_start_utc=now_iso,
                gap_end_utc=now_iso,
                gap_duration_sec=0.0,
                lost_frames_estimated=dropped_count,
                confirmed_missing_frames=None,
                estimated_missing_frames=dropped_count,
                unknown_frame_loss=False,
                estimation_method="queue_overflow_drop",
                confidence="estimated",
                reason=reason,
            )
            rec.discontinuities.append(gap_event)
            rec.estimated_missing_frames_total += dropped_count
            rec.current_state = RecordingContinuityState.RECORDING_DEGRADED

    def record_camera_disconnect(
        self,
        camera_id: str,
        segment_id: str,
        reason: str = "CAMERA_NETWORK_TIMEOUT",
    ) -> None:
        """Record camera physical/network disconnect event."""
        key = f"{camera_id}:{segment_id}"
        with self._lock:
            rec = self._records.get(key)
            if not rec:
                return
            rec.current_state = RecordingContinuityState.CAMERA_DISCONNECTED
            now_iso = datetime.now(timezone.utc).isoformat()
            rec.discontinuities.append(
                DiscontinuityEvent(
                    camera_id=camera_id,
                    stream_id=rec.stream_id,
                    segment_id=segment_id,
                    gap_start_utc=now_iso,
                    gap_end_utc=now_iso,
                    gap_duration_sec=0.0,
                    lost_frames_estimated=0,
                    confirmed_missing_frames=None,
                    estimated_missing_frames=None,
                    unknown_frame_loss=True,
                    estimation_method="camera_disconnect",
                    confidence="unknown",
                    reason=f"CAMERA_DISCONNECTED: {reason}",
                    recovery_status="interrupted",
                )
            )

    def record_camera_reconnect_start(self, camera_id: str, segment_id: str) -> None:
        """Record initiation of camera reconnect attempt."""
        key = f"{camera_id}:{segment_id}"
        with self._lock:
            rec = self._records.get(key)
            if rec:
                rec.reconnect_events += 1
                rec.current_state = RecordingContinuityState.RECOVERY_IN_PROGRESS

    def transition_state(
        self,
        camera_id: str,
        segment_id: str,
        new_state: RecordingContinuityState,
        reason: str = "",
    ) -> None:
        """Thread-safe recording continuity state transition."""
        key = f"{camera_id}:{segment_id}"
        with self._lock:
            rec = self._records.get(key)
            if rec:
                rec.current_state = new_state
                if reason:
                    logger.info(
                        "recording_continuity.state_transition",
                        camera_id=camera_id,
                        new_state=new_state.value,
                        reason=reason,
                    )

    def record_storage_error(self, camera_id: str, segment_id: str, error_reason: str) -> None:
        key = f"{camera_id}:{segment_id}"
        with self._lock:
            rec = self._records.get(key)
            if rec:
                rec.storage_write_errors += 1
                rec.current_state = RecordingContinuityState.STORAGE_BACKPRESSURE
                rec.discontinuities.append(
                    DiscontinuityEvent(
                        camera_id=camera_id,
                        stream_id=rec.stream_id,
                        segment_id=segment_id,
                        gap_start_utc=datetime.now(timezone.utc).isoformat(),
                        gap_end_utc=datetime.now(timezone.utc).isoformat(),
                        gap_duration_sec=0.0,
                        lost_frames_estimated=0,
                        confirmed_missing_frames=None,
                        estimated_missing_frames=None,
                        unknown_frame_loss=True,
                        estimation_method="storage_error",
                        confidence="unknown",
                        reason=f"STORAGE_WRITE_ERROR: {error_reason}",
                    )
                )

    def record_reconnect(self, camera_id: str, segment_id: str) -> None:
        key = f"{camera_id}:{segment_id}"
        with self._lock:
            rec = self._records.get(key)
            if rec:
                rec.reconnect_events += 1

    def finalize_segment(
        self,
        camera_id: str,
        segment_id: str,
        expected_frames: int | None = None,
        integrity_verified: bool = True,
    ) -> RecordingContinuityRecord | None:
        key = f"{camera_id}:{segment_id}"
        with self._lock:
            rec = self._records.get(key)
            if not rec:
                return None
            rec.end_timestamp_utc = datetime.now(timezone.utc).isoformat()
            if expected_frames is not None:
                rec.expected_frames = expected_frames
            else:
                rec.expected_frames = rec.observed_frames
            rec.is_finalized = True
            rec.integrity_verified = integrity_verified
            return rec

    def get_record(self, camera_id: str, segment_id: str) -> RecordingContinuityRecord | None:
        key = f"{camera_id}:{segment_id}"
        with self._lock:
            return self._records.get(key)

    def to_dict(self) -> dict[str, Any]:
        """Serialize complete continuity ledger for persistent storage."""
        with self._lock:
            return {
                "records": {k: v.to_dict() for k, v in self._records.items()},
                "expected_fps": dict(self._expected_fps),
            }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecordingContinuityLedger:
        """Reload continuity ledger from persisted records."""
        ledger = cls()
        records_raw = data.get("records", {})
        for k, v in records_raw.items():
            ledger._records[k] = RecordingContinuityRecord.from_dict(v)
        ledger._expected_fps = {k: float(v) for k, v in data.get("expected_fps", {}).items()}
        return ledger


@dataclass(slots=True)
class QueueTelemetry:
    """Real-time observability metrics for a bounded pipeline queue."""

    queue_name: str
    capacity: int
    current_size: int
    pipeline_type: str = "ai_analytics"
    total_enqueued: int = 0
    total_dequeued: int = 0
    total_dropped: int = 0
    overflow_events: int = 0
    high_watermark: int = 0
    max_latency_ms: float = 0.0
    is_disk_full: bool = False

    @property
    def utilization_percent(self) -> float:
        if self.capacity <= 0:
            return 0.0
        return round((self.current_size / self.capacity) * 100.0, 1)


class BoundedPipelineQueue(Generic[T]):
    """
    Thread-safe, bounded pipeline queue with explicit overflow policies,
    telemetry accounting, and non-blocking semantics.
    Prevents uncontrolled heap expansion during slow disk I/O or AI stalls.
    """

    def __init__(
        self,
        name: str,
        maxsize: int = 120,
        policy: QueueOverflowPolicy = QueueOverflowPolicy.DROP_OLDEST,
        priority: ServicePriority = ServicePriority.OPTIONAL_AI_ANALYSIS,
        pipeline_type: PipelineType = PipelineType.AI_ANALYTICS,
        continuity_ledger: RecordingContinuityLedger | None = None,
        camera_id: str | None = None,
        segment_id: str | None = None,
    ) -> None:
        if maxsize <= 0:
            raise ValueError(f"Queue capacity must be positive, got {maxsize}")
        self.name = name
        self.maxsize = maxsize
        self.policy = policy
        self.priority = priority
        self.pipeline_type = pipeline_type
        self.continuity_ledger = continuity_ledger
        self.camera_id = camera_id
        self.segment_id = segment_id

        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._not_full = threading.Condition(self._lock)
        self._deque: collections.deque[tuple[T, float]] = collections.deque()

        # Telemetry
        self.total_enqueued = 0
        self.total_dequeued = 0
        self.total_dropped = 0
        self.overflow_events = 0
        self.high_watermark = 0
        self.max_latency_ms = 0.0
        self.is_disk_full = False

    def set_disk_full(self, status: bool) -> None:
        """Set or clear disk full emergency state."""
        with self._lock:
            self.is_disk_full = status
            if status:
                logger.error("bounded_queue.disk_full_engaged", queue=self.name)

    def put(self, item: T, timeout_sec: float | None = None) -> bool:
        """
        Enqueue an item following the configured overflow policy.
        Returns True if item was accepted into queue, False if dropped.
        """
        now = time.time()
        with self._lock:
            # If disk is completely full for storage writer, reject immediately without deadlocking
            if self.is_disk_full and self.pipeline_type == PipelineType.STORAGE_WRITER:
                self.total_dropped += 1
                if self.continuity_ledger and self.camera_id and self.segment_id:
                    self.continuity_ledger.record_storage_error(
                        self.camera_id, self.segment_id, "DISK_FULL_EMERGENCY_REJECTION"
                    )
                return False

            # Check if queue has space
            if len(self._deque) < self.maxsize:
                self._deque.append((item, now))
                self.total_enqueued += 1
                self.high_watermark = max(self.high_watermark, len(self._deque))
                self._not_empty.notify()
                return True

            # Capacity reached: apply policy
            self.overflow_events += 1

            if self.policy == QueueOverflowPolicy.DROP_OLDEST:
                evicted, enq_time = self._deque.popleft()
                self.total_dropped += 1
                self._deque.append((item, now))
                self.total_enqueued += 1
                self._not_empty.notify()
                logger.debug(
                    "bounded_queue.drop_oldest",
                    queue=self.name,
                    dropped_count=self.total_dropped,
                )
                return True

            elif self.policy == QueueOverflowPolicy.DROP_NEWEST:
                self.total_dropped += 1
                logger.debug(
                    "bounded_queue.drop_newest",
                    queue=self.name,
                    dropped_count=self.total_dropped,
                )
                return False

            elif self.policy == QueueOverflowPolicy.APPLY_BACKPRESSURE:
                # Ingestion queues must not block indefinitely; cap wait at timeout_sec or 0.5s
                wait_limit = timeout_sec if timeout_sec is not None else 0.5
                deadline = now + wait_limit

                # Signal backpressure state to ledger if this is recording ingest or storage writer
                if self.continuity_ledger and self.camera_id and self.segment_id:
                    if self.pipeline_type == PipelineType.STORAGE_WRITER:
                        self.continuity_ledger.transition_state(
                            self.camera_id, self.segment_id, RecordingContinuityState.STORAGE_BACKPRESSURE, "STORAGE_QUEUE_FULL"
                        )
                    elif self.pipeline_type == PipelineType.RECORDING_INGEST:
                        self.continuity_ledger.transition_state(
                            self.camera_id, self.segment_id, RecordingContinuityState.TEMPORARY_BACKPRESSURE, "INGEST_QUEUE_FULL"
                        )

                while len(self._deque) >= self.maxsize:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        self.total_dropped += 1
                        if self.continuity_ledger and self.camera_id and self.segment_id:
                            if self.pipeline_type == PipelineType.RECORDING_INGEST:
                                self.continuity_ledger.record_queue_drop(
                                    self.camera_id,
                                    self.segment_id,
                                    reason=f"RECORDING_INGEST_QUEUE_OVERFLOW_BACKPRESSURE_TIMEOUT_{wait_limit:.2f}s",
                                    dropped_count=1,
                                )
                            else:
                                self.continuity_ledger.record_storage_error(
                                    self.camera_id,
                                    self.segment_id,
                                    f"QUEUE_BACKPRESSURE_TIMEOUT_{wait_limit:.2f}s",
                                )
                        logger.warning(
                            "bounded_queue.backpressure_timeout",
                            queue=self.name,
                            timeout_sec=wait_limit,
                            dropped=self.total_dropped,
                        )
                        return False
                    self._not_full.wait(remaining)

                self._deque.append((item, now))
                self.total_enqueued += 1
                self.high_watermark = max(self.high_watermark, len(self._deque))
                self._not_empty.notify()
                return True

            else:  # FAIL_CLOSED
                self.total_dropped += 1
                raise BufferError(f"Queue '{self.name}' saturated at capacity {self.maxsize}")

    def get(self, timeout_sec: float | None = 0.1) -> T | None:
        """Dequeue an item with timeout. Returns None if queue is empty."""
        with self._lock:
            if not self._deque:
                if timeout_sec and timeout_sec > 0:
                    self._not_empty.wait(timeout_sec)
                if not self._deque:
                    return None

            item, enq_time = self._deque.popleft()
            self.total_dequeued += 1
            latency = (time.time() - enq_time) * 1000.0
            self.max_latency_ms = max(self.max_latency_ms, latency)
            self._not_full.notify()
            return item

    def get_telemetry(self) -> QueueTelemetry:
        """Retrieve real-time queue health telemetry."""
        with self._lock:
            return QueueTelemetry(
                queue_name=self.name,
                capacity=self.maxsize,
                current_size=len(self._deque),
                pipeline_type=self.pipeline_type.value,
                total_enqueued=self.total_enqueued,
                total_dequeued=self.total_dequeued,
                total_dropped=self.total_dropped,
                overflow_events=self.overflow_events,
                high_watermark=self.high_watermark,
                max_latency_ms=round(self.max_latency_ms, 2),
                is_disk_full=self.is_disk_full,
            )

    def clear(self) -> int:
        """Clear all pending items and return count of cleared items."""
        with self._lock:
            count = len(self._deque)
            self._deque.clear()
            self._not_full.notify_all()
            return count


def calculate_backoff_with_jitter(
    attempt: int,
    base_delay_sec: float = 1.0,
    max_delay_sec: float = 60.0,
    jitter_factor: float = 0.25,
) -> float:
    """
    Calculate exponential backoff with full randomized jitter to prevent reconnect storms.
    Formula: delay = min(max_delay, base * 2^attempt) * (1 +/- random(0, jitter))
    """
    attempt = max(0, min(10, attempt))
    exp_delay = min(max_delay_sec, base_delay_sec * math.pow(2, max(0, attempt - 1)))
    # Add randomized symmetric jitter
    jitter = exp_delay * jitter_factor * (random.random() * 2.0 - 1.0)
    final_delay = max(0.1, exp_delay + jitter)
    return round(final_delay, 3)


class CancellationExit(Exception):
    """Raised by worker thread when checking cancellation token at a safe boundary."""
    pass


class CancellationToken:
    """
    Thread-safe cooperative cancellation token with boundary checkpoints,
    explicit worker acknowledgment, and confirmed stopped tracking.
    """

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._acknowledged = threading.Event()
        self._stopped = threading.Event()
        self.requested_timestamp: float | None = None
        self.acknowledged_timestamp: float | None = None
        self.stopped_timestamp: float | None = None
        self.last_checkpoint: str | None = None

    def cancel(self) -> None:
        """Signal cancellation request to worker."""
        if not self._cancelled.is_set():
            self.requested_timestamp = time.time()
            self._cancelled.set()

    def acknowledge(self, checkpoint_name: str = "general") -> None:
        """Signal that worker observed cancellation and is initiating clean exit."""
        self.last_checkpoint = checkpoint_name
        if not self._acknowledged.is_set():
            self.acknowledged_timestamp = time.time()
            self._acknowledged.set()

    def confirm_stopped(self) -> None:
        """Signal that worker thread/process has terminated and cleaned up resources."""
        self.stopped_timestamp = time.time()
        self._stopped.set()

    def checkpoint(self, checkpoint_name: str = "unnamed_checkpoint") -> bool:
        """
        Check cancellation status at a defined safe boundary.
        If cancelled, acknowledges and returns True.
        """
        if self._cancelled.is_set():
            self.acknowledge(checkpoint_name)
            return True
        return False

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def cancellation_requested(self) -> bool:
        return self._cancelled.is_set()

    @property
    def cancellation_acknowledged(self) -> bool:
        return self._acknowledged.is_set()

    @property
    def is_confirmed_stopped(self) -> bool:
        return self._stopped.is_set()

    def wait_stopped(self, timeout_sec: float = 1.0) -> bool:
        """Wait for worker confirmation of termination."""
        return self._stopped.wait(timeout_sec)


class WorkerCrashSupervisor:
    """
    Monitors background workers (AI inference, camera RTSP decoders, flusher).
    Provides crash isolation, heartbeat watchdog monitoring, anti-duplicate lease fencing,
    truthful worker termination reporting, and safe partial segment recovery.
    """

    # Global lease registry to prevent duplicate workers for the same camera channel
    _ACTIVE_CHANNEL_LEASES: dict[str, str] = {}
    _LEASE_LOCK = threading.Lock()

    def __init__(
        self,
        name: str,
        max_restarts: int = 5,
        backoff_base_sec: float = 1.0,
        heartbeat_timeout_sec: float = 10.0,
        channel_id: str | None = None,
    ) -> None:
        self.name = name
        self.max_restarts = max_restarts
        self.backoff_base_sec = backoff_base_sec
        self.heartbeat_timeout_sec = heartbeat_timeout_sec
        self.channel_id = channel_id

        self.restart_count = 0
        self.crash_history: list[dict[str, Any]] = []
        self.is_alive = True
        self.is_fenced = False
        self.state = WorkerLifecycleState.STARTING
        self.last_heartbeat_timestamp = time.time()
        self.lease_token: str | None = None

        # Worker handle and termination tracking
        self.worker_thread: threading.Thread | None = None
        self.worker_process: Any | None = None
        self.cancellation_token: CancellationToken | None = None
        self.termination_confirmed: bool = False
        self.termination_forced: bool = False
        self.termination_unconfirmed: bool = False

        if self.channel_id:
            self.acquire_channel_lease()

    def register_worker(
        self,
        thread: threading.Thread | None = None,
        token: CancellationToken | None = None,
        process: Any | None = None,
    ) -> None:
        """Register live worker thread, cancellation token, or isolated process."""
        self.worker_thread = thread
        self.cancellation_token = token
        self.worker_process = process
        self.termination_confirmed = False
        self.termination_forced = False
        self.termination_unconfirmed = False
        self.is_alive = True

    def acquire_channel_lease(self) -> str | None:
        """Acquire atomic exclusive lease for this worker's camera channel."""
        if not self.channel_id:
            return None
        with self._LEASE_LOCK:
            existing = self._ACTIVE_CHANNEL_LEASES.get(self.channel_id)
            if existing and existing != self.lease_token:
                logger.warning(
                    "worker_supervisor.lease_collision_prevented",
                    channel=self.channel_id,
                    existing_lease=existing,
                )
                self.is_fenced = True
                self.state = WorkerLifecycleState.TERMINATED
                return None
            token = f"lease_{self.channel_id}_{uuid.uuid4().hex[:8]}"
            self.lease_token = token
            self._ACTIVE_CHANNEL_LEASES[self.channel_id] = token
            return token

    def revoke_channel_lease(self) -> None:
        """Release atomic lease upon worker confirmed termination or restart fencing."""
        if not self.channel_id or not self.lease_token:
            return
        with self._LEASE_LOCK:
            if self._ACTIVE_CHANNEL_LEASES.get(self.channel_id) == self.lease_token:
                self._ACTIVE_CHANNEL_LEASES.pop(self.channel_id, None)
            self.lease_token = None

    def record_heartbeat(self) -> None:
        """Record live worker heartbeat."""
        self.last_heartbeat_timestamp = time.time()
        if self.state in (WorkerLifecycleState.STARTING, WorkerLifecycleState.DEGRADED):
            self.state = WorkerLifecycleState.RUNNING

    def check_hung(self, now: float | None = None) -> bool:
        """
        Check if worker has missed heartbeat beyond threshold.
        Returns True if worker is detected as HUNG.
        """
        current_time = now if now is not None else time.time()
        elapsed = current_time - self.last_heartbeat_timestamp
        if elapsed > self.heartbeat_timeout_sec:
            if self.state not in (WorkerLifecycleState.HUNG, WorkerLifecycleState.TERMINATED, WorkerLifecycleState.TERMINATION_UNCONFIRMED):
                self.state = WorkerLifecycleState.HUNG
                logger.error(
                    "worker_supervisor.worker_hung_detected",
                    worker=self.name,
                    elapsed_sec=round(elapsed, 2),
                    timeout_sec=self.heartbeat_timeout_sec,
                )
            return True
        elif elapsed > (self.heartbeat_timeout_sec * 0.5):
            self.state = WorkerLifecycleState.DEGRADED
        return False

    def record_crash(self, exception: Exception | str) -> float:
        """
        Record worker crash, increment restart counter, and compute safe delay before retry.
        If max_restarts is exceeded, fences worker to prevent continuous thrashing.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        self.restart_count += 1
        err_msg = str(exception)
        self.state = WorkerLifecycleState.TERMINATING

        self.crash_history.append({
            "restart_attempt": self.restart_count,
            "timestamp_utc": now_iso,
            "error": err_msg,
        })

        if self.restart_count > self.max_restarts:
            self.is_fenced = True
            self.is_alive = False
            self.state = WorkerLifecycleState.TERMINATED
            self.revoke_channel_lease()
            logger.error(
                "worker_supervisor.worker_fenced_exceeded_restarts",
                worker=self.name,
                restarts=self.restart_count,
                error=err_msg,
            )
            return -1.0  # Fenced: do not restart

        delay = calculate_backoff_with_jitter(self.restart_count, self.backoff_base_sec)
        logger.warning(
            "worker_supervisor.worker_crashed_isolated",
            worker=self.name,
            restart_count=self.restart_count,
            next_retry_delay_sec=delay,
            error=err_msg,
        )
        return delay

    def request_cancellation(self, timeout_sec: float = 1.0) -> bool:
        """
        Request cooperative cancellation of worker and await confirmed termination.
        Returns True if confirmed stopped, False if unconfirmed.
        """
        self.state = WorkerLifecycleState.CANCELLATION_REQUESTED
        if self.cancellation_token:
            self.cancellation_token.cancel()

        stopped = False
        if self.cancellation_token:
            stopped = self.cancellation_token.wait_stopped(timeout_sec)
        elif self.worker_thread:
            self.worker_thread.join(timeout_sec)
            stopped = not self.worker_thread.is_alive()

        if stopped:
            self.termination_confirmed = True
            self.termination_unconfirmed = False
            self.state = WorkerLifecycleState.TERMINATED
            self.is_alive = False
            self.revoke_channel_lease()
            return True
        else:
            self.termination_confirmed = False
            self.termination_unconfirmed = True
            self.state = WorkerLifecycleState.TERMINATION_UNCONFIRMED
            # Mandatory: Never revoke channel lease while worker may still be active
            logger.critical(
                "worker_supervisor.cancellation_timeout_unconfirmed",
                worker=self.name,
                channel=self.channel_id,
            )
            return False

    def terminate_worker(self, force: bool = False, timeout_sec: float = 1.0) -> bool:
        """
        Controlled worker termination.
        Where enforceable process isolation is available and force=True, forces termination.
        Where cooperative thread termination does not confirm within timeout,
        reports TERMINATION_UNCONFIRMED and preserves channel lease fencing.
        """
        self.state = WorkerLifecycleState.TERMINATING

        # Process isolation path: enforceable termination
        if self.worker_process is not None:
            if force:
                try:
                    if hasattr(self.worker_process, "kill"):
                        self.worker_process.kill()
                    elif hasattr(self.worker_process, "terminate"):
                        self.worker_process.terminate()
                    if hasattr(self.worker_process, "join"):
                        self.worker_process.join(timeout_sec)
                    self.termination_forced = True
                    self.termination_confirmed = True
                    self.termination_unconfirmed = False
                    self.state = WorkerLifecycleState.TERMINATED
                    self.is_alive = False
                    self.revoke_channel_lease()
                    return True
                except Exception as exc:
                    logger.error("worker_supervisor.process_force_kill_failed", error=str(exc))
                    self.termination_unconfirmed = True
                    self.state = WorkerLifecycleState.TERMINATION_UNCONFIRMED
                    return False

        # Cooperative token / thread path
        if self.cancellation_token or self.worker_thread:
            return self.request_cancellation(timeout_sec=timeout_sec)

        # Default synchronous path when no background worker thread/process is active
        self.termination_confirmed = True
        self.termination_unconfirmed = False
        self.state = WorkerLifecycleState.TERMINATED
        self.is_alive = False
        self.revoke_channel_lease()
        return True

    def quarantine_partial_segment(
        self,
        part_path: Path | str,
        reason: str = "WORKER_HUNG_RECOVERY",
    ) -> Path | None:
        """
        Safely recover and quarantine an in-flight .part segment without data loss.
        Renames .part to .recovered_partial.mp4 and updates state to RECOVERED.
        """
        p = Path(part_path)
        if not p.exists() or p.stat().st_size == 0:
            return None

        recovered_name = p.stem.replace(".part", "") + ".recovered_partial.mp4"
        recovered_path = p.parent / recovered_name
        try:
            p.rename(recovered_path)
            self.state = WorkerLifecycleState.RECOVERED
            logger.info(
                "worker_supervisor.segment_recovered_partial",
                original=str(p),
                recovered=str(recovered_path),
                size_bytes=recovered_path.stat().st_size,
                reason=reason,
            )
            return recovered_path
        except Exception as exc:
            logger.error("worker_supervisor.recovery_rename_failed", error=str(exc))
            return None

    def reset_clean(self) -> None:
        """Reset restart count and restore clean state after a period of stability."""
        self.restart_count = 0
        self.is_fenced = False
        self.is_alive = True
        self.state = WorkerLifecycleState.RUNNING
        self.last_heartbeat_timestamp = time.time()
        self.termination_confirmed = False
        self.termination_unconfirmed = False


class NonBlockingExecutor:
    """
    Utility ensuring long-running operations (RTSP probe, storage sync, neural model loading)
    are executed asynchronously with hard timeouts, completely isolating the graphical UI.
    """

    @staticmethod
    def execute_with_timeout(
        task_fn: Callable[[], T],
        timeout_sec: float = 3.0,
        fallback_value: T | None = None,
    ) -> tuple[bool, T | None, str | None]:
        """
        Execute task_fn in a worker thread with guaranteed timeout.
        Returns: (success, result, error_message)
        """
        result: list[T | None] = [fallback_value]
        exc_holder: list[Exception | None] = [None]
        completed = threading.Event()

        def _target() -> None:
            try:
                result[0] = task_fn()
            except Exception as e:
                exc_holder[0] = e
            finally:
                completed.set()

        t = threading.Thread(target=_target, daemon=True)
        t.start()
        is_finished = completed.wait(timeout_sec)

        if not is_finished:
            return (
                False,
                fallback_value,
                f"Operation timed out after {timeout_sec:.2f} seconds (Non-blocking guard engaged).",
            )

        if exc_holder[0] is not None:
            return False, fallback_value, str(exc_holder[0])

        return True, result[0], None

    @staticmethod
    def execute_with_cancellation(
        task_fn: Callable[[CancellationToken], T],
        timeout_sec: float = 3.0,
        fallback_value: T | None = None,
    ) -> tuple[bool, T | None, str | None]:
        """
        Execute task_fn passing a CancellationToken with hard timeout enforcement.
        Cancels the token upon timeout to prevent zombie execution.
        """
        token = CancellationToken()
        result: list[T | None] = [fallback_value]
        exc_holder: list[Exception | None] = [None]
        completed = threading.Event()

        def _target() -> None:
            try:
                result[0] = task_fn(token)
            except Exception as e:
                exc_holder[0] = e
            finally:
                token.confirm_stopped()
                completed.set()

        t = threading.Thread(target=_target, daemon=True)
        t.start()
        is_finished = completed.wait(timeout_sec)

        if not is_finished:
            token.cancel()
            return (
                False,
                fallback_value,
                f"Operation timed out after {timeout_sec:.2f} seconds; cancellation token triggered.",
            )

        if exc_holder[0] is not None:
            return False, fallback_value, str(exc_holder[0])

        return True, result[0], None
