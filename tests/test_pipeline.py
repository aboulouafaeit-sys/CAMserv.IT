"""Pipeline subsystem tests for CAMserv.

Verifies:
- Backpressure queues dropping oldest items when full
- Dropped item count telemetry
- PipelineEngine lifecycle (startup, shutdown, task teardown)
- DDSketch/log-bucketed latency metric accuracy (P50, P95, P99)
- Memory limit tracking and enforcement
- Stage error isolation (failure in one stage doesn't crash others)
- Priority queue item ordering (critical events bypass bulk frames)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from camserv.pipeline.backpressure import (
    BackpressureQueue,
    DropPolicy,
    PriorityItem,
)
from camserv.pipeline.engine import (
    EngineConfig,
    PipelineEngine,
    PipelineStatus,
)
from camserv.pipeline.interfaces import (
    BoundingBox,
    Detection,
    Event,
    EventSeverity,
    Frame,
    Track,
    TrackState,
)
from camserv.pipeline.metrics import (
    LatencyTracker,
    MemoryMonitor,
    MetricsRegistry,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_backpressure_queue_drops_oldest() -> None:
    """Verify that BackpressureQueue with DROP_OLDEST policy evicts the oldest item when full."""
    queue: BackpressureQueue[str] = BackpressureQueue(
        name="test_queue",
        maxsize=3,
        drop_policy=DropPolicy.DROP_OLDEST,
    )

    assert queue.is_empty
    assert queue.qsize == 0

    await queue.put("item_1")
    await queue.put("item_2")
    await queue.put("item_3")

    assert queue.is_full
    assert queue.qsize == 3

    # Enqueue 4th item; oldest ('item_1') must be dropped
    await queue.put("item_4")

    assert queue.qsize == 3
    assert queue.dropped_count == 1

    # Next item should be 'item_2'
    first_out = await queue.get(timeout=1.0)
    assert first_out == "item_2"

    second_out = await queue.get(timeout=1.0)
    assert second_out == "item_3"

    third_out = await queue.get(timeout=1.0)
    assert third_out == "item_4"

    assert queue.is_empty


@pytest.mark.unit
@pytest.mark.asyncio
async def test_backpressure_queue_tracks_dropped_count() -> None:
    """Verify that BackpressureQueue accurately records dropped item statistics across multiple drops."""
    queue: BackpressureQueue[int] = BackpressureQueue(
        name="stats_queue",
        maxsize=5,
        drop_policy=DropPolicy.DROP_OLDEST,
    )

    for i in range(15):
        await queue.put(i)

    # 15 puts into maxsize=5 -> exactly 10 dropped items
    assert queue.dropped_count == 10
    stats = queue.stats()
    assert stats.total_dropped == 10
    assert stats.total_enqueued == 15
    assert stats.current_depth == 5


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pipeline_engine_startup_shutdown() -> None:
    """Verify PipelineEngine launches all worker tasks cleanly and shuts down without leaking tasks."""
    engine = PipelineEngine(
        config=EngineConfig(raw_queue_size=10, decoded_queue_size=10),
    )

    status_before: PipelineStatus = engine.status()
    assert not status_before.is_running

    await engine.start()
    status_running: PipelineStatus = engine.status()
    assert status_running.is_running
    assert len(engine._tasks) > 0

    await engine.stop()
    status_stopped: PipelineStatus = engine.status()
    assert not status_stopped.is_running
    assert len(engine._tasks) == 0


@pytest.mark.unit
def test_pipeline_metrics_latency_tracking() -> None:
    """Verify LatencyTracker records observations and computes count, min, max, and mean."""
    tracker = LatencyTracker(name="test_inference_latency")

    tracker.record(10.0)
    tracker.record(20.0)
    tracker.record(30.0)

    assert tracker.count == 3
    assert tracker.min == pytest.approx(10.0)
    assert tracker.max == pytest.approx(30.0)
    assert tracker.mean == pytest.approx(20.0)


@pytest.mark.unit
def test_pipeline_metrics_p50_p95_p99_accuracy() -> None:
    """Verify DDSketch-based LatencyTracker approximates percentiles within relative error."""
    tracker = LatencyTracker(name="p99_accuracy_test", alpha=0.01)

    # Ingest 1000 uniform samples from 1 to 1000
    for val in range(1, 1001):
        tracker.record(float(val))

    p50 = tracker.p50
    p95 = tracker.p95
    p99 = tracker.p99

    # DDSketch is bounded within (1 +/- alpha)
    assert p50 == pytest.approx(500.0, rel=0.05)
    assert p95 == pytest.approx(950.0, rel=0.05)
    assert p99 == pytest.approx(990.0, rel=0.05)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pipeline_memory_limit_enforcement() -> None:
    """Verify MemoryMonitor correctly inspects RSS memory and reports threshold breaches."""
    monitor = MemoryMonitor()
    snap = monitor.snapshot()

    # Process RSS should be a positive float
    assert isinstance(snap.process_rss_mb, float)
    assert snap.process_rss_mb >= 0.0

    # Test engine memory check with artificially low limit
    low_config = EngineConfig(max_memory_mb=0.0001)
    engine = PipelineEngine(config=low_config)
    engine.raw_queue._buffer.append(
        Frame(
            image=np.zeros((10, 10, 3), dtype=np.uint8),
            camera_id="cam-mem",
            timestamp=datetime.now(timezone.utc),
            frame_id=1,
        )
    )
    assert engine.raw_queue.qsize == 1
    # Trigger memory safety check inside running async loop
    engine._check_memory_safety()
    # Allow scheduled clear task to run
    await asyncio.sleep(0.05)
    assert engine.raw_queue.qsize == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pipeline_stage_error_isolation() -> None:
    """Verify an exception in one stage (e.g. decoder) is caught and logged without crashing the engine."""
    # Mock decoder that raises an unexpected exception
    failing_decoder = MagicMock()
    failing_decoder.decode = AsyncMock(side_effect=RuntimeError("Corrupt frame bitstream"))

    engine = PipelineEngine(
        config=EngineConfig(raw_queue_size=10, decoded_queue_size=10),
        decoder=failing_decoder,
    )

    await engine.start()

    # Put a dummy frame into raw_queue
    frame = Frame(
        image=np.zeros((10, 10, 3), dtype=np.uint8),
        camera_id="cam-fault",
        timestamp=datetime.now(timezone.utc),
        frame_id=1,
    )
    await engine.raw_queue.put(frame)

    # Allow processing loop to handle and log the failure
    await asyncio.sleep(0.1)

    # PipelineEngine must still be alive and running despite the stage error
    assert engine.status().is_running

    await engine.stop()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_queue_priority_items() -> None:
    """Verify BackpressureQueue with priority returns high priority items (lower int) first."""
    p_queue: BackpressureQueue[str] = BackpressureQueue(
        name="priority_queue",
        maxsize=10,
        enable_priority=True,
    )

    # Enqueue low priority (e.g. regular frame = 10)
    await p_queue.put("bulk_frame_1", priority=10)
    await p_queue.put("bulk_frame_2", priority=10)

    # Enqueue high priority (e.g. critical security alert = 0)
    await p_queue.put("critical_alert_event", priority=0)

    # High priority item must be dequeued first
    first_item = await p_queue.get(timeout=1.0)
    assert first_item == "critical_alert_event"

    second_item = await p_queue.get(timeout=1.0)
    assert second_item == "bulk_frame_1"

    third_item = await p_queue.get(timeout=1.0)
    assert third_item == "bulk_frame_2"
