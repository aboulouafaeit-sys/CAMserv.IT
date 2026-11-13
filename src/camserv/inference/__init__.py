"""CAMserv inference and detection package.

Provides object detection, scene analysis, privacy filtering,
and inference benchmarking for the CAMserv security intelligence platform.
"""

from camserv.inference.benchmarks import (
    BenchmarkResult,
    ComparisonReport,
    InferenceBenchmark,
    LatencyStats,
    MemoryUsage,
)
from camserv.inference.detector import (
    BaseDetector,
    BoundingBox,
    CAMSERV_CLASS_NAMES,
    COCO_TO_CAMSERV,
    Detection,
    DetectorBackend,
    DetectorFactory,
    Frame,
    ONNXDetector,
    SUPPORTED_CLASSES,
    UltralyticsDetector,
    nms,
)
from camserv.inference.hud_renderer import (
    CinematicHUDRenderer,
    ThreatVisualState,
)
from camserv.inference.segmentation import (
    COCO_KEYPOINT_NAMES,
    COCO_SKELETON_PAIRS,
    SegmentationEngine,
    SegmentedContour,
    SkeletalPose,
)
from camserv.inference.privacy import (
    BlurMethod,
    PrivacyConfig,
    PrivacyFilter,
    PrivacyZone,
)
from camserv.inference.scene import (
    CrowdDensityResult,
    HazardResult,
    HazardType,
    ObservationStatus,
    SceneAnalyzer,
    SceneEventType,
    SceneObservation,
    TamperingResult,
    VehicleFlowResult,
    Zone,
)

__all__ = [
    # Detection
    "BaseDetector",
    "BoundingBox",
    "CAMSERV_CLASS_NAMES",
    "COCO_TO_CAMSERV",
    "Detection",
    "DetectorBackend",
    "DetectorFactory",
    "Frame",
    "ONNXDetector",
    "SUPPORTED_CLASSES",
    "UltralyticsDetector",
    "nms",
    # Scene understanding
    "CrowdDensityResult",
    "HazardResult",
    "HazardType",
    "ObservationStatus",
    "SceneAnalyzer",
    "SceneEventType",
    "SceneObservation",
    "TamperingResult",
    "VehicleFlowResult",
    "Zone",
    # Privacy
    "BlurMethod",
    "PrivacyConfig",
    "PrivacyFilter",
    "PrivacyZone",
    # Benchmarking
    "BenchmarkResult",
    "ComparisonReport",
    "InferenceBenchmark",
    "LatencyStats",
    "MemoryUsage",
    # Cinematic HUD & Segmentation
    "CinematicHUDRenderer",
    "ThreatVisualState",
    "SegmentationEngine",
    "SegmentedContour",
    "SkeletalPose",
    "COCO_KEYPOINT_NAMES",
    "COCO_SKELETON_PAIRS",
]
