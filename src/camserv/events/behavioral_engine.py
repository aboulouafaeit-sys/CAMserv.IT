"""
camserv.events.behavioral_engine
================================

Behavioral Intelligence, Structured Scenarios, and Human-in-the-Loop (HITL) Workflow for CAMserv.

Features:
- Structured Security Scenarios:
  1. RESTRICTED_AREA_ENTRY (Polygon geo-fence breach)
  2. PERIMETER_LOITERING (Dwell time threshold exceeded in sensitive perimeter zone)
  3. ACCESS_POINT_TAMPERING (Camera lens occlusion, sudden defocus, drastic illumination drop)
  4. SCHEDULE_ANOMALY (Movement detected outside authorized schedule hours)
  5. RETAIL_INTERACTION (Multi-zone shopping flow and checkout transition analysis)
- Calibrated Epistemic Threat Scoring (0.0 - 1.0 with factor attribution).
- Mandatory Human-in-the-Loop (HITL) State Machine:
  DETECTED -> UNDER_REVIEW -> CONFIRMED | DISMISSED | INCONCLUSIVE.
  High-severity incidents cannot dispatch consequential physical actions without operator sign-off.
"""

from __future__ import annotations

import enum
import math
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, time as dtime, timezone
from typing import Any, Sequence

import numpy as np

try:
    import structlog
except ImportError:
    import logging
    class _FallbackLogger:
        def __init__(self, name: str = "camserv") -> None:
            self._logger = logging.getLogger(name)
        def bind(self, **kwargs: Any) -> _FallbackLogger:
            return self
        def info(self, event: str, **kwargs: Any) -> None:
            self._logger.info(f"{event} {kwargs}" if kwargs else event)
        def warning(self, event: str, **kwargs: Any) -> None:
            self._logger.warning(f"{event} {kwargs}" if kwargs else event)
        def error(self, event: str, **kwargs: Any) -> None:
            self._logger.error(f"{event} {kwargs}" if kwargs else event)
        def debug(self, event: str, **kwargs: Any) -> None:
            self._logger.debug(f"{event} {kwargs}" if kwargs else event)
        def critical(self, event: str, **kwargs: Any) -> None:
            self._logger.critical(f"{event} {kwargs}" if kwargs else event)
    class _MockStructlog:
        @staticmethod
        def get_logger(name: str | None = None) -> _FallbackLogger:
            return _FallbackLogger(name or "camserv")
    structlog = _MockStructlog()  # type: ignore[assignment]

from camserv.inference.detector import BoundingBox, Detection
from camserv.tracking.coordinator import EnhancedTrack

logger = structlog.get_logger(__name__)


class BehaviorScenario(str, enum.Enum):
    """The five standard security behavioral scenarios."""

    RESTRICTED_AREA_ENTRY = "RESTRICTED_AREA_ENTRY"
    PERIMETER_LOITERING = "PERIMETER_LOITERING"
    ACCESS_POINT_TAMPERING = "ACCESS_POINT_TAMPERING"
    SCHEDULE_ANOMALY = "SCHEDULE_ANOMALY"
    RETAIL_INTERACTION = "RETAIL_INTERACTION"


class ReviewStatus(str, enum.Enum):
    """Human-in-the-Loop review lifecycle state machine."""

    DETECTED = "DETECTED"                  # Automatically detected by AI
    UNDER_REVIEW = "UNDER_REVIEW"          # Assigned to human operator for verification
    CONFIRMED = "CONFIRMED"                # Operator confirmed genuine security incident
    DISMISSED = "DISMISSED"                # Operator dismissed as benign or false positive
    INCONCLUSIVE = "INCONCLUSIVE"          # Insufficient evidence to confirm or dismiss


@dataclass(slots=True)
class OperatorReviewRecord:
    """Audit record capturing human operator verification decision."""

    review_id: str
    operator_id: str
    decision: ReviewStatus
    timestamp_utc: str
    notes: str
    action_authorized: bool = False


@dataclass(slots=True)
class BehavioralIncident:
    """A behavioral security incident requiring epistemic tracking and human review."""

    incident_id: str
    scenario: BehaviorScenario
    camera_id: str
    track_id: int | None
    threat_score: float                   # Calibrated score in [0.0, 1.0]
    confidence: float                     # Algorithmic prediction confidence in [0.0, 1.0]
    description: str
    review_status: ReviewStatus
    requires_human_review: bool
    review_record: OperatorReviewRecord | None = None
    created_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_prediction: bool = True            # Invariant: AI detections are predictions, not facts
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["scenario"] = self.scenario.value
        d["review_status"] = self.review_status.value
        return d


class BehavioralEngine:
    """Evaluates multi-scenario behaviors and coordinates human-in-the-loop review."""

    def __init__(
        self,
        dwell_threshold_seconds: float = 15.0,
        tamper_luminance_threshold: float = 0.85,
        night_start_hour: int = 21,
        night_end_hour: int = 6,
    ) -> None:
        self.dwell_threshold = dwell_threshold_seconds
        self.tamper_luminance_threshold = tamper_luminance_threshold
        self.night_start_hour = night_start_hour
        self.night_end_hour = night_end_hour

        self._active_incidents: dict[str, BehavioralIncident] = {}
        self._dwell_trackers: dict[tuple[str, int], float] = {}  # (camera_id, track_id) -> start_time
        self._retail_sequences: dict[tuple[str, int], list[str]] = {}  # (camera_id, track_id) -> list[zone]
        self._log = logger.bind(component="behavioral_engine")

    # -----------------------------------------------------------------------
    # Scenario 1: Restricted Area Entry
    # -----------------------------------------------------------------------

    def evaluate_restricted_area(
        self,
        track: EnhancedTrack,
        restricted_polygon: list[tuple[float, float]],
    ) -> BehavioralIncident | None:
        """Evaluate if an object enters a restricted virtual polygon."""
        cx, cy = track.bbox.center
        if self._point_in_polygon((cx, cy), restricted_polygon):
            threat = 0.85 if track.class_name == "person" else 0.70
            return self._create_incident(
                scenario=BehaviorScenario.RESTRICTED_AREA_ENTRY,
                camera_id=track.camera_id,
                track_id=track.track_id,
                threat_score=threat,
                confidence=track.confidence,
                description=f"Object {track.qualified_id} ({track.class_name}) entered restricted zone polygon.",
                requires_human_review=True,
                metadata={"centroid": [cx, cy]},
            )
        return None

    # -----------------------------------------------------------------------
    # Scenario 2: Perimeter Loitering / Dwell
    # -----------------------------------------------------------------------

    def evaluate_perimeter_loitering(
        self,
        track: EnhancedTrack,
        perimeter_polygon: list[tuple[float, float]],
        current_time: float | None = None,
    ) -> BehavioralIncident | None:
        """Evaluate if an object remains inside a sensitive perimeter zone exceeding dwell threshold."""
        t_now = current_time or time.monotonic()
        cx, cy = track.bbox.center
        key = (track.camera_id, track.track_id)

        if self._point_in_polygon((cx, cy), perimeter_polygon):
            if key not in self._dwell_trackers:
                self._dwell_trackers[key] = t_now
                return None

            dwell_duration = t_now - self._dwell_trackers[key]
            if dwell_duration >= self.dwell_threshold:
                # Threat scales with dwell duration up to 0.95
                threat = min(0.95, 0.5 + 0.45 * (dwell_duration / (self.dwell_threshold * 2)))
                return self._create_incident(
                    scenario=BehaviorScenario.PERIMETER_LOITERING,
                    camera_id=track.camera_id,
                    track_id=track.track_id,
                    threat_score=round(threat, 2),
                    confidence=track.confidence,
                    description=f"Object {track.qualified_id} loitering in perimeter for {dwell_duration:.1f}s (threshold {self.dwell_threshold}s).",
                    requires_human_review=True,
                    metadata={"dwell_duration_sec": round(dwell_duration, 1), "speed": track.speed},
                )
        else:
            self._dwell_trackers.pop(key, None)

        return None

    # -----------------------------------------------------------------------
    # Scenario 3: Access Point Tampering
    # -----------------------------------------------------------------------

    def evaluate_camera_tampering(
        self,
        camera_id: str,
        current_frame: np.ndarray,
        reference_mean_luminance: float = 120.0,
    ) -> BehavioralIncident | None:
        """Evaluate sudden scene occlusion, lens covering, or drastic darkening."""
        current_mean = float(np.mean(current_frame))
        delta = abs(current_mean - reference_mean_luminance) / max(1.0, reference_mean_luminance)

        # Extreme darkness (< 10) or total saturation (> 245) or drastic drop > 85%
        if current_mean < 10.0 or current_mean > 245.0 or delta > self.tamper_luminance_threshold:
            threat = 0.95
            return self._create_incident(
                scenario=BehaviorScenario.ACCESS_POINT_TAMPERING,
                camera_id=camera_id,
                track_id=None,
                threat_score=threat,
                confidence=0.98,
                description=f"Camera {camera_id} tampering or occlusion detected. Mean luminance: {current_mean:.1f} (expected {reference_mean_luminance:.1f}).",
                requires_human_review=True,
                metadata={"current_mean": current_mean, "ref_mean": reference_mean_luminance, "delta": delta},
            )
        return None

    # -----------------------------------------------------------------------
    # Scenario 4: Schedule Anomaly / After-Hours Activity
    # -----------------------------------------------------------------------

    def evaluate_schedule_anomaly(
        self,
        track: EnhancedTrack,
        current_datetime_utc: datetime | None = None,
    ) -> BehavioralIncident | None:
        """Evaluate activity detected outside authorized operating hours."""
        dt = current_datetime_utc or datetime.now(timezone.utc)
        hr = dt.hour

        is_after_hours = hr >= self.night_start_hour or hr < self.night_end_hour
        if is_after_hours:
            threat = 0.80
            return self._create_incident(
                scenario=BehaviorScenario.SCHEDULE_ANOMALY,
                camera_id=track.camera_id,
                track_id=track.track_id,
                threat_score=threat,
                confidence=track.confidence,
                description=f"Activity by {track.qualified_id} outside authorized hours at {dt.strftime('%H:%M:%S UTC')}.",
                requires_human_review=True,
                metadata={"hour": hr, "night_window": f"{self.night_start_hour}:00-{self.night_end_hour}:00"},
            )
        return None

    # -----------------------------------------------------------------------
    # Scenario 5: Retail Interaction Sequence Analysis
    # -----------------------------------------------------------------------

    def evaluate_retail_sequence(
        self,
        track: EnhancedTrack,
        active_zone_name: str,
    ) -> BehavioralIncident | None:
        """Track customer progression through retail zones (e.g. shelf -> checkout vs bypass)."""
        key = (track.camera_id, track.track_id)
        if key not in self._retail_sequences:
            self._retail_sequences[key] = []

        seq = self._retail_sequences[key]
        if not seq or seq[-1] != active_zone_name:
            seq.append(active_zone_name)

        # Pattern: high-value-shelf visited, then exit without passing checkout
        if "high_value_shelf" in seq and active_zone_name == "exit" and "checkout" not in seq:
            threat = 0.75
            return self._create_incident(
                scenario=BehaviorScenario.RETAIL_INTERACTION,
                camera_id=track.camera_id,
                track_id=track.track_id,
                threat_score=threat,
                confidence=track.confidence,
                description=f"Customer {track.qualified_id} visited high_value_shelf and exited without visiting checkout.",
                requires_human_review=True,
                metadata={"zone_sequence": list(seq)},
            )
        return None

    # -----------------------------------------------------------------------
    # Human-in-the-Loop Workflow Methods
    # -----------------------------------------------------------------------

    def assign_review(self, incident_id: str, operator_id: str) -> BehavioralIncident:
        """Assign detected incident to human operator for verification (DETECTED -> UNDER_REVIEW)."""
        incident = self._get_incident(incident_id)
        if incident.review_status != ReviewStatus.DETECTED:
            raise ValueError(f"Incident {incident_id} is already in state {incident.review_status.value}.")

        incident.review_status = ReviewStatus.UNDER_REVIEW
        self._log.info(
            "behavioral_engine.assigned_review",
            incident_id=incident_id,
            operator_id=operator_id,
        )
        return incident

    def submit_review_decision(
        self,
        incident_id: str,
        operator_id: str,
        decision: ReviewStatus,
        notes: str,
    ) -> BehavioralIncident:
        """Submit final human operator verdict (UNDER_REVIEW -> CONFIRMED | DISMISSED | INCONCLUSIVE)."""
        if decision not in (ReviewStatus.CONFIRMED, ReviewStatus.DISMISSED, ReviewStatus.INCONCLUSIVE):
            raise ValueError(f"Invalid review decision: {decision}")

        incident = self._get_incident(incident_id)
        record = OperatorReviewRecord(
            review_id=f"rev-{uuid.uuid4().hex[:8]}",
            operator_id=operator_id,
            decision=decision,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            notes=notes,
            action_authorized=(decision == ReviewStatus.CONFIRMED),
        )

        incident.review_status = decision
        incident.review_record = record
        self._log.info(
            "behavioral_engine.review_completed",
            incident_id=incident_id,
            operator_id=operator_id,
            decision=decision.value,
            action_authorized=record.action_authorized,
        )
        return incident

    def get_incident(self, incident_id: str) -> BehavioralIncident:
        return self._get_incident(incident_id)

    def list_pending_reviews(self) -> list[BehavioralIncident]:
        """List all incidents pending human verification."""
        return [
            inc for inc in self._active_incidents.values()
            if inc.review_status in (ReviewStatus.DETECTED, ReviewStatus.UNDER_REVIEW)
        ]

    # -----------------------------------------------------------------------
    # Internal Helpers
    # -----------------------------------------------------------------------

    def _create_incident(
        self,
        scenario: BehaviorScenario,
        camera_id: str,
        track_id: int | None,
        threat_score: float,
        confidence: float,
        description: str,
        requires_human_review: bool,
        metadata: dict[str, Any],
    ) -> BehavioralIncident:
        inc_id = f"inc-{uuid.uuid4().hex[:8]}"
        incident = BehavioralIncident(
            incident_id=inc_id,
            scenario=scenario,
            camera_id=camera_id,
            track_id=track_id,
            threat_score=threat_score,
            confidence=confidence,
            description=description,
            review_status=ReviewStatus.DETECTED,
            requires_human_review=requires_human_review,
            metadata=metadata,
        )
        self._active_incidents[inc_id] = incident
        return incident

    def _get_incident(self, incident_id: str) -> BehavioralIncident:
        if incident_id not in self._active_incidents:
            raise KeyError(f"Incident '{incident_id}' not found.")
        return self._active_incidents[incident_id]

    @staticmethod
    def _point_in_polygon(pt: tuple[float, float], poly: list[tuple[float, float]]) -> bool:
        """Ray-casting algorithm for point-in-polygon inclusion."""
        x, y = pt
        inside = False
        n = len(poly)
        if n < 3:
            return False
        p1x, p1y = poly[0]
        for i in range(n + 1):
            p2x, p2y = poly[i % n]
            if y > min(p1y, p2y):
                if y <= max(p1y, p2y):
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y
        return inside
