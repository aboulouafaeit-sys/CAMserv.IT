"""Pydantic request and response schemas for the CAMserv REST and WebSocket APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Authentication Models
# ---------------------------------------------------------------------------

class TokenRequest(BaseModel):
    """User login credential payload."""

    username: str = Field(..., min_length=1, description="Username or service identifier.")
    password: str = Field(..., min_length=1, description="Password.")


class TokenResponse(BaseModel):
    """OAuth2 / JWT token response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    """Token refresh request."""

    refresh_token: str


# ---------------------------------------------------------------------------
# Camera Models
# ---------------------------------------------------------------------------

class CameraCreate(BaseModel):
    """Payload to register a new camera stream."""

    id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=128)
    url: str = Field(..., description="RTSP, HTTP, or video stream URL.")
    enabled: bool = True
    fps: int = Field(15, ge=1, le=120)
    resolution: tuple[int, int] = (1920, 1080)
    codec: str = "h264"
    retry_interval_s: float = Field(5.0, ge=1.0, le=300.0)
    max_retries: int = Field(10, ge=0)
    zones: list[str] = Field(default_factory=list)


class CameraUpdate(BaseModel):
    """Partial update payload for an existing camera."""

    name: str | None = None
    url: str | None = None
    enabled: bool | None = None
    fps: int | None = Field(None, ge=1, le=120)
    resolution: tuple[int, int] | None = None
    retry_interval_s: float | None = None
    zones: list[str] | None = None


class CameraResponse(BaseModel):
    """Camera description schema."""

    id: str
    name: str
    url: str
    enabled: bool
    fps: int
    resolution: tuple[int, int]
    codec: str
    retry_interval_s: float
    max_retries: int
    zones: list[str]
    status: str = "online"


# ---------------------------------------------------------------------------
# Detection Models
# ---------------------------------------------------------------------------

class BoundingBoxSchema(BaseModel):
    """Bounding box pixel coordinates [x1, y1, x2, y2]."""

    x1: float
    y1: float
    x2: float
    y2: float


class DetectionResponse(BaseModel):
    """Detected object representation."""

    bbox: BoundingBoxSchema
    class_id: int
    class_name: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    camera_id: str
    frame_id: int
    timestamp: str
    is_prediction: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Track Models
# ---------------------------------------------------------------------------

class TrackResponse(BaseModel):
    """Active object track."""

    track_id: int
    bbox: BoundingBoxSchema
    class_name: str
    class_id: int
    confidence: float
    age: int
    state: str
    camera_id: str
    velocity: tuple[float, float] = (0.0, 0.0)
    trajectory: list[tuple[float, float]] = Field(default_factory=list)
    last_seen: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Event & Verification Models
# ---------------------------------------------------------------------------

class EventVerificationRequest(BaseModel):
    """Human-in-the-loop verification decision."""

    action: Literal["accept", "dismiss"] = Field(
        ..., description="Verification decision: accept or dismiss."
    )
    reason: str = Field(..., min_length=3, description="Justification for the decision.")
    reviewer_notes: str | None = Field(None, description="Optional extra analyst notes.")


class EventResponse(BaseModel):
    """Security event representation."""

    event_id: str
    event_type: str
    severity: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    camera_id: str
    timestamp: str
    requires_verification: bool
    description: str
    related_track_ids: list[int] = Field(default_factory=list)
    zone_id: str | None = None
    is_prediction: bool = True
    verification_status: str = "pending"  # pending, verified, dismissed
    verified_by: str | None = None
    verification_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PaginatedEventsResponse(BaseModel):
    """Cursor-paginated events collection."""

    items: list[EventResponse]
    next_cursor: str | None = None
    total: int = 0


# ---------------------------------------------------------------------------
# System & Audit Models
# ---------------------------------------------------------------------------

class HealthCheckResponse(BaseModel):
    """Detailed platform health report."""

    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    timestamp: str
    components: dict[str, Any]


class AuditLogEntryModel(BaseModel):
    """Audit log entry schema."""

    timestamp: str
    actor: str
    action: str
    resource: str
    result: str
    details: dict[str, Any]
    prev_hash: str
    entry_hash: str


class AuditLogResponse(BaseModel):
    """Audit log query response with chain verification status."""

    items: list[AuditLogEntryModel]
    total: int
    chain_verified: bool


# ---------------------------------------------------------------------------
# NVR & Camera Group Models
# ---------------------------------------------------------------------------

class CameraGroupCreate(BaseModel):
    """Create a logical camera group."""

    group_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=128)
    description: str = ""
    camera_ids: list[str] = Field(default_factory=list)
    site_id: str = "default"
    tags: list[str] = Field(default_factory=list)


class CameraGroupResponse(BaseModel):
    """Camera group description."""

    group_id: str
    name: str
    description: str
    camera_ids: list[str]
    site_id: str
    tags: list[str]
    created_at: float


class RecordingResponse(BaseModel):
    """Recording session details."""

    recording_id: str
    camera_id: str
    start_time_utc: str
    end_time_utc: str | None = None
    recording_type: str
    status: str
    storage_tier: str
    total_size_bytes: int
    created_at: str


class RecordingSegmentResponse(BaseModel):
    """Segmented video chunk metadata."""

    segment_id: str
    recording_id: str
    camera_id: str
    segment_index: int
    start_time_utc: str
    end_time_utc: str
    duration_seconds: float
    file_path: str
    file_size_bytes: int
    sha256_hash: str
    has_motion: bool
    has_event: bool
    event_ids: list[str]


class TimelineMarkerModel(BaseModel):
    """Timeline event marker."""

    marker_id: str
    camera_id: str
    timestamp_utc: str
    marker_type: str
    severity: str
    description: str
    event_id: str | None = None


class TimelineSpanModel(BaseModel):
    """Timeline recording span."""

    camera_id: str
    start_time_utc: str
    end_time_utc: str
    duration_seconds: float
    segment_ids: list[str]
    has_motion: bool
    has_event: bool
    markers: list[TimelineMarkerModel] = Field(default_factory=list)


class RecordingTimelineResponse(BaseModel):
    """Timeline query response for single or multi-camera views."""

    camera_id: str
    start_time_utc: str
    end_time_utc: str
    spans: list[TimelineSpanModel]


class ClippedExportRequest(BaseModel):
    """Request to export a clipped time-range video package."""

    camera_id: str
    start_time_utc: str
    end_time_utc: str
    export_format: str = "mp4"


class ClippedExportResponse(BaseModel):
    """Outcome of a clipped video export."""

    export_id: str
    camera_id: str
    start_time_utc: str
    end_time_utc: str
    output_file: str
    file_size_bytes: int
    sha256_hash: str
    segments_included: list[str]
    exported_at: str


# ---------------------------------------------------------------------------
# PTZ Models
# ---------------------------------------------------------------------------

class PTZMoveRequest(BaseModel):
    """Velocity vector for PTZ motion [-1.0, 1.0]."""

    pan: float = Field(0.0, ge=-1.0, le=1.0)
    tilt: float = Field(0.0, ge=-1.0, le=1.0)
    zoom: float = Field(0.0, ge=-1.0, le=1.0)
    timeout_s: float = Field(0.0, ge=0.0, le=60.0)


class PTZPresetCreate(BaseModel):
    """Save current physical coordinates as preset."""

    name: str = Field(..., min_length=1, max_length=64)


class PTZPresetResponse(BaseModel):
    """PTZ preset details."""

    preset_id: str
    camera_id: str
    name: str
    pan: float
    tilt: float
    zoom: float
    token: str | None = None


class PTZCapabilitiesResponse(BaseModel):
    """Channel PTZ capability profile."""

    camera_id: str
    is_ptz_capable: bool
    supports_continuous_move: bool
    supports_relative_move: bool
    supports_absolute_move: bool
    supports_presets: bool
    max_presets: int
    notes: str


# ---------------------------------------------------------------------------
# Analytics Zone Models
# ---------------------------------------------------------------------------

class TripwireCreate(BaseModel):
    """Virtual tripwire line configuration."""

    tripwire_id: str = Field(..., min_length=1, max_length=64)
    name: str
    start_point: tuple[float, float]
    end_point: tuple[float, float]
    direction: Literal["bidirectional", "forward", "reverse"] = "bidirectional"


class PolygonZoneCreate(BaseModel):
    """Virtual polygon zone configuration."""

    zone_id: str = Field(..., min_length=1, max_length=64)
    name: str
    vertices: list[tuple[float, float]]
    loitering_threshold_sec: float = 10.0


class ZoneEventResponse(BaseModel):
    """Spatial zone analytics event candidate."""

    event_type: str
    camera_id: str
    zone_or_tripwire_id: str
    track_id: int
    timestamp_utc: float
    confidence: float
    dwell_duration_sec: float = 0.0
    is_prediction: bool = True
