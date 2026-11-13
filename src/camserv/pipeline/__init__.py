"""
camserv.pipeline
================

Core asynchronous video analytics pipeline infrastructure.
"""

from __future__ import annotations

from camserv.pipeline.backpressure import (
    BackpressureQueue,
    DropPolicy,
    PriorityItem,
    QueueStats,
)
from camserv.pipeline.engine import (
    DecodedPayload,
    EngineConfig,
    InferencePayload,
    PipelineEngine,
    PipelineStatus,
    StoragePayload,
    TrackingPayload,
)
from camserv.pipeline.interfaces import (
    Alert,
    AlertStatus,
    BoundingBox,
    Detection,
    Event,
    EventDetector,
    EventSeverity,
    Frame,
    FrameAcquisitionError,
    FrameDecoder,
    FrameSource,
    InferenceError,
    ObjectDetector,
    ObjectTracker,
    PipelineError,
    PrivacyFilter,
    StorageBackend,
    StorageError,
    Track,
    TrackingError,
    TrackState,
)
from camserv.pipeline.metrics import (
    BenchmarkResult,
    LatencyTracker,
    MemoryMonitor,
    MemorySnapshot,
    MetricsRegistry,
    QueueDepthMonitor,
    ThroughputCounter,
    run_benchmark,
)

__all__ = [
    # Interfaces & Dataclasses
    "Alert",
    "AlertStatus",
    "BoundingBox",
    "Detection",
    "Event",
    "EventDetector",
    "EventSeverity",
    "Frame",
    "FrameAcquisitionError",
    "FrameDecoder",
    "FrameSource",
    "InferenceError",
    "ObjectDetector",
    "ObjectTracker",
    "PipelineError",
    "PrivacyFilter",
    "StorageBackend",
    "StorageError",
    "Track",
    "TrackingError",
    "TrackState",
    # Engine & Configuration
    "DecodedPayload",
    "EngineConfig",
    "InferencePayload",
    "PipelineEngine",
    "PipelineStatus",
    "StoragePayload",
    "TrackingPayload",
    # Backpressure & Queues
    "BackpressureQueue",
    "DropPolicy",
    "PriorityItem",
    "QueueStats",
    # Metrics
    "BenchmarkResult",
    "LatencyTracker",
    "MemoryMonitor",
    "MemorySnapshot",
    "MetricsRegistry",
    "QueueDepthMonitor",
    "ThroughputCounter",
    "run_benchmark",
]
