"""
camserv.events.temporal
=======================

Temporal event reasoning engine for CAMserv. Analyzes kinematic trajectories,
multi-frame state transitions, dwell times, and temporal correlations to produce
auditable, explainable security events with complete supporting observation chains.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from camserv.pipeline.interfaces import (
    BoundingBox,
    Detection,
    Event,
    EventSeverity,
    Track,
    TrackState,
)

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class ObservationEvidence:
    """A single atomic observation supporting a higher-level event hypothesis."""

    frame_id: int
    timestamp_utc: str
    track_id: int
    class_name: str
    bbox: tuple[float, float, float, float]
    confidence: float
    description: str


@dataclass(slots=True)
class TemporalTrackState:
    """Historical kinematic observations for a single anonymous track."""

    track_id: int
    camera_id: str
    class_name: str
    first_seen: datetime
    last_seen: datetime
    history_bboxes: list[tuple[int, BoundingBox]] = field(default_factory=list)  # (frame_id, bbox)
    zone_dwell_times: dict[str, float] = field(default_factory=dict)             # zone_id -> seconds
    aspect_ratio_history: list[float] = field(default_factory=list)
    velocity_history: list[tuple[float, float]] = field(default_factory=list)
    is_prostrate: bool = False
    prostrate_duration_sec: float = 0.0


class TemporalEventEngine:
    """Reasoning engine that evaluates temporal progression graphs over sliding windows."""

    MODEL_VERSION = "temporal-graph-v2.1"
    RULE_VERSION = "camserv-rules-2026.11"

    def __init__(
        self,
        max_history_frames: int = 150,
        fall_dwell_threshold_sec: float = 1.5,
        loiter_warning_sec: float = 15.0,
        loiter_critical_sec: float = 30.0,
    ) -> None:
        self.max_history_frames = max_history_frames
        self.fall_dwell_threshold_sec = fall_dwell_threshold_sec
        self.loiter_warning_sec = loiter_warning_sec
        self.loiter_critical_sec = loiter_critical_sec
        self._tracks: dict[int, TemporalTrackState] = {}
        self._cooldowns: dict[str, float] = {}

    def update_track(self, track: Track, frame_id: int, timestamp: datetime) -> None:
        """Update kinematic history for an anonymous track."""
        if track.track_id not in self._tracks:
            self._tracks[track.track_id] = TemporalTrackState(
                track_id=track.track_id,
                camera_id=track.camera_id,
                class_name=track.class_name,
                first_seen=timestamp,
                last_seen=timestamp,
            )

        ts = self._tracks[track.track_id]
        ts.last_seen = timestamp
        ts.history_bboxes.append((frame_id, track.bbox))
        if len(ts.history_bboxes) > self.max_history_frames:
            ts.history_bboxes.pop(0)

        # Aspect ratio = width / height
        ar = track.bbox.width / max(1.0, track.bbox.height)
        ts.aspect_ratio_history.append(ar)
        if len(ts.aspect_ratio_history) > self.max_history_frames:
            ts.aspect_ratio_history.pop(0)

        # Prostrate state check: aspect ratio > 1.25 (wider than tall)
        if ar > 1.25 and track.class_name == "person":
            dt = (timestamp - ts.first_seen).total_seconds()
            ts.prostrate_duration_sec += 0.066  # ~15 fps step
            if ts.prostrate_duration_sec >= self.fall_dwell_threshold_sec:
                ts.is_prostrate = True
        else:
            ts.prostrate_duration_sec = max(0.0, ts.prostrate_duration_sec - 0.1)
            ts.is_prostrate = False

    def evaluate_temporal_events(
        self,
        tracks: list[Track],
        camera_id: str,
        current_time: datetime,
    ) -> list[Event]:
        """Examine temporal state machines and emit explainable events."""
        events: list[Event] = []

        for track in tracks:
            # 1. Fall Detection Temporal Progression
            fall_event = self._check_fall_progression(track, current_time)
            if fall_event:
                events.append(fall_event)

            # 2. Loitering Temporal Dwell
            loiter_event = self._check_loitering_progression(track, current_time)
            if loiter_event:
                events.append(loiter_event)

        # Clean expired tracks
        active_ids = {t.track_id for t in tracks}
        dead_ids = [tid for tid, s in self._tracks.items() if (current_time - s.last_seen).total_seconds() > 10.0]
        for tid in dead_ids:
            self._tracks.pop(tid, None)

        return events

    def _check_fall_progression(self, track: Track, current_time: datetime) -> Event | None:
        """Evaluate multi-frame posture change: upright -> sudden descent -> prostrate dwell."""
        ts = self._tracks.get(track.track_id)
        if not ts or not ts.is_prostrate or track.class_name != "person":
            return None

        # Verify historical aspect ratio transition
        if len(ts.aspect_ratio_history) < 10:
            return None

        earlier_ar = ts.aspect_ratio_history[0]  # Expected < 0.8 for upright human
        current_ar = ts.aspect_ratio_history[-1]

        cooldown_key = f"fall_{track.camera_id}_{track.track_id}"
        now_ts = current_time.timestamp()
        if now_ts - self._cooldowns.get(cooldown_key, 0.0) < 60.0:
            return None

        if earlier_ar < 0.85 and current_ar > 1.2:
            self._cooldowns[cooldown_key] = now_ts
            # Build supporting observations
            observations = [
                ObservationEvidence(
                    frame_id=ts.history_bboxes[0][0],
                    timestamp_utc=ts.first_seen.isoformat(),
                    track_id=track.track_id,
                    class_name=track.class_name,
                    bbox=(ts.history_bboxes[0][1].x1, ts.history_bboxes[0][1].y1, ts.history_bboxes[0][1].x2, ts.history_bboxes[0][1].y2),
                    confidence=track.confidence,
                    description=f"Upright posture observed (aspect_ratio={earlier_ar:.2f})",
                ),
                ObservationEvidence(
                    frame_id=ts.history_bboxes[-1][0],
                    timestamp_utc=current_time.isoformat(),
                    track_id=track.track_id,
                    class_name=track.class_name,
                    bbox=(track.bbox.x1, track.bbox.y1, track.bbox.x2, track.bbox.y2),
                    confidence=track.confidence,
                    description=f"Prostrate posture sustained for {ts.prostrate_duration_sec:.1f}s (aspect_ratio={current_ar:.2f})",
                ),
            ]

            reasoning = (
                f"Anonymous track #{track.track_id} transitioned from an upright stance (aspect_ratio={earlier_ar:.2f}) "
                f"to a prostrate ground position (aspect_ratio={current_ar:.2f}) and remained stationary for {ts.prostrate_duration_sec:.1f}s. "
                "Kinematic pattern satisfies fall event hypothesis."
            )

            return Event(
                event_id=f"evt_{uuid.uuid4().hex[:12]}",
                event_type="fall_detection",
                severity=EventSeverity.CRITICAL,
                confidence=min(0.95, round(track.confidence * 0.92, 2)),
                camera_id=track.camera_id,
                timestamp=current_time,
                requires_verification=True,  # Mandatory human verification for critical events
                description=f"Potential fall detected for Track #{track.track_id} on {track.camera_id}",
                related_track_ids=[track.track_id],
                is_prediction=True,
                metadata={
                    "model_version": self.MODEL_VERSION,
                    "rule_version": self.RULE_VERSION,
                    "reasoning_trace": reasoning,
                    "supporting_observations": [
                        {
                            "frame_id": o.frame_id,
                            "timestamp_utc": o.timestamp_utc,
                            "track_id": o.track_id,
                            "class_name": o.class_name,
                            "bbox": list(o.bbox),
                            "confidence": o.confidence,
                            "description": o.description,
                        }
                        for o in observations
                    ],
                },
            )

        return None

    def _check_loitering_progression(self, track: Track, current_time: datetime) -> Event | None:
        """Evaluate dwell time of an anonymous track in the camera view."""
        ts = self._tracks.get(track.track_id)
        if not ts:
            return None

        dwell_sec = (current_time - ts.first_seen).total_seconds()
        if dwell_sec < self.loiter_warning_sec:
            return None

        cooldown_key = f"loiter_{track.camera_id}_{track.track_id}"
        now_ts = current_time.timestamp()
        if now_ts - self._cooldowns.get(cooldown_key, 0.0) < 45.0:
            return None

        severity = EventSeverity.HIGH if dwell_sec >= self.loiter_critical_sec else EventSeverity.MEDIUM
        req_verify = severity == EventSeverity.HIGH

        self._cooldowns[cooldown_key] = now_ts
        reasoning = (
            f"Anonymous track #{track.track_id} ({track.class_name}) has remained continuously active "
            f"within field of view for {dwell_sec:.1f}s, exceeding configured threshold ({self.loiter_warning_sec}s)."
        )

        return Event(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            event_type="loitering",
            severity=severity,
            confidence=round(min(0.99, 0.70 + (dwell_sec / 100.0)), 2),
            camera_id=track.camera_id,
            timestamp=current_time,
            requires_verification=req_verify,
            description=f"Extended dwell/loitering ({dwell_sec:.1f}s) for Track #{track.track_id}",
            related_track_ids=[track.track_id],
            is_prediction=True,
            metadata={
                "model_version": self.MODEL_VERSION,
                "rule_version": self.RULE_VERSION,
                "dwell_duration_sec": round(dwell_sec, 1),
                "reasoning_trace": reasoning,
            },
        )
