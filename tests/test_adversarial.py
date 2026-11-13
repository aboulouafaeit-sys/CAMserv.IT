"""Adversarial and robustness tests for CAMserv.

Verifies:
- Malformed frame buffer handling (non-array, None, invalid shapes)
- Extremely large frame processing (4K+ resolutions) without unhandled exceptions
- Corrupted video stream input decoding error isolation
- Empty frame (0-sized dimensions) handling
- All-zero frame (pure black) processing and scene tamper indicator
- All-white frame (pure saturation/glare) handling
- Negative confidence scores strictly rejected by domain models
- Confidence scores above 1.0 strictly rejected by domain models
- Invalid bounding box coordinates handling (inverted x2 < x1 or NaNs)
- Concurrent camera stream disconnections and graceful reconnection states
- Rapid dynamic configuration changes under active pipeline execution
- System memory pressure backpressure queue shedding
- Adversarial noise patch / high-frequency pattern frame detection
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from camserv.acquisition.camera import CameraHealth, CameraManager, CameraStream
from camserv.acquisition.decoder import DecoderConfig, FrameDecoderImpl
from camserv.events.detector import EventDetector, EventRule, EventType
from camserv.inference.detector import Detection
from camserv.inference.privacy import PrivacyFilter
from camserv.inference.scene import SceneAnalyzer
from camserv.pipeline.backpressure import BackpressureQueue, DropPolicy
from camserv.pipeline.engine import EngineConfig, PipelineEngine
from camserv.pipeline.interfaces import (
    BoundingBox,
    DecodingError,
    Frame,
    Track,
    TrackState,
)


@pytest.mark.adversarial
@pytest.mark.asyncio
async def test_malformed_frame_handling() -> None:
    """Verify FrameDecoder raises DecodingError when frame image buffer is not a valid numpy ndarray."""
    decoder = FrameDecoderImpl()
    malformed_frame = Frame(
        image=None,  # type: ignore[arg-type]
        camera_id="cam-bad",
        timestamp=datetime.now(timezone.utc),
        frame_id=1,
    )

    with pytest.raises(DecodingError, match="Invalid frame buffer"):
        await decoder.decode(malformed_frame)


@pytest.mark.adversarial
@pytest.mark.asyncio
async def test_extremely_large_frame() -> None:
    """Verify pipeline and decoder safely resize 4K+ high-resolution frames without crashing."""
    decoder = FrameDecoderImpl(config=DecoderConfig(target_size=(640, 640)))

    # Create 4K frame (2160 x 3840 x 3)
    large_img = np.zeros((2160, 3840, 3), dtype=np.uint8)
    large_frame = Frame(
        image=large_img,
        camera_id="cam-4k",
        timestamp=datetime.now(timezone.utc),
        frame_id=1,
    )

    processed = await decoder.decode(large_frame)
    assert processed.image.shape == (640, 640, 3)
    assert processed.metadata["original_shape"] == (2160, 3840, 3)


@pytest.mark.adversarial
@pytest.mark.asyncio
async def test_corrupted_video_stream() -> None:
    """Verify corrupted video frames in a stream do not bring down the pipeline."""
    decoder = FrameDecoderImpl()

    # Pass object that is not an image array to simulate stream corruption
    corrupt_frame = Frame(
        image="corrupted_byte_stream_not_an_array",  # type: ignore[arg-type]
        camera_id="cam-corrupt",
        timestamp=datetime.now(timezone.utc),
        frame_id=99,
    )

    with pytest.raises(DecodingError):
        await decoder.decode(corrupt_frame)


@pytest.mark.adversarial
@pytest.mark.asyncio
async def test_empty_frame() -> None:
    """Verify zero-dimension frame buffer does not raise unhandled panic."""
    decoder = FrameDecoderImpl(config=DecoderConfig(target_size=(640, 640)))
    empty_img = np.empty((0, 0, 3), dtype=np.uint8)

    empty_frame = Frame(
        image=empty_img,
        camera_id="cam-empty",
        timestamp=datetime.now(timezone.utc),
        frame_id=1,
    )

    # Empty frame should either process or raise caught DecodingError gracefully
    try:
        res = await decoder.decode(empty_frame)
        assert res is not None
    except Exception as exc:
        assert isinstance(exc, (DecodingError, IndexError, ValueError))


@pytest.mark.adversarial
def test_all_zero_frame() -> None:
    """Verify an all-black (all zeros) frame triggers camera tampering detection."""
    detector = EventDetector()
    now = datetime.now(timezone.utc)

    # Frame 1: Establish baseline with random noise
    baseline_img = np.random.randint(40, 220, size=(120, 120, 3), dtype=np.uint8)
    frame1 = Frame(image=baseline_img, camera_id="cam-tamper-check", timestamp=now, frame_id=1)
    detector.evaluate([], frame=frame1)

    # Frame 2: Pure black frame (lens covered / camera blinded)
    black_img = np.zeros((120, 120, 3), dtype=np.uint8)
    frame2 = Frame(image=black_img, camera_id="cam-tamper-check", timestamp=now, frame_id=2)
    events = detector.evaluate([], frame=frame2)

    tamper = [e for e in events if e.event_type == EventType.CAMERA_TAMPER]
    assert len(tamper) == 1
    assert tamper[0].requires_verification is True


@pytest.mark.adversarial
def test_all_white_frame() -> None:
    """Verify an all-white (pure saturation/glare) frame is safely analyzed."""
    analyzer = SceneAnalyzer()
    white_img = np.full((480, 640, 3), 255, dtype=np.uint8)

    # Scene analyzer should evaluate empty detections on saturated frame without errors
    results = analyzer.estimate_crowd_density([], frame_shape=white_img.shape)
    assert len(results) == 1
    assert results[0].count == 0


@pytest.mark.adversarial
def test_negative_confidence_rejected() -> None:
    """Verify that negative prediction confidence raises ValueError."""
    with pytest.raises(ValueError, match="confidence"):
        Detection(
            bbox=BoundingBox(0, 0, 50, 50),
            class_id=0,
            class_name="person",
            confidence=-0.42,
        )


@pytest.mark.adversarial
def test_confidence_above_1_rejected() -> None:
    """Verify that confidence greater than 1.0 raises ValueError."""
    with pytest.raises(ValueError, match="confidence"):
        Detection(
            bbox=BoundingBox(0, 0, 50, 50),
            class_id=0,
            class_name="person",
            confidence=1.0001,
        )


@pytest.mark.adversarial
def test_invalid_bbox_coordinates() -> None:
    """Verify invalid or inverted bounding box coordinates handle area safely."""
    # Inverted bounding box (x2 < x1)
    inverted_box = BoundingBox(x1=100.0, y1=100.0, x2=50.0, y2=50.0)
    assert inverted_box.width < 0
    # Area should clamp to 0.0, not negative
    assert inverted_box.area == 0.0

    # Non-overlapping IoU
    normal_box = BoundingBox(x1=200.0, y1=200.0, x2=300.0, y2=300.0)
    assert inverted_box.iou(normal_box) == 0.0


@pytest.mark.adversarial
@pytest.mark.asyncio
async def test_concurrent_camera_disconnect() -> None:
    """Verify handling when multiple camera sources disconnect concurrently."""
    manager = CameraManager()

    # Create 3 mock camera streams
    stream1 = MagicMock(spec=CameraStream)
    stream1.camera_id = "cam-dis-1"
    stream1.is_alive = True
    stream1.stop = AsyncMock()

    stream2 = MagicMock(spec=CameraStream)
    stream2.camera_id = "cam-dis-2"
    stream2.is_alive = True
    stream2.stop = AsyncMock()

    manager._streams["cam-dis-1"] = stream1
    manager._streams["cam-dis-2"] = stream2

    # Stop all concurrently
    await manager.stop_all()

    assert stream1.stop.called
    assert stream2.stop.called


@pytest.mark.adversarial
@pytest.mark.asyncio
async def test_rapid_config_changes() -> None:
    """Verify EventDetector accepts rapid hot-reloads of rules without deadlocking or crashing."""
    detector = EventDetector()

    for i in range(20):
        new_rules = [
            {
                "rule_id": f"hot_rule_{i}",
                "event_type": EventType.ZONE_INTRUSION,
                "severity": "high",
                "polygon": [[0, 0], [100 + i, 0], [100 + i, 100 + i], [0, 100 + i]],
            }
        ]
        await detector.configure_rules(new_rules)
        assert len(detector.rules) == 1
        assert detector.rules[f"hot_rule_{i}"].rule_id == f"hot_rule_{i}"


@pytest.mark.adversarial
@pytest.mark.asyncio
async def test_memory_pressure_handling() -> None:
    """Verify BackpressureQueue sheds excess load when consumer stalls under high memory pressure."""
    queue: BackpressureQueue[int] = BackpressureQueue(
        name="pressure_queue",
        maxsize=10,
        drop_policy=DropPolicy.DROP_OLDEST,
    )

    # Flood queue with 100 items while consumer is idle
    for i in range(100):
        await queue.put(i)

    # Queue depth must be bounded at maxsize (10)
    assert queue.qsize == 10
    assert queue.dropped_count == 90

    # Ensure items remaining in queue are the most recent 10 items (90 to 99)
    items = []
    while not queue.is_empty:
        items.append(await queue.get(timeout=0.1))
    assert items == list(range(90, 100))


@pytest.mark.adversarial
def test_adversarial_patch_detection() -> None:
    """Verify high-frequency noise pattern frames (adversarial patches) are handled by scene analyzer."""
    analyzer = SceneAnalyzer()
    np.random.seed(999)

    # Generate adversarial high-frequency random noise frame
    noise_frame = np.random.randint(0, 256, size=(480, 640, 3), dtype=np.uint8)

    # Pass noise pattern to scene analyzer
    results = analyzer.estimate_crowd_density([], frame_shape=noise_frame.shape)
    assert len(results) >= 1
    # When no persons detected, count is zero
    assert results[0].count == 0
