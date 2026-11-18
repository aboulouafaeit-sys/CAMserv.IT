"""
camserv.intelligence
====================

CAMserv Visual Intelligence, Traffic Analytics, Object Understanding & ANPR.

A hardware-adaptive, failure-isolated intelligence platform built for
local-first edge and appliance surveillance deployments.
"""

from camserv.intelligence.anpr import (
    LicensePlateEngine,
    assess_plate_quality,
    extract_characters_from_pixels,
)
from camserv.intelligence.classification import ObjectClassificationEngine
from camserv.intelligence.contracts import (
    BoundingBox,
    CameraCalibration,
    CameraIntelligenceConfig,
    CameraProfilePreset,
    ClassificationResult,
    DetectionPrediction,
    EngineHealthStatus,
    EpistemicLevel,
    EvidenceLink,
    HardwareOperatingTier,
    InferenceTaskLease,
    IntelligenceEvent,
    IntelligenceEventType,
    IntelligencePriority,
    ModelCapabilityState,
    PlateProcessingStatus,
    PlateQualityAssessment,
    PlateQualityGrade,
    PlateRecognitionResult,
    SpeedMeasurementStatus,
    TrackLifecycleState,
    TrackRecord,
    TrafficCongestionLevel,
    TrafficCountingLine,
    TrafficFlowMeasurement,
    TrafficZone,
    WorkerLifecycleState,
)
from camserv.intelligence.coordinator import CAMservIntelligenceEngine
from camserv.intelligence.detection import (
    CANONICAL_CLASSES,
    ObjectDetectionEngine,
    apply_nms,
)
from camserv.intelligence.events import EventDetectionEngine
from camserv.intelligence.evidence import EvidenceProvenanceEngine
from camserv.intelligence.health import IntelligenceHealthMonitor
from camserv.intelligence.process_worker import ProcessIsolatedInferenceSupervisor
from camserv.intelligence.registry import (
    DEFAULT_MODELS,
    EMPTY_FILE_SHA256,
    ModelCapabilityRecord,
    ModelCapabilityRegistry,
    validate_model_path,
)
from camserv.intelligence.rules import (
    PROFILE_DEFAULTS,
    ConfigurableRulesEngine,
)
from camserv.intelligence.scene import (
    SceneReasoningRecord,
    SceneUnderstandingEngine,
)
from camserv.intelligence.scheduler import (
    AIResourceScheduler,
    ResourceAdmissionError,
    SchedulerMetrics,
    TierBudget,
    WorkerExecutionTimeoutError,
)
from camserv.intelligence.tracking import ObjectTrackingEngine

__all__ = [
    # Coordinator
    "CAMservIntelligenceEngine",
    # 12 Engines
    "ObjectDetectionEngine",
    "ObjectClassificationEngine",
    "ObjectTrackingEngine",
    "SceneUnderstandingEngine",
    "TrafficAnalyticsEngine",
    "LicensePlateEngine",
    "EventDetectionEngine",
    "ConfigurableRulesEngine",
    "EvidenceProvenanceEngine",
    "AIResourceScheduler",
    "ProcessIsolatedInferenceSupervisor",
    "ModelCapabilityRegistry",
    "IntelligenceHealthMonitor",
    # Contracts & Dataclasses
    "BoundingBox",
    "DetectionPrediction",
    "ClassificationResult",
    "TrackRecord",
    "TrafficCountingLine",
    "TrafficZone",
    "TrafficFlowMeasurement",
    "CameraCalibration",
    "PlateQualityAssessment",
    "PlateRecognitionResult",
    "IntelligenceEvent",
    "InferenceTaskLease",
    "EvidenceLink",
    "CameraIntelligenceConfig",
    "SceneReasoningRecord",
    "ModelCapabilityRecord",
    "TierBudget",
    "SchedulerMetrics",
    # Enums
    "EngineHealthStatus",
    "IntelligencePriority",
    "HardwareOperatingTier",
    "TrackLifecycleState",
    "PlateQualityGrade",
    "PlateProcessingStatus",
    "TrafficCongestionLevel",
    "CameraProfilePreset",
    "IntelligenceEventType",
    "EpistemicLevel",
    "WorkerLifecycleState",
    "SpeedMeasurementStatus",
    "ModelCapabilityState",
    # Constants & Helpers
    "CANONICAL_CLASSES",
    "PROFILE_DEFAULTS",
    "DEFAULT_MODELS",
    "EMPTY_FILE_SHA256",
    "apply_nms",
    "assess_plate_quality",
    "extract_characters_from_pixels",
    "validate_model_path",
    # Exceptions
    "ResourceAdmissionError",
    "WorkerExecutionTimeoutError",
]
