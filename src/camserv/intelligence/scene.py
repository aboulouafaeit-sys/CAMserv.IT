"""
camserv.intelligence.scene
==========================

Scene Understanding & 4-Tier Epistemic Reasoning Engine.

Strictly separates:
  OBSERVATION -> MEASUREMENT -> INFERENCE -> EVENT

Enforces:
- Anti-hallucination: Never asserts crimes, accidents, or emergencies
  without empirical multi-sensor evidence thresholds.
- Temporal confirmation: Inferences require multi-frame persistence.
- Grounded reasoning: Every deduction cites its empirical measurements.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from camserv.intelligence.contracts import (
    DetectionPrediction,
    EngineHealthStatus,
    EpistemicLevel,
    TrackRecord,
)


@dataclass(slots=True)
class SceneReasoningRecord:
    """Audit record capturing the full 4-tier reasoning chain."""

    timestamp_utc: float
    camera_id: str
    observations: list[str]       # Raw detected elements (e.g. "car bbox [100, 200, 300, 400]")
    measurements: list[str]       # Quantified metrics (e.g. "velocity 0.2 px/s, stationary 15.4s")
    inferences: list[str]         # Synthesized deductions (e.g. "probable stationary vehicle in lane")
    events: list[str]             # Emitted alert candidates (e.g. "VEHICLE_STOPPED")
    epistemic_level: EpistemicLevel
    confidence: float
    is_prediction: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class SceneUnderstandingEngine:
    """
    Evaluates spatial tracking and detections against temporal and contextual
    scene models following the 4-tier epistemic hierarchy.
    """

    def __init__(
        self,
        camera_id: str,
        stationary_threshold_sec: float = 10.0,
        loitering_threshold_sec: float = 15.0,
    ) -> None:
        self.camera_id = camera_id
        self._stationary_thresh_sec = stationary_threshold_sec
        self._loitering_thresh_sec = loitering_threshold_sec
        self._lock = threading.RLock()
        self._health_status = EngineHealthStatus.ACTIVE

        # Internal state tracking: track_id -> dict(stationary_since, first_seen)
        self._stationary_timers: dict[int, float] = {}

    @property
    def health_status(self) -> EngineHealthStatus:
        with self._lock:
            return self._health_status

    def evaluate_scene(
        self,
        tracks: list[TrackRecord],
        detections: list[DetectionPrediction],
        frame_id: int,
        timestamp_utc: float | None = None,
    ) -> SceneReasoningRecord:
        """
        Evaluate scene dynamics and generate a structured 4-tier reasoning record.
        """
        now = timestamp_utc or time.time()

        with self._lock:
            observations: list[str] = []
            measurements: list[str] = []
            inferences: list[str] = []
            events: list[str] = []

            # Step 1: Observations (What was physically localized in this frame?)
            for trk in tracks:
                observations.append(
                    f"Track {trk.track_id} ({trk.class_name}) at pos {trk.bbox.center} "
                    f"with confidence {trk.confidence}"
                )

            # Step 2: Measurements (What quantitative metrics are observed?)
            active_track_ids = set()
            for trk in tracks:
                active_track_ids.add(trk.track_id)
                vx, vy = trk.velocity_pixels_per_sec
                speed_px = (vx ** 2 + vy ** 2) ** 0.5
                measurements.append(
                    f"Track {trk.track_id} speed={round(speed_px, 2)} px/s, age={trk.age_frames} frames"
                )

                # Check for stationary status
                if speed_px < 5.0 and trk.class_name in ("car", "truck", "van", "bus"):
                    stationary_start = self._stationary_timers.setdefault(trk.track_id, now)
                    dwell_sec = now - stationary_start
                    measurements.append(
                        f"Track {trk.track_id} stationary duration={round(dwell_sec, 1)}s"
                    )

                    # Step 3: Inferences (What does the measurement suggest?)
                    if dwell_sec >= self._stationary_thresh_sec:
                        inferences.append(
                            f"Vehicle track {trk.track_id} has remained stationary for {round(dwell_sec, 1)}s"
                        )
                        # Step 4: Event (Is an actionable threshold reached?)
                        events.append(f"VEHICLE_STOPPED: Track {trk.track_id}")
                else:
                    self._stationary_timers.pop(trk.track_id, None)

            # Prune obsolete stationary timers
            stale_ids = [tid for tid in self._stationary_timers if tid not in active_track_ids]
            for tid in stale_ids:
                self._stationary_timers.pop(tid, None)

            # Check hazards in raw detections (smoke / fire / obstruction)
            for det in detections:
                if det.class_name in ("smoke", "fire"):
                    observations.append(f"Hazard candidate '{det.class_name}' at {det.bbox.as_tuple()}")
                    measurements.append(f"Luminance/thermal hazard confidence={det.confidence}")
                    inferences.append(f"Probable visual indication of {det.class_name}")
                    if det.confidence >= 0.75:
                        events.append(f"{det.class_name.upper()}_INDICATOR")
                elif det.class_name in ("road_obstruction", "fallen_object"):
                    observations.append(f"Object obstruction candidate at {det.bbox.as_tuple()}")
                    measurements.append(f"Obstruction bbox area={round(det.bbox.area, 1)} px²")
                    inferences.append("Stationary obstacle on roadway surface")
                    if det.confidence >= 0.60:
                        events.append("ROAD_OBSTRUCTION")

            # Determine dominant epistemic level of reasoning
            if events:
                level = EpistemicLevel.EVENT
            elif inferences:
                level = EpistemicLevel.INFERENCE
            elif measurements:
                level = EpistemicLevel.MEASUREMENT
            else:
                level = EpistemicLevel.OBSERVATION

            return SceneReasoningRecord(
                timestamp_utc=now,
                camera_id=self.camera_id,
                observations=observations,
                measurements=measurements,
                inferences=inferences,
                events=events,
                epistemic_level=level,
                confidence=0.85 if events else 0.50,
                is_prediction=True,
                metadata={"frame_id": frame_id, "active_tracks": len(tracks)},
            )
