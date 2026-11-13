"""
CAMserv platform configuration — Pydantic v2 BaseSettings.

All settings are loadable from environment variables with the ``CAMSERV_``
prefix or from a YAML/JSON config file.  Nested models use ``__`` as the
env-var separator (e.g. ``CAMSERV_INFERENCE__DEVICE=cuda``).
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class InferenceDevice(str, Enum):
    CPU = "cpu"
    CUDA = "cuda"


class TrackingAlgorithm(str, Enum):
    DEEPSORT = "deepsort"
    BYTETRACK = "bytetrack"
    BOTSORT = "botsort"


class AnonymizationLevel(str, Enum):
    NONE = "none"
    BLUR_FACES = "blur_faces"
    BLUR_ALL = "blur_all"
    SILHOUETTE = "silhouette"


class RetentionUnit(str, Enum):
    HOURS = "hours"
    DAYS = "days"
    WEEKS = "weeks"


# ---------------------------------------------------------------------------
# Nested configuration models
# ---------------------------------------------------------------------------

class CameraSource(BaseModel):
    """Single camera / RTSP source definition."""

    id: str = Field(..., min_length=1, max_length=64, description="Unique camera identifier.")
    name: str = Field(..., min_length=1, max_length=128, description="Human-readable name.")
    url: str = Field(..., description="RTSP / HTTP stream URL.")
    enabled: bool = Field(True, description="Whether the camera is actively ingested.")
    fps: int = Field(15, ge=1, le=120, description="Target capture frame-rate.")
    resolution: tuple[int, int] = Field(
        (1920, 1080), description="Capture resolution (width, height)."
    )
    codec: str = Field("h264", description="Expected stream codec.")
    retry_interval_s: float = Field(
        5.0, ge=1.0, le=300.0, description="Seconds between reconnection attempts."
    )
    max_retries: int = Field(10, ge=0, description="Maximum reconnection attempts (0 = unlimited).")
    zones: list[str] = Field(default_factory=list, description="Privacy / analytics zone IDs.")

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        if not re.match(r"^(rtsp|rtsps|http|https)://", v, re.IGNORECASE):
            raise ValueError("Camera URL must start with rtsp://, rtsps://, http://, or https://")
        return v

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("Camera id must be alphanumeric (plus _ and -).")
        return v


class CamerasSettings(BaseModel):
    """Camera ingestion configuration."""

    sources: list[CameraSource] = Field(default_factory=list, description="List of camera sources.")
    max_concurrent: int = Field(
        8, ge=1, le=64, description="Maximum cameras processed concurrently."
    )
    buffer_size: int = Field(
        30, ge=1, le=300, description="Per-camera ring-buffer size (frames)."
    )
    reconnect_enabled: bool = Field(True, description="Auto-reconnect on stream loss.")


class InferenceSettings(BaseModel):
    """ONNX Runtime inference configuration."""

    device: InferenceDevice = Field(InferenceDevice.CUDA, description="Inference device.")
    model_path: Path = Field(
        Path("models/yolov8n.onnx"), description="Path to the ONNX detection model."
    )
    confidence_threshold: float = Field(
        0.45, ge=0.01, le=1.0, description="Minimum detection confidence."
    )
    nms_iou_threshold: float = Field(
        0.50, ge=0.01, le=1.0, description="Non-maximum suppression IoU threshold."
    )
    max_batch_size: int = Field(
        4, ge=1, le=32, description="Maximum batch size for GPU inference."
    )
    input_size: tuple[int, int] = Field(
        (640, 640), description="Model input dimensions (width, height)."
    )
    target_classes: list[int] = Field(
        default_factory=lambda: [0],  # COCO person class
        description="COCO class IDs to detect.",
    )
    half_precision: bool = Field(
        True, description="Use FP16 inference (requires GPU with compute >= 7.0)."
    )
    warmup_iterations: int = Field(
        3, ge=0, le=20, description="Model warmup iterations on startup."
    )
    gpu_memory_limit_mb: int = Field(
        4096, ge=512, le=24576, description="Maximum GPU memory allocation (MB)."
    )

    @model_validator(mode="after")
    def _check_half_precision(self) -> "InferenceSettings":
        if self.half_precision and self.device == InferenceDevice.CPU:
            raise ValueError("FP16 half-precision requires CUDA device, not CPU.")
        return self


class TrackingSettings(BaseModel):
    """Multi-object tracker configuration."""

    algorithm: TrackingAlgorithm = Field(
        TrackingAlgorithm.DEEPSORT, description="Tracking algorithm."
    )
    max_age: int = Field(
        70, ge=1, le=1000, description="Frames to keep a lost track alive."
    )
    min_hits: int = Field(
        3, ge=1, le=50, description="Minimum detections before a track is confirmed."
    )
    iou_threshold: float = Field(
        0.3, ge=0.01, le=1.0, description="IoU threshold for track association."
    )
    max_tracks: int = Field(
        200, ge=1, le=10000, description="Maximum concurrent tracks per camera."
    )
    embedding_dim: int = Field(
        128, ge=32, le=2048, description="Re-ID embedding dimension for vector search."
    )
    reid_model_path: Path = Field(
        Path("models/reid_osnet.onnx"), description="Path to Re-ID ONNX model."
    )
    kalman_process_noise: float = Field(
        1.0, ge=0.001, le=100.0, description="Kalman filter process noise multiplier."
    )
    kalman_measurement_noise: float = Field(
        1.0, ge=0.001, le=100.0, description="Kalman filter measurement noise multiplier."
    )


class EventRule(BaseModel):
    """Single event / alert rule definition."""

    id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    event_type: str = Field(..., description="Event type: intrusion, loitering, crowd, tripwire, etc.")
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    enabled: bool = True
    cooldown_s: float = Field(
        30.0, ge=0, le=3600, description="Minimum seconds between repeated firings."
    )
    min_confidence: float = Field(
        0.6, ge=0.0, le=1.0,
        description="Minimum prediction confidence to raise the event.",
    )
    require_human_review: bool = Field(
        False,
        description="If True, the event is queued for human review before action is taken.",
    )
    parameters: dict[str, float | int | str | bool] = Field(
        default_factory=dict,
        description="Event-type-specific parameters (e.g. loitering_seconds, zone_id).",
    )


class EventsSettings(BaseModel):
    """Event engine and alerting configuration."""

    rules: list[EventRule] = Field(default_factory=list, description="Event / alert rules.")
    max_queue_size: int = Field(
        10_000, ge=100, le=1_000_000, description="In-memory event queue depth."
    )
    dispatch_interval_ms: int = Field(
        100, ge=10, le=5000, description="Event dispatch loop interval."
    )
    webhook_url: str | None = Field(
        None, description="Optional webhook for event notifications."
    )
    webhook_timeout_s: float = Field(5.0, ge=1.0, le=60.0)
    human_review_default: bool = Field(
        True,
        description="Default require_human_review for new rules — enforces human-in-the-loop.",
    )


class PrivacyZone(BaseModel):
    """Defines a rectangular privacy masking zone in normalised coordinates."""

    id: str = Field(..., min_length=1, max_length=64)
    camera_id: str = Field(..., min_length=1, max_length=64)
    x: float = Field(..., ge=0.0, le=1.0)
    y: float = Field(..., ge=0.0, le=1.0)
    width: float = Field(..., ge=0.0, le=1.0)
    height: float = Field(..., ge=0.0, le=1.0)
    label: str = Field("", max_length=128)

    @model_validator(mode="after")
    def _check_bounds(self) -> "PrivacyZone":
        if self.x + self.width > 1.0 or self.y + self.height > 1.0:
            raise ValueError("Privacy zone extends beyond normalised frame bounds [0, 1].")
        return self


class PrivacySettings(BaseModel):
    """Privacy and data-protection configuration."""

    anonymization_level: AnonymizationLevel = Field(
        AnonymizationLevel.BLUR_FACES,
        description="Default anonymization applied to exported / streamed video.",
    )
    zones: list[PrivacyZone] = Field(
        default_factory=list, description="Static privacy masking zones."
    )
    face_blur_strength: int = Field(
        31, ge=3, le=99, description="Gaussian blur kernel size for face blurring (odd number)."
    )
    auto_purge_enabled: bool = Field(True, description="Automatically purge expired data.")
    data_retention_hours: int = Field(
        720,  # 30 days
        ge=1,
        le=8760,
        description="Hours to retain raw detection / tracking data.",
    )
    video_retention_hours: int = Field(
        168,  # 7 days
        ge=1,
        le=8760,
        description="Hours to retain recorded video clips.",
    )
    gdpr_erasure_enabled: bool = Field(
        True, description="Enable GDPR right-to-erasure endpoint.",
    )
    log_access_requests: bool = Field(
        True, description="Log all data-subject access requests for audit.",
    )

    @field_validator("face_blur_strength")
    @classmethod
    def _odd_kernel(cls, v: int) -> int:
        if v % 2 == 0:
            raise ValueError("face_blur_strength must be an odd number.")
        return v


class RedisSettings(BaseModel):
    """Redis connection configuration."""

    host: str = Field("localhost", description="Redis host.")
    port: int = Field(6379, ge=1, le=65535)
    db: int = Field(0, ge=0, le=15)
    password: SecretStr | None = Field(None, description="Redis AUTH password.")
    ssl: bool = Field(False, description="Use TLS for Redis connections.")
    max_connections: int = Field(20, ge=1, le=500)
    socket_timeout_s: float = Field(5.0, ge=1.0, le=60.0)


class MilvusSettings(BaseModel):
    """Milvus vector database configuration."""

    host: str = Field("localhost", description="Milvus host.")
    port: int = Field(19530, ge=1, le=65535)
    collection: str = Field("reid_embeddings", description="Default collection name.")
    dim: int = Field(128, ge=32, le=2048, description="Embedding dimension (must match tracker).")
    index_type: str = Field("IVF_FLAT", description="Milvus index type.")
    metric_type: str = Field("IP", description="Similarity metric: IP (inner product) or L2.")
    nprobe: int = Field(16, ge=1, le=1024, description="Search nprobe parameter.")
    search_top_k: int = Field(10, ge=1, le=1000, description="Default top-K for similarity search.")


class StorageSettings(BaseModel):
    """Storage and database configuration."""

    redis: RedisSettings = Field(default_factory=RedisSettings)
    milvus: MilvusSettings = Field(default_factory=MilvusSettings)
    video_archive_path: Path = Field(
        Path("data/video"), description="Directory for recorded video clips."
    )
    snapshot_path: Path = Field(
        Path("data/snapshots"), description="Directory for detection snapshots."
    )
    max_disk_usage_gb: float = Field(
        100.0, ge=1.0, le=10000.0, description="Maximum disk usage before old data is purged."
    )


class JWTSettings(BaseModel):
    """JWT authentication configuration."""

    secret_key: SecretStr = Field(
        ..., min_length=32, description="JWT signing secret (RS256 private key or HMAC secret)."
    )
    algorithm: str = Field("HS256", description="JWT algorithm (HS256, RS256).")
    access_token_expire_minutes: int = Field(30, ge=5, le=1440)
    refresh_token_expire_days: int = Field(7, ge=1, le=90)
    issuer: str = Field("camserv", description="JWT issuer claim.")


class RBACRole(BaseModel):
    """Role-based access control role definition."""

    name: str = Field(..., min_length=1, max_length=64)
    permissions: list[str] = Field(
        default_factory=list,
        description="Permission strings: cameras:read, cameras:write, events:read, etc.",
    )


class SecuritySettings(BaseModel):
    """Security configuration."""

    jwt: JWTSettings
    roles: list[RBACRole] = Field(
        default_factory=lambda: [
            RBACRole(name="admin", permissions=["*"]),
            RBACRole(name="operator", permissions=[
                "cameras:read", "cameras:write",
                "detections:read", "events:read", "events:write",
                "tracks:read", "alerts:read", "alerts:write",
                "analytics:read",
            ]),
            RBACRole(name="viewer", permissions=[
                "cameras:read", "detections:read", "events:read",
                "tracks:read", "analytics:read",
            ]),
            RBACRole(name="auditor", permissions=[
                "cameras:read", "detections:read", "events:read",
                "tracks:read", "analytics:read", "audit:read",
            ]),
        ],
    )
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"],
        description="Allowed CORS origins.",
    )
    rate_limit_rpm: int = Field(
        300, ge=10, le=10000, description="Global requests-per-minute rate limit."
    )
    tls_enabled: bool = Field(False, description="Enable TLS termination in uvicorn.")
    tls_cert_path: Path | None = Field(None, description="Path to TLS certificate.")
    tls_key_path: Path | None = Field(None, description="Path to TLS private key.")
    audit_log_path: Path = Field(
        Path("logs/audit.jsonl"), description="Path for tamper-evident audit log."
    )
    audit_hmac_key: SecretStr | None = Field(
        None, description="HMAC key for audit log chain integrity."
    )

    @model_validator(mode="after")
    def _tls_paths(self) -> "SecuritySettings":
        if self.tls_enabled and (self.tls_cert_path is None or self.tls_key_path is None):
            raise ValueError("tls_cert_path and tls_key_path are required when tls_enabled=True.")
        return self


class PipelineSettings(BaseModel):
    """Frame processing pipeline tuning."""

    max_pipeline_latency_ms: int = Field(
        100, ge=10, le=5000, description="Target end-to-end latency budget (ms)."
    )
    inference_timeout_ms: int = Field(
        50, ge=5, le=2000, description="Per-frame inference timeout (ms)."
    )
    skip_frames: int = Field(
        0, ge=0, le=30,
        description="Process every N-th frame (0 = process all). Reduces GPU load.",
    )
    enable_profiling: bool = Field(
        False, description="Enable per-stage latency profiling."
    )
    queue_backpressure_limit: int = Field(
        60, ge=10, le=1000,
        description="Frame queue depth before applying back-pressure to ingestion.",
    )


# ---------------------------------------------------------------------------
# Root settings
# ---------------------------------------------------------------------------

class CamservSettings(BaseSettings):
    """
    Root configuration for the CAMserv platform.

    Environment variables use the ``CAMSERV_`` prefix with ``__`` as the
    nested separator.  Example::

        CAMSERV_INFERENCE__DEVICE=cuda
        CAMSERV_STORAGE__REDIS__HOST=redis.local
        CAMSERV_SECURITY__JWT__SECRET_KEY=super-secret-key-at-least-32-chars
    """

    model_config = SettingsConfigDict(
        env_prefix="CAMSERV_",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Top-level ---
    app_name: str = Field("CAMserv", description="Application display name.")
    environment: Literal["development", "staging", "production"] = Field(
        "development", description="Deployment environment."
    )
    debug: bool = Field(False, description="Enable debug mode (verbose logging, auto-reload).")
    log_level: LogLevel = Field(LogLevel.INFO, description="Root log level.")
    host: str = Field("0.0.0.0", description="API server bind address.")
    port: int = Field(8000, ge=1, le=65535, description="API server bind port.")

    # --- Nested sections ---
    cameras: CamerasSettings = Field(default_factory=CamerasSettings)
    inference: InferenceSettings = Field(default_factory=InferenceSettings)
    tracking: TrackingSettings = Field(default_factory=TrackingSettings)
    events: EventsSettings = Field(default_factory=EventsSettings)
    privacy: PrivacySettings = Field(default_factory=PrivacySettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    security: SecuritySettings  # no default — JWT secret is required
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)

    # --- Derived validation ---
    @model_validator(mode="after")
    def _cross_validate(self) -> "CamservSettings":
        # Ensure embedding dimensions are consistent between tracker and Milvus
        if self.tracking.embedding_dim != self.storage.milvus.dim:
            raise ValueError(
                f"Tracking embedding_dim ({self.tracking.embedding_dim}) must match "
                f"Milvus collection dim ({self.storage.milvus.dim})."
            )
        # Warn-level: production should not run in debug
        if self.environment == "production" and self.debug:
            raise ValueError("debug=True is not permitted in production environment.")
        return self
