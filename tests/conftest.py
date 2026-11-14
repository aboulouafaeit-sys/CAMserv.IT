"""CAMserv test suite shared fixtures and configuration.

Provides standard test fixtures for:
- Video frames, detections, tracks, events, and alerts
- Mock configurations (camera, inference, tracking, storage, security)
- Temporary filesystem directories for evidence and audit logs
- Mock backends for Redis and Milvus
- Platform settings
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Generator
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

# Ensure src directory is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from camserv.config.settings import (
    CamerasSettings,
    CameraSource,
    CamservSettings,
    EventRule,
    EventsSettings,
    InferenceDevice,
    InferenceSettings,
    JWTSettings,
    MilvusSettings,
    PipelineSettings,
    PrivacySettings,
    PrivacyZone,
    RBACRole,
    RedisSettings,
    SecuritySettings,
    StorageSettings,
    TrackingAlgorithm,
    TrackingSettings,
)
from camserv.inference.privacy import PrivacyConfig
from camserv.pipeline.interfaces import (
    Alert,
    AlertStatus,
    BoundingBox,
    Detection,
    Event,
    EventSeverity,
    Frame,
    Track,
    TrackState,
)


# ---------------------------------------------------------------------------
# Core Dataclass Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_frame() -> Frame:
    """Fixture providing a standard test Frame with 640x480x3 BGR image."""
    np.random.seed(42)
    # 480 height, 640 width, 3 channels
    image = np.random.randint(0, 256, size=(480, 640, 3), dtype=np.uint8)
    return Frame(
        image=image,
        camera_id="cam-test-01",
        timestamp=datetime.now(timezone.utc),
        frame_id=101,
        metadata={"source": "test_generator", "resolution": (640, 480)},
    )


@pytest.fixture
def sample_detections() -> list[Detection]:
    """Fixture providing a list of Detection objects with varying confidence and classes.

    CRITICAL: All detections must carry is_prediction=True and valid confidence [0, 1].
    """
    now = datetime.now(timezone.utc)
    return [
        Detection(
            bbox=BoundingBox(x1=50.0, y1=60.0, x2=150.0, y2=200.0),
            class_id=0,
            class_name="person",
            confidence=0.92,
            camera_id="cam-test-01",
            frame_id=101,
            timestamp=now,
            is_prediction=True,
            metadata={"zone": "entry_gate"},
        ),
        Detection(
            bbox=BoundingBox(x1=200.0, y1=150.0, x2=380.0, y2=320.0),
            class_id=2,
            class_name="car",
            confidence=0.78,
            camera_id="cam-test-01",
            frame_id=101,
            timestamp=now,
            is_prediction=True,
            metadata={"zone": "parking"},
        ),
        Detection(
            bbox=BoundingBox(x1=400.0, y1=100.0, x2=480.0, y2=250.0),
            class_id=0,
            class_name="person",
            confidence=0.45,
            camera_id="cam-test-01",
            frame_id=101,
            timestamp=now,
            is_prediction=True,
            metadata={"zone": "perimeter"},
        ),
    ]


@pytest.fixture
def sample_tracks() -> list[Track]:
    """Fixture providing a list of Track objects with anonymous IDs and various states."""
    now = datetime.now(timezone.utc)
    return [
        Track(
            track_id=1001,  # Strictly anonymous integer ID
            bbox=BoundingBox(x1=50.0, y1=60.0, x2=150.0, y2=200.0),
            class_name="person",
            class_id=0,
            confidence=0.91,
            age=15,
            state=TrackState.CONFIRMED,
            camera_id="cam-test-01",
            velocity=(1.2, 0.5),
            trajectory=[(50.0, 60.0), (51.2, 60.5)],
            last_seen=now,
        ),
        Track(
            track_id=1002,  # Strictly anonymous integer ID
            bbox=BoundingBox(x1=200.0, y1=150.0, x2=380.0, y2=320.0),
            class_name="car",
            class_id=2,
            confidence=0.82,
            age=2,
            state=TrackState.TENTATIVE,
            camera_id="cam-test-01",
            velocity=(0.0, 0.0),
            trajectory=[(200.0, 150.0)],
            last_seen=now,
        ),
    ]


@pytest.fixture
def sample_events() -> list[Event]:
    """Fixture providing a list of Event objects with different severities.

    CRITICAL: High and critical severity events must require human verification.
    """
    now = datetime.now(timezone.utc)
    return [
        Event(
            event_id="evt-info-01",
            event_type="zone_entry",
            severity=EventSeverity.INFO,
            confidence=0.88,
            camera_id="cam-test-01",
            timestamp=now,
            requires_verification=False,
            description="Person entered public lobby zone",
            related_track_ids=[1001],
            is_prediction=True,
        ),
        Event(
            event_id="evt-med-01",
            event_type="loitering",
            severity=EventSeverity.MEDIUM,
            confidence=0.74,
            camera_id="cam-test-01",
            timestamp=now,
            requires_verification=False,
            description="Person lingering near outer gate for 60s",
            related_track_ids=[1001],
            is_prediction=True,
        ),
        Event(
            event_id="evt-high-01",
            event_type="intrusion",
            severity=EventSeverity.HIGH,
            confidence=0.94,
            camera_id="cam-test-01",
            timestamp=now,
            requires_verification=True,  # High severity REQUIRES human verification
            description="Intrusion detected in restricted server room",
            related_track_ids=[1001],
            is_prediction=True,
        ),
        Event(
            event_id="evt-crit-01",
            event_type="fall_detection",
            severity=EventSeverity.CRITICAL,
            confidence=0.96,
            camera_id="cam-test-01",
            timestamp=now,
            requires_verification=True,  # Critical severity REQUIRES human verification
            description="Person fallen and stationary in stairwell",
            related_track_ids=[1001],
            is_prediction=True,
        ),
    ]


# ---------------------------------------------------------------------------
# Configuration Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_camera_config() -> CameraSource:
    """Fixture for single camera source configuration."""
    return CameraSource(
        id="cam-test-01",
        name="Test Camera North",
        url="rtsp://127.0.0.1:8554/live/north",
        enabled=True,
        fps=15,
        resolution=(1920, 1080),
        codec="h264",
        retry_interval_s=2.0,
        max_retries=5,
        zones=["zone_entry", "zone_perimeter"],
    )


@pytest.fixture
def mock_inference_config() -> InferenceSettings:
    """Fixture for inference settings with CPU default for tests."""
    return InferenceSettings(
        device=InferenceDevice.CPU,
        model_path=Path("models/yolov8n.onnx"),
        confidence_threshold=0.45,
        nms_iou_threshold=0.50,
        max_batch_size=2,
        input_size=(640, 640),
        half_precision=False,  # FP16 disabled on CPU
        warmup_iterations=0,
    )


@pytest.fixture
def mock_tracking_config() -> TrackingSettings:
    """Fixture for tracking settings."""
    return TrackingSettings(
        algorithm=TrackingAlgorithm.BYTETRACK,
        max_age=30,
        min_hits=3,
        iou_threshold=0.3,
        max_tracks=100,
        embedding_dim=128,
    )


@pytest.fixture
def mock_privacy_config() -> PrivacySettings:
    """Fixture for privacy settings."""
    return PrivacySettings(
        face_blur_strength=25,
        auto_purge_enabled=True,
        data_retention_hours=24,
        video_retention_hours=24,
        gdpr_erasure_enabled=True,
        log_access_requests=True,
    )


@pytest.fixture
def platform_settings(tmp_path: Path) -> CamservSettings:
    """Fixture providing complete CamservSettings suitable for test environment."""
    return CamservSettings(
        environment="development",
        debug=True,
        cameras=CamerasSettings(
            sources=[
                CameraSource(
                    id="cam-01",
                    name="Test Camera 1",
                    url="rtsp://localhost:8554/cam1",
                )
            ]
        ),
        inference=InferenceSettings(
            device=InferenceDevice.CPU,
            half_precision=False,
            confidence_threshold=0.4,
            nms_iou_threshold=0.45,
        ),
        tracking=TrackingSettings(
            algorithm=TrackingAlgorithm.BYTETRACK,
            max_age=30,
            min_hits=2,
            embedding_dim=128,
        ),
        events=EventsSettings(
            human_review_default=True,
            rules=[
                EventRule(
                    id="rule-test-01",
                    name="Perimeter Breach",
                    event_type="intrusion",
                    severity="high",
                    require_human_review=True,
                    min_confidence=0.7,
                )
            ],
        ),
        privacy=PrivacySettings(
            data_retention_hours=48,
            video_retention_hours=24,
        ),
        storage=StorageSettings(
            redis=RedisSettings(host="127.0.0.1", port=6379),
            milvus=MilvusSettings(host="127.0.0.1", port=19530, dim=128),
            video_archive_path=tmp_path / "videos",
            snapshot_path=tmp_path / "snapshots",
        ),
        security=SecuritySettings(
            jwt=JWTSettings(
                secret_key="unit-test-secret-key-that-is-at-least-32-chars-long",
                access_token_expire_minutes=15,
            ),
            audit_log_path=tmp_path / "audit.jsonl",
        ),
        pipeline=PipelineSettings(
            max_pipeline_latency_ms=150,
            inference_timeout_ms=50,
            queue_backpressure_limit=50,
        ),
    )


# ---------------------------------------------------------------------------
# Storage & Temporary Directory Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_evidence_dir(tmp_path: Path) -> Path:
    """Fixture providing a temporary directory for evidence tamper tests."""
    evidence_dir = tmp_path / "evidence_store"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    return evidence_dir


@pytest.fixture
def tmp_audit_log_path(tmp_path: Path) -> Path:
    """Fixture providing a temporary file path for audit logs."""
    return tmp_path / "audit_test.jsonl"


@pytest.fixture(autouse=True, scope="session")
def isolate_session_audit_log(tmp_path_factory: pytest.TempPathFactory) -> Generator[Path, None, None]:
    """Isolate all test audit logging to an ephemeral temporary directory (Condition C1)."""
    temp_dir = tmp_path_factory.mktemp("camserv_test_audit")
    temp_log = temp_dir / "audit.jsonl"
    old_env = os.environ.get("CAMSERV_SECURITY__AUDIT_LOG_PATH")
    os.environ["CAMSERV_SECURITY__AUDIT_LOG_PATH"] = str(temp_log)
    try:
        yield temp_log
    finally:
        if old_env is not None:
            os.environ["CAMSERV_SECURITY__AUDIT_LOG_PATH"] = old_env
        else:
            os.environ.pop("CAMSERV_SECURITY__AUDIT_LOG_PATH", None)


# ---------------------------------------------------------------------------
# Mock External Dependencies (Redis, Milvus, Camera)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_redis() -> MagicMock:
    """Mock Redis client supporting get/set/delete/expire with in-memory dict."""
    store: dict[str, Any] = {}
    mock = MagicMock()

    async def _async_get(key: str) -> Any:
        return store.get(key)

    async def _async_set(key: str, value: Any, ex: int | None = None) -> bool:
        store[key] = value
        return True

    async def _async_delete(*keys: str) -> int:
        count = 0
        for k in keys:
            if k in store:
                del store[k]
                count += 1
        return count

    mock.get = AsyncMock(side_effect=_async_get)
    mock.set = AsyncMock(side_effect=_async_set)
    mock.delete = AsyncMock(side_effect=_async_delete)
    mock.ping = AsyncMock(return_value=True)
    mock.raw_store = store
    return mock


@pytest.fixture
def mock_milvus() -> MagicMock:
    """Mock Milvus client that rejects biometric/PII data and stores anonymous analytics."""
    mock = MagicMock()
    stored_vectors: list[dict[str, Any]] = []

    def _insert(collection_name: str, entities: list[dict[str, Any]]) -> list[int]:
        for entity in entities:
            # Enforce NO PII check
            for forbidden_key in ["name", "face_id", "ssn", "email", "biometric", "identity"]:
                if forbidden_key in entity:
                    raise ValueError(f"PII detected: {forbidden_key} is strictly prohibited in vector store")
            stored_vectors.append(entity)
        return list(range(len(entities)))

    mock.insert = MagicMock(side_effect=_insert)
    mock.has_collection = MagicMock(return_value=True)
    mock.search = MagicMock(return_value=[[]])
    mock.stored_vectors = stored_vectors
    return mock
