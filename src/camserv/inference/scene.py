"""Scene understanding module for CAMserv.

Builds higher-level situational awareness on top of raw detections: crowd
density, vehicle flow, environmental hazards (smoke / fire), camera-tampering
detection, and multi-camera event correlation.

All outputs carry confidence scores and uncertainty bounds.  Observations are
classified as *verified* (multi-frame confirmed) or *uncertain* (single-frame).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Sequence

import numpy as np
import structlog

from camserv.inference.detector import Detection

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class ObservationStatus(str, Enum):
    """Whether an observation has been confirmed across multiple frames."""

    UNCERTAIN = "uncertain"    # single-frame only
    VERIFIED = "verified"      # confirmed across ≥ N frames


class HazardType(str, Enum):
    FIRE = "fire"
    SMOKE = "smoke"


class SceneEventType(str, Enum):
    CROWD_DENSITY = "crowd_density"
    VEHICLE_FLOW = "vehicle_flow"
    HAZARD = "hazard"
    TAMPERING = "tampering"
    CORRELATED = "correlated_event"


@dataclass(slots=True)
class Zone:
    """A named rectangular region in image coordinates."""

    name: str
    x1: float
    y1: float
    x2: float
    y2: float

    def contains_centre(self, bbox: tuple[float, float, float, float]) -> bool:
        """Check if the centre of *bbox* falls within this zone."""
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2
        return self.x1 <= cx <= self.x2 and self.y1 <= cy <= self.y2


@dataclass(slots=True)
class SceneObservation:
    """A single scene-level observation with confidence and status."""

    event_type: SceneEventType
    camera_id: str
    timestamp: datetime
    confidence: float
    status: ObservationStatus
    description: str
    details: dict[str, Any] = field(default_factory=dict)
    uncertainty_lower: float = 0.0
    uncertainty_upper: float = 1.0

    @property
    def is_verified(self) -> bool:
        return self.status == ObservationStatus.VERIFIED


@dataclass(slots=True)
class CrowdDensityResult:
    """Crowd density estimate for a zone."""

    zone_name: str
    count: int
    density: float  # people per unit area (normalised)
    confidence: float
    uncertainty_lower: float
    uncertainty_upper: float
    status: ObservationStatus


@dataclass(slots=True)
class VehicleFlowResult:
    """Vehicle flow estimate for a zone."""

    zone_name: str
    vehicle_count: int
    flow_rate: float  # vehicles per second (smoothed)
    composition: dict[str, int]  # class_name → count
    confidence: float
    status: ObservationStatus


@dataclass(slots=True)
class HazardResult:
    """Environmental hazard observation."""

    hazard_type: HazardType
    bbox: tuple[float, float, float, float]
    confidence: float
    frame_count: int  # consecutive frames detected
    status: ObservationStatus
    requires_verification: bool = True


@dataclass(slots=True)
class TamperingResult:
    """Camera tampering / scene-change indicator."""

    camera_id: str
    score: float  # 0 = normal, 1 = fully tampered
    confidence: float
    status: ObservationStatus
    description: str


# ---------------------------------------------------------------------------
# Scene analyser
# ---------------------------------------------------------------------------

# How many consecutive frames a hazard must appear in to be "verified".
_HAZARD_CONFIRM_FRAMES: int = 3
# History window for flow-rate estimation (seconds).
_FLOW_WINDOW_SEC: float = 10.0
# Default tampering threshold on structural similarity drop.
_TAMPER_THRESHOLD: float = 0.35


class SceneAnalyzer:
    """Higher-level scene understanding built on top of raw detections.

    Parameters
    ----------
    zones:
        Named rectangular regions for crowd / vehicle counting.
    hazard_confirm_frames:
        Number of consecutive frames a hazard must appear in before it is
        promoted to *verified*.
    tamper_threshold:
        Structural-similarity drop threshold for tampering detection.
    """

    def __init__(
        self,
        zones: Sequence[Zone] | None = None,
        hazard_confirm_frames: int = _HAZARD_CONFIRM_FRAMES,
        tamper_threshold: float = _TAMPER_THRESHOLD,
    ) -> None:
        self._zones = list(zones or [])
        self._hazard_confirm = hazard_confirm_frames
        self._tamper_threshold = tamper_threshold

        # Per-camera hazard tracking: camera_id → {class_name → consecutive count}
        self._hazard_streaks: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        # Per-camera latest hazard bboxes for correlation
        self._hazard_bboxes: dict[str, dict[str, tuple[float, float, float, float]]] = (
            defaultdict(dict)
        )

        # Per-camera vehicle timestamp history for flow estimation
        self._vehicle_history: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=500)
        )

        # Per-camera reference frame for tampering detection
        self._reference_frames: dict[str, np.ndarray] = {}

        # Cross-camera event buffer for correlation (camera_id → list of SceneObservation)
        self._event_buffer: dict[str, list[SceneObservation]] = defaultdict(list)

    # --------------------------------------------------------------------- #
    # Crowd density
    # --------------------------------------------------------------------- #

    def estimate_crowd_density(
        self,
        detections: list[Detection],
        frame_shape: tuple[int, ...],
    ) -> list[CrowdDensityResult]:
        """Count persons in each zone and return density estimates.

        If no zones are configured the entire frame is treated as a single
        zone.
        """
        person_boxes = [
            d.bbox for d in detections if d.class_name == "person"
        ]

        zones = self._zones or [
            Zone("full_frame", 0, 0, float(frame_shape[1]), float(frame_shape[0]))
        ]

        results: list[CrowdDensityResult] = []
        for zone in zones:
            in_zone = [b for b in person_boxes if zone.contains_centre(b)]
            count = len(in_zone)
            area = max((zone.x2 - zone.x1) * (zone.y2 - zone.y1), 1.0)
            density = count / (area / 1e4)  # per 10k px²

            # Confidence degrades at very high or very low counts
            conf = min(0.95, 0.5 + 0.05 * count) if count > 0 else 0.8
            margin = max(1, int(count * 0.15))

            results.append(
                CrowdDensityResult(
                    zone_name=zone.name,
                    count=count,
                    density=round(density, 4),
                    confidence=round(conf, 3),
                    uncertainty_lower=max(0, count - margin),
                    uncertainty_upper=count + margin,
                    status=ObservationStatus.VERIFIED
                    if count >= 2
                    else ObservationStatus.UNCERTAIN,
                )
            )

        logger.debug("crowd_density_estimated", zones=len(results))
        return results

    # --------------------------------------------------------------------- #
    # Vehicle flow
    # --------------------------------------------------------------------- #

    _VEHICLE_CLASSES: set[str] = {"vehicle", "car", "truck", "bicycle", "motorcycle"}

    def analyse_vehicle_flow(
        self,
        detections: list[Detection],
        camera_id: str,
        timestamp: float | None = None,
    ) -> list[VehicleFlowResult]:
        """Estimate vehicle flow rate and composition per zone."""
        ts = timestamp or time.time()
        vehicle_dets = [d for d in detections if d.class_name in self._VEHICLE_CLASSES]

        # Record timestamp for each vehicle detection
        for _ in vehicle_dets:
            self._vehicle_history[camera_id].append(ts)

        # Compute flow rate over window
        history = self._vehicle_history[camera_id]
        cutoff = ts - _FLOW_WINDOW_SEC
        recent = [t for t in history if t >= cutoff]
        flow_rate = len(recent) / _FLOW_WINDOW_SEC if recent else 0.0

        zones = self._zones or [
            Zone("full_frame", 0, 0, float("inf"), float("inf"))
        ]

        results: list[VehicleFlowResult] = []
        for zone in zones:
            in_zone = [d for d in vehicle_dets if zone.contains_centre(d.bbox)]
            composition: dict[str, int] = defaultdict(int)
            for d in in_zone:
                composition[d.class_name] += 1

            count = len(in_zone)
            conf = min(0.95, 0.6 + 0.03 * count) if count > 0 else 0.7

            results.append(
                VehicleFlowResult(
                    zone_name=zone.name,
                    vehicle_count=count,
                    flow_rate=round(flow_rate, 3),
                    composition=dict(composition),
                    confidence=round(conf, 3),
                    status=ObservationStatus.VERIFIED
                    if count >= 3
                    else ObservationStatus.UNCERTAIN,
                )
            )

        logger.debug("vehicle_flow_analysed", camera=camera_id, vehicles=len(vehicle_dets))
        return results

    # --------------------------------------------------------------------- #
    # Environmental hazards (fire / smoke)
    # --------------------------------------------------------------------- #

    def detect_hazards(
        self,
        detections: list[Detection],
        camera_id: str,
    ) -> list[HazardResult]:
        """Detect fire / smoke with multi-frame confirmation."""
        hazard_classes = {"fire", "smoke"}
        current_hazards: set[str] = set()
        results: list[HazardResult] = []

        for d in detections:
            if d.class_name not in hazard_classes:
                continue

            current_hazards.add(d.class_name)
            self._hazard_streaks[camera_id][d.class_name] += 1
            self._hazard_bboxes[camera_id][d.class_name] = d.bbox
            streak = self._hazard_streaks[camera_id][d.class_name]

            verified = streak >= self._hazard_confirm
            results.append(
                HazardResult(
                    hazard_type=HazardType(d.class_name),
                    bbox=d.bbox,
                    confidence=round(d.confidence, 4),
                    frame_count=streak,
                    status=ObservationStatus.VERIFIED
                    if verified
                    else ObservationStatus.UNCERTAIN,
                    requires_verification=not verified,
                )
            )

            if verified:
                logger.warning(
                    "hazard_verified",
                    type=d.class_name,
                    camera=camera_id,
                    frames=streak,
                    confidence=d.confidence,
                )

        # Reset streaks for hazards not seen in this frame
        for cls_name in list(self._hazard_streaks[camera_id]):
            if cls_name not in current_hazards:
                self._hazard_streaks[camera_id][cls_name] = 0

        return results

    # --------------------------------------------------------------------- #
    # Camera tampering / scene-change detection
    # --------------------------------------------------------------------- #

    def detect_tampering(
        self,
        frame: np.ndarray,
        camera_id: str,
    ) -> TamperingResult:
        """Detect significant scene changes that may indicate camera tampering.

        Compares the current frame against a slowly-updated reference using a
        simple structural similarity proxy (normalised mean-squared error on
        downscaled greyscale).
        """
        import cv2  # type: ignore[import-untyped]

        small = cv2.resize(
            cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (64, 64)
        ).astype(np.float32)

        if camera_id not in self._reference_frames:
            self._reference_frames[camera_id] = small
            return TamperingResult(
                camera_id=camera_id,
                score=0.0,
                confidence=0.5,
                status=ObservationStatus.UNCERTAIN,
                description="Reference frame initialised; no comparison yet.",
            )

        ref = self._reference_frames[camera_id]
        mse = float(np.mean((small - ref) ** 2)) / (255.0 ** 2)
        score = min(1.0, mse / self._tamper_threshold)

        # Slowly update reference (exponential moving average)
        alpha = 0.01
        self._reference_frames[camera_id] = (
            ref * (1 - alpha) + small * alpha
        ).astype(np.float32)

        if score > 0.8:
            status = ObservationStatus.VERIFIED
            desc = "Significant scene change detected — possible tampering."
            logger.warning("tampering_detected", camera=camera_id, score=round(score, 3))
        elif score > 0.4:
            status = ObservationStatus.UNCERTAIN
            desc = "Moderate scene change detected — monitoring."
        else:
            status = ObservationStatus.UNCERTAIN
            desc = "Scene stable."

        return TamperingResult(
            camera_id=camera_id,
            score=round(score, 4),
            confidence=round(min(0.95, 0.5 + score * 0.4), 3),
            status=status,
            description=desc,
        )

    # --------------------------------------------------------------------- #
    # Multi-camera correlation
    # --------------------------------------------------------------------- #

    def correlate_events(
        self,
        observations: list[SceneObservation],
        *,
        time_window_sec: float = 5.0,
        spatial_overlap_threshold: float = 0.3,
    ) -> list[SceneObservation]:
        """Correlate events across cameras by time and spatial proximity.

        Events of the same type occurring within *time_window_sec* on
        different cameras and (if applicable) with overlapping bounding boxes
        are merged into a single correlated observation.
        """
        # Buffer incoming observations
        for obs in observations:
            self._event_buffer[obs.camera_id].append(obs)

        correlated: list[SceneObservation] = []
        seen_pairs: set[tuple[str, str]] = set()

        cameras = list(self._event_buffer.keys())
        for i, cam_a in enumerate(cameras):
            for cam_b in cameras[i + 1 :]:
                pair_key = (cam_a, cam_b)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                for obs_a in self._event_buffer[cam_a]:
                    for obs_b in self._event_buffer[cam_b]:
                        if obs_a.event_type != obs_b.event_type:
                            continue
                        dt = abs(
                            (obs_a.timestamp - obs_b.timestamp).total_seconds()
                        )
                        if dt > time_window_sec:
                            continue

                        # Spatial check via bbox overlap in details if present
                        bbox_a = obs_a.details.get("bbox")
                        bbox_b = obs_b.details.get("bbox")
                        if bbox_a and bbox_b:
                            overlap = self._iou(bbox_a, bbox_b)
                            if overlap < spatial_overlap_threshold:
                                continue

                        avg_conf = (obs_a.confidence + obs_b.confidence) / 2
                        correlated.append(
                            SceneObservation(
                                event_type=SceneEventType.CORRELATED,
                                camera_id=f"{cam_a}+{cam_b}",
                                timestamp=max(obs_a.timestamp, obs_b.timestamp),
                                confidence=round(avg_conf, 4),
                                status=ObservationStatus.VERIFIED
                                if obs_a.is_verified or obs_b.is_verified
                                else ObservationStatus.UNCERTAIN,
                                description=(
                                    f"Correlated {obs_a.event_type.value} across "
                                    f"{cam_a} and {cam_b} (dt={dt:.1f}s)"
                                ),
                                details={
                                    "source_cameras": [cam_a, cam_b],
                                    "time_delta_sec": round(dt, 2),
                                    "original_types": [
                                        obs_a.event_type.value,
                                        obs_b.event_type.value,
                                    ],
                                },
                                uncertainty_lower=min(
                                    obs_a.uncertainty_lower, obs_b.uncertainty_lower
                                ),
                                uncertainty_upper=max(
                                    obs_a.uncertainty_upper, obs_b.uncertainty_upper
                                ),
                            )
                        )

        if correlated:
            logger.info("events_correlated", count=len(correlated))

        # Prune old events (keep last 100 per camera)
        for cam in self._event_buffer:
            if len(self._event_buffer[cam]) > 100:
                self._event_buffer[cam] = self._event_buffer[cam][-100:]

        return correlated

    # --------------------------------------------------------------------- #
    # Full scene analysis convenience method
    # --------------------------------------------------------------------- #

    def analyse(
        self,
        detections: list[Detection],
        frame: np.ndarray,
        camera_id: str,
        timestamp: datetime | None = None,
    ) -> list[SceneObservation]:
        """Run all scene analyses and return a unified list of observations."""
        ts = timestamp or datetime.now(tz=timezone.utc)
        results: list[SceneObservation] = []

        # Crowd density
        for cd in self.estimate_crowd_density(detections, frame.shape):
            results.append(
                SceneObservation(
                    event_type=SceneEventType.CROWD_DENSITY,
                    camera_id=camera_id,
                    timestamp=ts,
                    confidence=cd.confidence,
                    status=cd.status,
                    description=f"Zone '{cd.zone_name}': {cd.count} persons (density {cd.density})",
                    details={
                        "zone": cd.zone_name,
                        "count": cd.count,
                        "density": cd.density,
                    },
                    uncertainty_lower=float(cd.uncertainty_lower),
                    uncertainty_upper=float(cd.uncertainty_upper),
                )
            )

        # Vehicle flow
        for vf in self.analyse_vehicle_flow(detections, camera_id, ts.timestamp()):
            results.append(
                SceneObservation(
                    event_type=SceneEventType.VEHICLE_FLOW,
                    camera_id=camera_id,
                    timestamp=ts,
                    confidence=vf.confidence,
                    status=vf.status,
                    description=(
                        f"Zone '{vf.zone_name}': {vf.vehicle_count} vehicles, "
                        f"flow {vf.flow_rate}/s"
                    ),
                    details={
                        "zone": vf.zone_name,
                        "count": vf.vehicle_count,
                        "flow_rate": vf.flow_rate,
                        "composition": vf.composition,
                    },
                )
            )

        # Hazards
        for hz in self.detect_hazards(detections, camera_id):
            results.append(
                SceneObservation(
                    event_type=SceneEventType.HAZARD,
                    camera_id=camera_id,
                    timestamp=ts,
                    confidence=hz.confidence,
                    status=hz.status,
                    description=(
                        f"{hz.hazard_type.value} detected "
                        f"({'VERIFIED' if hz.status == ObservationStatus.VERIFIED else 'unconfirmed'}, "
                        f"{hz.frame_count} frames)"
                    ),
                    details={
                        "hazard_type": hz.hazard_type.value,
                        "bbox": hz.bbox,
                        "frame_count": hz.frame_count,
                        "requires_verification": hz.requires_verification,
                    },
                )
            )

        # Tampering
        tamper = self.detect_tampering(frame, camera_id)
        results.append(
            SceneObservation(
                event_type=SceneEventType.TAMPERING,
                camera_id=camera_id,
                timestamp=ts,
                confidence=tamper.confidence,
                status=tamper.status,
                description=tamper.description,
                details={"score": tamper.score},
            )
        )

        return results

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #

    @staticmethod
    def _iou(
        a: tuple[float, float, float, float],
        b: tuple[float, float, float, float],
    ) -> float:
        """Compute Intersection-over-Union for two bounding boxes."""
        x1 = max(a[0], b[0])
        y1 = max(a[1], b[1])
        x2 = min(a[2], b[2])
        y2 = min(a[3], b[3])
        inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        area_a = (a[2] - a[0]) * (a[3] - a[1])
        area_b = (b[2] - b[0]) * (b[3] - b[1])
        return inter / (area_a + area_b - inter + 1e-6)
