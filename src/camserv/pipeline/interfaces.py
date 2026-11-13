"""
camserv.pipeline.interfaces
============================

Protocol classes and core dataclasses defining all module interfaces for the
CAMserv Advanced Security Intelligence Platform.

Every pluggable component (detector, tracker, storage backend, etc.) MUST
implement the corresponding Protocol so the pipeline engine can treat them
uniformly.  All predictions carry an explicit ``is_prediction`` flag and a
confidence score so downstream consumers can distinguish verified facts from
model outputs.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Protocol, runtime_checkable

try:
    import numpy as np
except ImportError:
    class _MockNDArray:
        shape: tuple[int, ...] = (0, 0, 0)
        nbytes: int = 0
    class _MockNumpy:  # type: ignore[no-redef]
        ndarray = _MockNDArray
    np = _MockNumpy()  # type: ignore[assignment]



# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class TrackState(enum.Enum):
    """Lifecycle state of an object track."""

    TENTATIVE = "tentative"
    CONFIRMED = "confirmed"
    LOST = "lost"
    DELETED = "deleted"


class EventSeverity(enum.Enum):
    """Severity level for detected events."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertStatus(enum.Enum):
    """Status of an alert through its lifecycle."""

    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    VERIFIED = "verified"
    DISMISSED = "dismissed"
    ESCALATED = "escalated"


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------

class PipelineError(Exception):
    """Base exception for all pipeline errors."""


class FrameAcquisitionError(PipelineError):
    """Error acquiring a frame from a source."""


class DecodingError(PipelineError):
    """Error decoding raw bytes into an image array."""


class InferenceError(PipelineError):
    """Error running detection inference."""


class TrackingError(PipelineError):
    """Error updating object tracks."""


class StorageError(PipelineError):
    """Error persisting or retrieving data."""


class BackpressureError(PipelineError):
    """Backpressure limit exceeded; frame dropped."""


class PrivacyFilterError(PipelineError):
    """Error applying privacy masking."""


# ---------------------------------------------------------------------------
# Core Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class BoundingBox:
    """Axis-aligned bounding box in pixel coordinates (x1, y1, x2, y2)."""

    x1: float
    y1: float
    x2: float
    y2: float

    def __getitem__(self, idx: int) -> float:
        if idx in (0, -4):
            return self.x1
        elif idx in (1, -3):
            return self.y1
        elif idx in (2, -2):
            return self.x2
        elif idx in (3, -1):
            return self.y2
        raise IndexError(f"BoundingBox index out of range: {idx}")

    def __iter__(self):
        yield self.x1
        yield self.y1
        yield self.x2
        yield self.y2

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    def iou(self, other: BoundingBox) -> float:
        """Compute Intersection over Union with *other*."""
        xi1 = max(self.x1, other.x1)
        yi1 = max(self.y1, other.y1)
        xi2 = min(self.x2, other.x2)
        yi2 = min(self.y2, other.y2)
        inter = max(0.0, xi2 - xi1) * max(0.0, yi2 - yi1)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0


@dataclass(slots=True)
class Frame:
    """A single video frame flowing through the pipeline.

    Attributes:
        image: Raw image data as a NumPy array (H, W, C) in BGR colour order.
        camera_id: Unique identifier for the source camera.
        timestamp: UTC capture time.
        frame_id: Monotonically increasing sequence number per camera.
        metadata: Arbitrary key/value metadata attached by pipeline stages.
    """

    image: np.ndarray
    camera_id: str
    timestamp: datetime
    frame_id: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def shape(self) -> tuple[int, ...]:
        return getattr(self.image, "shape", (0, 0, 0))

    @property
    def nbytes(self) -> int:
        """Memory footprint of the image buffer."""
        return getattr(self.image, "nbytes", 0)


@dataclass(slots=True)
class Detection:
    """A single object detection produced by an :class:`ObjectDetector`.

    Every detection is explicitly labelled as a *prediction* so downstream
    consumers never confuse model output with verified ground truth.
    """

    bbox: BoundingBox
    class_id: int
    class_name: str
    confidence: float
    camera_id: str
    frame_id: int
    timestamp: datetime
    is_prediction: bool = True
    embedding: np.ndarray | None = None
    polygon: list[tuple[float, float]] | None = None
    keypoints: list[tuple[float, float, float]] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Track:
    """An object track maintained by an :class:`ObjectTracker`.

    Tracks aggregate detections over time and carry lifecycle state so the
    event detector can reason about object behaviour.
    """

    track_id: int
    bbox: BoundingBox
    class_name: str
    class_id: int
    confidence: float
    age: int  # frames since first detection
    state: TrackState
    camera_id: str
    velocity: tuple[float, float] = (0.0, 0.0)
    trajectory: list[tuple[float, float]] = field(default_factory=list)
    last_seen: datetime | None = None
    polygon: list[tuple[float, float]] | None = None
    keypoints: list[tuple[float, float, float]] | None = None
    threat_score: float = 0.0
    threat_state: str = "normal"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Event:
    """A security event detected by an :class:`EventDetector`.

    Events that require human verification MUST set ``requires_verification``
    to ``True`` so the alert subsystem routes them for human-in-the-loop
    review before any consequential action is taken.
    """

    event_id: str
    event_type: str
    severity: EventSeverity
    confidence: float
    camera_id: str
    timestamp: datetime
    requires_verification: bool
    description: str
    related_track_ids: list[int] = field(default_factory=list)
    related_detections: list[Detection] = field(default_factory=list)
    zone_id: str | None = None
    is_prediction: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Alert:
    """An alert surfaced to operators based on one or more :class:`Event` instances.

    Alerts carry their own lifecycle status and audit trail so every
    consequential decision is logged.
    """

    alert_id: str
    events: list[Event]
    severity: EventSeverity
    status: AlertStatus
    created_at: datetime
    updated_at: datetime
    assigned_to: str | None = None
    verified_by: str | None = None
    notes: str = ""
    requires_human_review: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Protocol Interfaces
# ---------------------------------------------------------------------------

@runtime_checkable
class FrameSource(Protocol):
    """Async iterator that yields :class:`Frame` objects from a camera or
    video file.  Implementations handle connection management, reconnection
    and frame sequencing internally.
    """

    async def start(self) -> None:
        """Open the source and begin producing frames."""
        ...

    async def stop(self) -> None:
        """Gracefully close the source and release resources."""
        ...

    def __aiter__(self) -> AsyncIterator[Frame]:
        ...

    async def __anext__(self) -> Frame:
        ...

    @property
    def camera_id(self) -> str:
        """Return the unique camera identifier for this source."""
        ...

    @property
    def is_alive(self) -> bool:
        """``True`` while the source is connected and producing frames."""
        ...


@runtime_checkable
class FrameDecoder(Protocol):
    """Decodes and pre-processes raw frame data for downstream inference."""

    async def decode(
        self,
        frame: Frame,
        target_size: tuple[int, int] | None = None,
    ) -> Frame:
        """Decode *frame*, optionally resizing to *target_size* ``(W, H)``.

        Returns a **new** :class:`Frame` whose ``image`` is the processed
        result.  The original frame must not be mutated.
        """
        ...

    async def batch_decode(
        self,
        frames: list[Frame],
        target_size: tuple[int, int] | None = None,
    ) -> list[Frame]:
        """Decode a batch of frames.  Default implementations may simply
        loop over :meth:`decode`.
        """
        ...


@runtime_checkable
class ObjectDetector(Protocol):
    """Runs object detection on decoded frames and returns a list of
    :class:`Detection` instances.  All results MUST have
    ``is_prediction=True``.
    """

    async def detect(self, frame: Frame) -> list[Detection]:
        """Run inference on a single *frame*."""
        ...

    async def detect_batch(self, frames: list[Frame]) -> list[list[Detection]]:
        """Run inference on a batch of frames."""
        ...

    @property
    def model_name(self) -> str:
        """Human-readable model identifier."""
        ...

    @property
    def class_names(self) -> list[str]:
        """Ordered list of class names the model can detect."""
        ...

    async def warmup(self) -> None:
        """Run a dummy inference pass to initialize the model."""
        ...


@runtime_checkable
class ObjectTracker(Protocol):
    """Maintains object tracks across frames, associating new detections
    with existing tracks and managing track lifecycle.
    """

    async def update(
        self,
        detections: list[Detection],
        frame: Frame,
    ) -> list[Track]:
        """Incorporate *detections* from *frame* and return updated tracks.

        Tracks that have not been matched for a configurable number of
        frames should transition to ``TrackState.LOST`` and eventually
        ``TrackState.DELETED``.
        """
        ...

    async def reset(self) -> None:
        """Clear all active tracks."""
        ...

    @property
    def active_tracks(self) -> list[Track]:
        """Currently active (TENTATIVE or CONFIRMED) tracks."""
        ...


@runtime_checkable
class EventDetector(Protocol):
    """Evaluates high-level rules against tracks and detections to produce
    :class:`Event` instances.

    Events with ``severity >= HIGH`` MUST set ``requires_verification=True``
    so a human can confirm before any action is taken.
    """

    async def evaluate(
        self,
        tracks: list[Track],
        detections: list[Detection],
        frame: Frame,
    ) -> list[Event]:
        """Evaluate rules and return any newly triggered events."""
        ...

    async def configure_rules(self, rules: list[dict[str, Any]]) -> None:
        """Hot-reload detection rules without restarting the pipeline."""
        ...


@runtime_checkable
class StorageBackend(Protocol):
    """Persists and retrieves detections, events, analytics data and alert
    records.  Implementations may target Redis, PostgreSQL, Milvus, or any
    combination.
    """

    async def store_detections(
        self,
        detections: list[Detection],
    ) -> None:
        """Persist a batch of detections."""
        ...

    async def store_event(self, event: Event) -> None:
        """Persist a single event."""
        ...

    async def store_alert(self, alert: Alert) -> None:
        """Persist or update an alert record."""
        ...

    async def query_events(
        self,
        camera_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        severity: EventSeverity | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """Query stored events with optional filters."""
        ...

    async def query_detections(
        self,
        camera_id: str | None = None,
        class_name: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> list[Detection]:
        """Query stored detections with optional filters."""
        ...

    async def store_analytics(
        self,
        camera_id: str,
        data: dict[str, Any],
    ) -> None:
        """Store aggregated analytics data."""
        ...

    async def health_check(self) -> bool:
        """Return ``True`` if the backend is reachable and operational."""
        ...


@runtime_checkable
class PrivacyFilter(Protocol):
    """Applies privacy-preserving transformations to frames before storage
    or display.

    Implementations MUST ensure personally identifiable regions (faces,
    licence plates) are irreversibly masked when configured to do so.
    """

    async def apply(
        self,
        frame: Frame,
        detections: list[Detection],
    ) -> Frame:
        """Return a **new** :class:`Frame` with privacy masks applied.

        The original *frame* MUST NOT be modified in place.
        """
        ...

    async def configure(self, settings: dict[str, Any]) -> None:
        """Update privacy filter settings at runtime."""
        ...
