"""
tests/test_inference_engine.py
==============================

Unit and regression tests for Phase 2A:
- Model Registry & Metadata SHA-256 validation.
- ModelIntegrityError on corrupted or modified weights.
- InferenceEngine hardware-adaptive execution and transparent CPU fallback.
- LatencyTracker P50, P95, P99 percentile calculations.
- Bounded queue with drop-oldest backpressure and request cancellation.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from concurrent.futures import Future

import numpy as np
import pytest

from camserv.inference.engine import (
    InferenceEngine,
    InferenceEngineConfig,
    InferenceRequest,
    InferenceResult,
    LatencyTracker,
)
from camserv.inference.models import (
    InferenceProvider,
    ModelIntegrityError,
    ModelMetadata,
    ModelNotFoundError,
    ModelRegistry,
    ModelTask,
)


@pytest.fixture
def temp_model_file():
    """Create a temporary model file and return its path and true SHA-256."""
    with tempfile.NamedTemporaryFile(suffix=".onnx", delete=False) as f:
        # Write dummy model weights
        f.write(b"MOCK_ONNX_MODEL_WEIGHTS_VERSION_1.0_DETERMINISTIC_BYTES")
        temp_path = f.name

    hasher = hashlib.sha256()
    with open(temp_path, "rb") as f:
        hasher.update(f.read())
    sha256 = hasher.hexdigest()

    yield temp_path, sha256

    if os.path.exists(temp_path):
        os.remove(temp_path)


def test_model_metadata_sha256_verification(temp_model_file):
    """Test that ModelMetadata correctly verifies matching SHA-256 and rejects altered files."""
    path, true_hash = temp_model_file

    meta = ModelMetadata(
        name="yolov8n-seg",
        version="1.0.0",
        task=ModelTask.INSTANCE_SEGMENTATION,
        framework="onnx",
        file_path=path,
        input_shape=(1, 3, 640, 640),
        output_shape=[(1, 116, 8400)],
        class_names=["person", "vehicle", "bicycle"],
        sha256_hash=true_hash,
        license="AGPL-3.0",
        provenance="Ultralytics / Local Export",
    )

    assert meta.verify_integrity() is True

    # Tamper with file
    with open(path, "ab") as f:
        f.write(b"CORRUPTED_BYTES")

    assert meta.verify_integrity() is False


def test_model_registry_integrity_rejection(temp_model_file):
    """Test that ModelRegistry refuses to register a model with incorrect SHA-256."""
    path, _ = temp_model_file
    registry = ModelRegistry()

    meta = ModelMetadata(
        name="tampered_model",
        version="1.0",
        task=ModelTask.OBJECT_DETECTION,
        framework="onnx",
        file_path=path,
        input_shape=(1, 3, 640, 640),
        output_shape=[(1, 84, 8400)],
        class_names=["person"],
        sha256_hash="0000000000000000000000000000000000000000000000000000000000000000",
        license="MIT",
        provenance="Test",
    )

    with pytest.raises(ModelIntegrityError):
        registry.register_model(meta, verify_immediately=True)


def test_latency_tracker_percentiles():
    """Test P50, P95, P99 calculation accuracy in LatencyTracker."""
    tracker = LatencyTracker(max_samples=100)

    # Insert 100 deterministic latency values: 1ms to 100ms
    for i in range(1, 101):
        tracker.record_latency(float(i))

    assert tracker.total_inferences == 100
    assert tracker.p50 == pytest.approx(50.0, abs=1.0)
    assert tracker.p95 == pytest.approx(95.0, abs=1.0)
    assert tracker.p99 == pytest.approx(99.0, abs=1.0)
    assert tracker.avg_ms == pytest.approx(50.5, abs=0.1)

    summary = tracker.get_summary()
    assert summary["total_inferences"] == 100
    assert summary["dropped_frames"] == 0
    assert summary["fallback_events"] == 0


def test_inference_engine_execution_and_fallback(temp_model_file):
    """Test InferenceEngine execution, synchronous inference, and forced fallback."""
    path, true_hash = temp_model_file
    registry = ModelRegistry()

    meta = ModelMetadata(
        name="test_detector",
        version="1.0",
        task=ModelTask.OBJECT_DETECTION,
        framework="onnx",
        file_path=path,
        input_shape=(1, 3, 640, 640),
        output_shape=[(1, 84, 8400)],
        class_names=["person", "car"],
        sha256_hash=true_hash,
        license="MIT",
        provenance="Test",
    )
    registry.register_model(meta)

    # Initialize engine with forced fallback simulation
    cfg = InferenceEngineConfig(
        model_name="test_detector",
        model_version="1.0",
        force_fallback_simulation=True,
    )
    engine = InferenceEngine(cfg, registry=registry)
    engine.initialize()

    assert engine.is_fallback_active is True
    assert engine.active_provider == InferenceProvider.CPU
    assert engine.tracker.fallback_events == 1

    # Run inference on synthetic frame
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    req = InferenceRequest(
        frame=dummy_frame,
        frame_id=1,
        camera_id="cam-01",
    )

    result = engine.execute_inference(req)
    assert result.status == "SUCCESS"
    assert result.frame_id == 1
    assert result.camera_id == "cam-01"
    assert len(result.detections) >= 1
    assert result.detections[0].is_prediction is True
    assert result.latency_ms > 0.0

    engine.stop()


def test_inference_engine_bounded_queue_backpressure(temp_model_file):
    """Test that bounded queue drops oldest requests when saturated without deadlock."""
    path, true_hash = temp_model_file
    registry = ModelRegistry()

    meta = ModelMetadata(
        name="test_queued_model",
        version="1.0",
        task=ModelTask.OBJECT_DETECTION,
        framework="onnx",
        file_path=path,
        input_shape=(1, 3, 640, 640),
        output_shape=[(1, 84, 8400)],
        class_names=["person"],
        sha256_hash=true_hash,
        license="MIT",
        provenance="Test",
    )
    registry.register_model(meta)

    # Max queue size 3, 1 worker thread
    cfg = InferenceEngineConfig(
        model_name="test_queued_model",
        model_version="1.0",
        max_queue_size=3,
        worker_threads=1,
    )
    engine = InferenceEngine(cfg, registry=registry)
    engine.initialize()

    dummy_frame = np.zeros((240, 320, 3), dtype=np.uint8)
    futures = []

    # Enqueue 10 items rapidly into queue of size 3
    for i in range(10):
        req = InferenceRequest(
            frame=dummy_frame,
            frame_id=i,
            camera_id="cam-01",
            priority=i,  # increasing priority
        )
        fut = engine.enqueue(req)
        futures.append(fut)

    # Wait for completion of all futures
    results = [f.result(timeout=2.0) for f in futures]
    engine.stop()

    # Verify that backpressure kicked in and dropped frames were counted
    dropped_count = sum(1 for r in results if r.status == "DROPPED")
    success_count = sum(1 for r in results if r.status == "SUCCESS")

    assert dropped_count > 0
    assert success_count > 0
    assert dropped_count + success_count == 10
    assert engine.tracker.dropped_frames == dropped_count
