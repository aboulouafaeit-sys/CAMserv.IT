"""
camserv.intelligence.contracts
==============================

Foundational types, protocol interfaces, data structures, and epistemic
abstractions for the CAMserv Intelligence Platform (Phase 27).

Every intelligence prediction explicitly carries `is_prediction=True`.
No AI hypothesis is ever converted into an established physical fact automatically.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class EngineHealthStatus(str, enum.Enum):
    """Real-time operational status of an intelligence engine."""

    ACTIVE = "active"                          # Engine running normally and processing
    AVAILABLE = "available"                    # Ready to run; idle or waiting for input
    LIMITED = "limited"                        # Throttled due to resource constraints
    DEGRADED = "degraded"                      # Running with reduced sampling or accuracy
    DISABLED = "disabled"                      # Administratively disabled by config
    UNSUPPORTED = "unsupported"                # Missing hardware or host capability
    MODEL_MISSING = "model_missing"            # Weight or model artifact not found
    HARDWARE_UNAVAILABLE = "hardware_unavail"  # Required GPU/NPU accelerator absent


class IntelligencePriority(int, enum.Enum):
    """
    Mandatory priority hierarchy. Lower integer value = higher priority.
    Surveillance recording and evidence preservation CANNOT be starved by AI.
    """

    RECORDING_CONTINUITY = 1   # Primary video recording to disk (NON-NEGOTIABLE #1)
    VIDEO_INGESTION = 2        # RTSP / camera frame ingestion and timestamps
    STORAGE_EVIDENCE = 3       # Tamper-evident vault & segment integrity
    LIVE_VIEWING = 4           # Real-time operator workspace display
    SYSTEM_MONITORING = 5      # Host health, thermal watchdog, heartbeat
    AI_ANALYTICS = 6           # Standard computer vision and tracking
    EXPENSIVE_ANALYSIS = 7     # Optional heavy tasks (e.g. ANPR, multi-model OCR)


class HardwareOperatingTier(str, enum.Enum):
    """Adaptive hardware classification tiers."""

    TIER_A_CPU_LOW = "tier_a_cpu_low"          # Low-resource CPU, conservative queues
    TIER_B_IGPU_NPU = "tier_b_igpu_npu"        # Integrated graphics / NPU acceleration
    TIER_C_MODERATE_DGPU = "tier_c_mod_dgpu"   # Moderate discrete GPU, higher throughput
    TIER_D_HIGH_PERF_SERVER = "tier_d_server"  # Enterprise server, high concurrency


class TrackLifecycleState(str, enum.Enum):
    """Lifecycle stages of an anonymous object track."""

    NEW = "new"              # Candidate detection awaiting temporal confirmation
    TRACKED = "tracked"      # Actively tracked across consecutive frames
    LOST = "lost"            # Temporarily occluded or missed by detector
    REMOVED = "removed"      # Evicted from tracker (exited scene or timed out)


class ModelCapabilityState(str, enum.Enum):
    """Epistemic operational readiness and verification state of an AI model."""

    MODEL_NOT_INSTALLED = "model_not_installed"
    MODEL_LOADING = "model_loading"
    MODEL_READY = "model_ready"
    MODEL_INTEGRITY_VERIFIED = "model_integrity_verified"
    MODEL_INTEGRITY_FAILED = "model_integrity_failed"
    MODEL_RUNTIME_UNAVAILABLE = "model_runtime_unavailable"
    MODEL_UNSUPPORTED = "model_unsupported"
    MODEL_LICENSE_UNVERIFIED = "model_license_unverified"
    MODEL_INFERENCE_FAILED = "model_inference_failed"


class WorkerLifecycleState(str, enum.Enum):
    """
    Accurate lifecycle states for AI inference workers (Phase 27.2 Process Isolation).
    No state may falsely claim a worker process has terminated.
    """

    CREATED = "created"
    STARTING = "starting"
    READY = "ready"
    RUNNING = "running"                                    # Actively executing task
    UNRESPONSIVE = "unresponsive"                          # Health check missed or lease expired
    CANCELLATION_REQUESTED = "cancellation_requested"      # Timeout or stop signal sent
    GRACEFUL_TERMINATION_REQUESTED = "graceful_termination_requested"  # Graceful exit requested
    FORCE_TERMINATION_REQUESTED = "force_termination_requested"        # Escalating to SIGTERM/SIGKILL
    TERMINATION_UNCONFIRMED = "termination_unconfirmed"    # Native execution timed out, exit unconfirmed
    TERMINATED = "terminated"                              # Worker process confirmed dead via OS check
    RESTART_PENDING = "restart_pending"                    # Queued for restart with incremented generation
    RECOVERY_FAILED = "recovery_failed"                    # Recovery or restart circuit breaker tripped


class SpeedMeasurementStatus(str, enum.Enum):
    """Epistemic classification of vehicle speed calculations."""

    CALIBRATED_ACCURATE = "calibrated_accurate"            # Fully calibrated with verified spatial metric
    RELATIVE_MOVEMENT_ONLY = "relative_movement_only"      # Uncalibrated pixel displacement only
    SPEED_UNAVAILABLE = "speed_unavailable"                # Speed cannot be computed due to geometry or data gaps


class PlateQualityGrade(str, enum.Enum):
    """Optical quality assessment of a license plate candidate region."""

    OPTIMAL = "optimal"          # Sharp, well-lit, frontal angle, high resolution
    ACCEPTABLE = "acceptable"    # Minor blur or angle; OCR viable with confidence
    DEGRADED = "degraded"        # Severe motion blur, glare, or oblique perspective
    UNREADABLE = "unreadable"    # Unusable; OCR prohibited to prevent fabrication


class PlateProcessingStatus(str, enum.Enum):
    """Outcome status of license plate detection and OCR pipeline."""

    SUCCESS = "success"                        # Plate parsed with high confidence
    LOW_CONFIDENCE = "low_confidence"          # Plate candidate below confidence gate
    UNREADABLE = "unreadable"                  # Plate failed optical quality assessment
    REVIEW_REQUIRED = "review_required"        # Human verification workflow needed
    UNAUTHORIZED = "unauthorized"              # ANPR disabled or unauthorized for camera
    UNSUPPORTED_FORMAT = "unsupported_format"  # Plate format syntax unrecognized
    OCR_RUNTIME_UNAVAILABLE = "ocr_runtime_unavailable"  # OCR model or runtime unavailable
    OCR_SIMULATED = "ocr_simulated"            # Test simulator / synthetic fallback


class TrafficCongestionLevel(str, enum.Enum):
    """Traffic density and movement state."""

    FREE_FLOW = "free_flow"      # Vehicles moving freely at nominal lane speeds
    MODERATE = "moderate"        # Dense traffic with continuous movement
    CONGESTED = "congested"      # Intermittent stop-and-go; high occupancy
    STANDSTILL = "standstill"    # Vehicles stationary; queue formation detected


class CameraProfilePreset(str, enum.Enum):
    """Configuration profiles optimized for specific surveillance deployment zones."""

    ROAD_TRAFFIC = "road_traffic"              # Vehicle counts, wrong-way, congestion
    PARKING = "parking"                        # Occupancy, dwell, optional ANPR
    BUILDING_ENTRANCE = "building_entrance"    # Pedestrian flow, entry/exit tripwires
    WAREHOUSE = "warehouse"                    # High-speed forklifts, aisle obstructions
    RETAIL = "retail"                          # Foot traffic density, queue monitoring
    PERIMETER = "perimeter"                    # Geo-fencing, fence breach, loitering
    GENERAL_SURVEILLANCE = "general"           # Balanced defaults for generic cameras


class IntelligenceEventType(str, enum.Enum):
    """Standardized event taxonomy for the intelligence platform."""

    PERSON_DETECTED = "PERSON_DETECTED"
    VEHICLE_DETECTED = "VEHICLE_DETECTED"
    VEHICLE_ENTERED_ZONE = "VEHICLE_ENTERED_ZONE"
    VEHICLE_EXITED_ZONE = "VEHICLE_EXITED_ZONE"
    PEDESTRIAN_CROSSING = "PEDESTRIAN_CROSSING"
    VEHICLE_STOPPED = "VEHICLE_STOPPED"
    WRONG_DIRECTION_INDICATOR = "WRONG_DIRECTION_INDICATOR"
    TRAFFIC_CONGESTION = "TRAFFIC_CONGESTION"
    ROAD_OBSTRUCTION = "ROAD_OBSTRUCTION"
    PLATE_CANDIDATE_DETECTED = "PLATE_CANDIDATE_DETECTED"
    PLATE_RECOGNITION_UNCERTAIN = "PLATE_RECOGNITION_UNCERTAIN"
    SMOKE_INDICATOR = "SMOKE_INDICATOR"
    FIRE_INDICATOR = "FIRE_INDICATOR"
    CAMERA_ANALYTICS_DEGRADED = "CAMERA_ANALYTICS_DEGRADED"
    AI_WORKER_FAILURE = "AI_WORKER_FAILURE"
    RESOURCE_LIMIT_REACHED = "RESOURCE_LIMIT_REACHED"


class EpistemicLevel(str, enum.Enum):
    """Four-tier epistemic reasoning hierarchy."""

    OBSERVATION = "observation"  # Raw bounding box, track point, optical detection
    MEASUREMENT = "measurement"  # Quantified metric (pixel velocity, count, duration)
    INFERENCE = "inference"      # Synthesized interpretation (probable congestion)
    EVENT = "event"              # Actionable alert submitted to rule engine / operator


# ---------------------------------------------------------------------------
# Core Spatial & Detection Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class BoundingBox:
    """Axis-aligned 2D bounding box (x1, y1, x2, y2) in pixel space."""

    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self) -> None:
        if self.x2 < self.x1 or self.y2 < self.y1:
            raise ValueError(
                f"Invalid bounding box coordinates: x1={self.x1}, y1={self.y1}, x2={self.x2}, y2={self.y2}"
            )

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
        """Calculate Intersection over Union with another bounding box."""
        xi1 = max(self.x1, other.x1)
        yi1 = max(self.y1, other.y1)
        xi2 = min(self.x2, other.x2)
        yi2 = min(self.y2, other.y2)
        inter = max(0.0, xi2 - xi1) * max(0.0, yi2 - yi1)
        union = self.area + other.area - inter
        return inter / union if union > 0.0 else 0.0

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x1, self.y1, self.x2, self.y2)


@dataclass(slots=True)
class DetectionPrediction:
    """A probabilistic object detection prediction from an inference model."""

    bbox: BoundingBox
    class_id: int
    class_name: str
    confidence: float
    camera_id: str
    frame_id: int
    timestamp_utc: float = field(default_factory=time.time)
    is_prediction: bool = True  # Always True; never presented as ground truth
    polygon: list[tuple[float, float]] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence score must be in [0.0, 1.0], got {self.confidence}")
        if not self.is_prediction:
            object.__setattr__(self, "is_prediction", True)


@dataclass(slots=True)
class ClassificationResult:
    """Fine-grained classification result separated from detection."""

    class_id: int
    class_name: str
    confidence: float
    is_uncertain: bool = False
    subcategories: list[tuple[str, float]] = field(default_factory=list)
    is_prediction: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TrackRecord:
    """Anonymized spatio-temporal track scoped strictly to camera and session."""

    track_id: int
    camera_id: str
    session_id: str
    bbox: BoundingBox
    class_name: str
    class_id: int
    confidence: float
    state: TrackLifecycleState
    age_frames: int
    created_at_utc: float
    last_seen_utc: float
    velocity_pixels_per_sec: tuple[float, float] = (0.0, 0.0)
    trajectory: list[tuple[float, float]] = field(default_factory=list)
    is_prediction: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Traffic & Movement Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CameraCalibration:
    """
    Camera perspective and geometrical calibration parameters.
    Speed in km/h is NEVER reported without a valid, validated calibration.
    """

    camera_id: str
    is_calibrated: bool = False
    pixels_per_meter: float = 1.0
    reference_distance_meters: float = 0.0
    homography_matrix: list[list[float]] | None = None
    error_margin_percent: float = 15.0
    calibration_date_utc: str = ""
    notes: str = "Uncalibrated default — relative pixel movement only."

    def project_to_ground_plane(self, u: float, v: float) -> tuple[float, float] | None:
        """
        Project image coordinates (u, v) to ground plane (X_w, Y_w) in meters using
        the 3x3 planar homography matrix H.
        [X', Y', W']^T = H * [u, v, 1]^T
        X_w = X' / W', Y_w = Y' / W'
        """
        if not self.homography_matrix or len(self.homography_matrix) != 3:
            return None
        h = self.homography_matrix
        if any(len(row) != 3 for row in h):
            return None
        xp = h[0][0] * u + h[0][1] * v + h[0][2]
        yp = h[1][0] * u + h[1][1] * v + h[1][2]
        wp = h[2][0] * u + h[2][1] * v + h[2][2]
        if abs(wp) < 1e-6:
            return None
        return (xp / wp, yp / wp)


@dataclass(slots=True)
class TrafficCountingLine:
    """Virtual line crossing boundary with directional vector evaluation."""

    line_id: str
    camera_id: str
    name: str
    start_pt: tuple[float, float]
    end_pt: tuple[float, float]
    forward_count: int = 0
    reverse_count: int = 0
    is_active: bool = True


@dataclass(slots=True)
class TrafficZone:
    """Monitored 2D polygon road or lane area for density and dwell tracking."""

    zone_id: str
    camera_id: str
    name: str
    vertices: list[tuple[float, float]]
    is_active: bool = True


@dataclass(slots=True)
class TrafficFlowMeasurement:
    """Aggregated traffic metrics distinguishing observed facts from estimates."""

    camera_id: str
    timestamp_utc: float
    observed_vehicle_count: int
    observed_pedestrian_count: int
    estimated_density: float                   # Normalized 0.0 - 1.0 occupancy
    congestion_level: TrafficCongestionLevel
    queue_length_meters: float
    stationary_vehicle_count: int
    wrong_direction_count: int
    is_calibrated: bool = False
    calibrated_speed_kmh: float | None = None  # None unless is_calibrated is True
    relative_velocity_pixels_sec: float = 0.0
    speed_status: SpeedMeasurementStatus = SpeedMeasurementStatus.RELATIVE_MOVEMENT_ONLY
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# ANPR / License Plate Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PlateQualityAssessment:
    """Multi-factor optical quality assessment for plate recognition gating."""

    blur_variance: float                       # Laplacian blur variance
    glare_ratio: float                         # Percentage of saturated pixels
    pixel_height: int                          # Character/plate pixel height
    illumination_score: float                  # Mean luminance normalized [0, 1]
    perspective_angle_deg: float               # Estimated skew angle in degrees
    overall_grade: PlateQualityGrade
    passed_gating: bool
    rejection_reason: str | None = None


@dataclass(slots=True)
class PlateRecognitionResult:
    """Full 12-stage license plate recognition result with provenance."""

    plate_id: str
    camera_id: str
    timestamp_utc: float
    raw_ocr_text: str
    normalized_candidate: str
    overall_confidence: float
    character_confidences: list[tuple[str, float]]
    quality: PlateQualityAssessment
    status: PlateProcessingStatus
    vehicle_bbox: BoundingBox | None
    plate_bbox: BoundingBox
    source_frame_hash: str                     # SHA-256 of source frame
    source_segment_id: str                     # Associated video recording segment
    review_status: str = "PENDING_REVIEW"      # PENDING_REVIEW, CONFIRMED, REJECTED
    operator_notes: str | None = None
    is_prediction: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Event & Provenance Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class IntelligenceEvent:
    """Actionable structured intelligence event published to the rules engine."""

    event_id: str
    event_type: IntelligenceEventType
    camera_id: str
    timestamp_utc: float
    confidence: float
    severity: str                              # INFO, LOW, MEDIUM, HIGH, CRITICAL
    epistemic_level: EpistemicLevel
    evidence_hash: str                         # SHA-256 reference to frame/evidence
    source_segment_id: str
    source_frame_id: int
    model_version: str
    requires_human_review: bool = False
    review_status: str = "UNREVIEWED"          # UNREVIEWED, CONFIRMED, DISMISSED
    is_prediction: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvidenceLink:
    """Immutable provenance record connecting intelligence metadata to raw video."""

    evidence_id: str
    event_id: str
    camera_id: str
    timestamp_utc: float
    segment_id: str
    frame_id: int
    frame_sha256: str
    derived_artifact_path: str
    model_id: str
    model_hash: str
    is_derived_artifact: bool = True           # NEVER mutates original raw recording


@dataclass(slots=True)
class CameraIntelligenceConfig:
    """Configuration container for camera-specific visual intelligence."""

    camera_id: str
    profile_preset: CameraProfilePreset = CameraProfilePreset.GENERAL_SURVEILLANCE
    enabled_engines: set[str] = field(default_factory=lambda: {
        "detection", "tracking", "scene", "events"
    })
    confidence_threshold: float = 0.40
    sampling_fps: float = 5.0
    max_queue_depth: int = 15
    retention_days: int = 30
    anpr_authorized: bool = False              # Disabled by default
    anpr_legal_justification: str = ""
    calibration: CameraCalibration = field(default_factory=lambda: CameraCalibration(camera_id="default"))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class InferenceTaskLease:
    """Lease contract governing an execution task assigned to an isolated worker."""

    lease_id: str
    worker_id: str
    generation: int
    camera_id: str
    created_at_utc: float
    expires_at_utc: float
    is_cancelled: bool = False

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at_utc

