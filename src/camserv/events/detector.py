"""Event detection engine for CAMserv.

Provides rule-based and anomaly event detection over tracked objects and video frames:
- Zone intrusion (point-in-polygon)
- Fall detection (aspect ratio transition + velocity drop)
- Abandoned object (stationary object without nearby person)
- Crowd density anomaly (zone occupancy limit exceeded)
- Camera tamper (scene change / frame difference anomaly)
- Loitering (zone dwell time exceeded)
- Vehicle wrong way (trajectory opposed to flow vector)
- Equipment failure (sensor/camera anomaly)

**All events carry confidence scores and are explicitly labeled as predictions.**
All consequential events (severity >= HIGH) default to ``requires_human_verification=True``.
"""

from __future__ import annotations

import enum
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

import numpy as np

try:
    import structlog
    logger = structlog.get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from camserv.pipeline.interfaces import (
    BoundingBox,
    Detection,
    Event,
    EventSeverity,
    Frame,
    Track,
)

__all__ = [
    "EventDetector",
    "EventType",
    "EventState",
    "EventRule",
    "PointInPolygon",
]


# ---------------------------------------------------------------------------
# Helper Awaitable list for dual sync/async compatibility
# ---------------------------------------------------------------------------

class AwaitableList(list):
    """A list that can also be awaited in async contexts."""

    def __await__(self):
        async def _resolve():
            return self

        return _resolve().__await__()


# ---------------------------------------------------------------------------
# Event Types and States
# ---------------------------------------------------------------------------

class EventType:
    """Standard security event type identifiers."""

    ZONE_INTRUSION = "zone_intrusion"
    FALL_DETECTION = "fall_detection"
    ABANDONED_OBJECT = "abandoned_object"
    CROWD_DENSITY_ANOMALY = "crowd_density_anomaly"
    CAMERA_TAMPER = "camera_tamper"
    EQUIPMENT_FAILURE = "equipment_failure"
    LOITERING = "loitering"
    VEHICLE_WRONG_WAY = "vehicle_wrong_way"


class EventState(str, enum.Enum):
    """Event lifecycle state machine."""

    DETECTED = "detected"
    PENDING_VERIFICATION = "pending_verification"
    VERIFIED = "verified"
    DISMISSED = "dismissed"


# Default severities for event types
DEFAULT_SEVERITIES: dict[str, EventSeverity] = {
    EventType.ZONE_INTRUSION: EventSeverity.HIGH,
    EventType.FALL_DETECTION: EventSeverity.CRITICAL,
    EventType.ABANDONED_OBJECT: EventSeverity.HIGH,
    EventType.CROWD_DENSITY_ANOMALY: EventSeverity.MEDIUM,
    EventType.CAMERA_TAMPER: EventSeverity.CRITICAL,
    EventType.EQUIPMENT_FAILURE: EventSeverity.HIGH,
    EventType.LOITERING: EventSeverity.MEDIUM,
    EventType.VEHICLE_WRONG_WAY: EventSeverity.HIGH,
}


# ---------------------------------------------------------------------------
# Point in Polygon (Ray Casting Algorithm)
# ---------------------------------------------------------------------------

class PointInPolygon:
    """Ray-casting test to determine if a 2D point lies inside a polygon."""

    @staticmethod
    def contains(point: tuple[float, float], polygon: Sequence[tuple[float, float]]) -> bool:
        """Return True if *point* (x, y) is inside *polygon* [(x1, y1), ...]."""
        n = len(polygon)
        if n < 3:
            return False

        x, y = point
        inside = False

        p1x, p1y = polygon[0]
        for i in range(n + 1):
            p2x, p2y = polygon[i % n]
            if y > min(p1y, p2y):
                if y <= max(p1y, p2y):
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y

        return inside


# ---------------------------------------------------------------------------
# Configurable Rule Definition
# ---------------------------------------------------------------------------

@dataclass
class EventRule:
    """Rule definition for event detection."""

    rule_id: str
    event_type: str
    enabled: bool = True
    severity: EventSeverity | None = None
    zone_id: str = "default"
    polygon: list[tuple[float, float]] = field(default_factory=list)
    cooldown_seconds: float = 30.0
    threshold_seconds: float = 10.0  # For loitering / abandoned object
    capacity_limit: int = 5  # For crowd density
    allowed_direction: tuple[float, float] = (1.0, 0.0)  # For vehicle direction
    classes: list[str] = field(default_factory=lambda: ["person", "car", "truck"])
    min_confidence: float = 0.5
    parameters: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# EventDetector
# ---------------------------------------------------------------------------

class EventDetector:
    """Rule-based and anomaly event detection engine.

    Evaluates configured rules against incoming tracks, detections, and frames.
    All consequential events (severity >= HIGH) default to
    ``requires_human_verification=True``.

    Parameters
    ----------
    rules:
        Initial list of rule definitions or raw rule dictionaries.
    default_cooldown:
        Default cooldown in seconds for event deduplication.
    """

    def __init__(
        self,
        rules: list[EventRule | dict[str, Any]] | None = None,
        default_cooldown: float = 30.0,
    ) -> None:
        self.default_cooldown = default_cooldown
        self.rules: dict[str, EventRule] = {}
        self._cooldown_cache: dict[tuple[str, int | str, str], float] = {}  # (type, track/camera, zone) -> timestamp

        # Dwell tracking: track_id -> dict[zone_id, first_seen_timestamp]
        self._zone_dwell_times: dict[int, dict[str, float]] = {}

        # Stationary tracking: track_id -> dict[str, Any] (first_seen, anchor_center)
        self._stationary_tracks: dict[int, dict[str, Any]] = {}

        # Previous frame buffer for tamper detection: camera_id -> prev_frame_gray
        self._prev_frames: dict[str, np.ndarray] = {}

        # Fall detection tracking: track_id -> list of (timestamp, aspect_ratio)
        self._track_ratios: dict[int, list[tuple[float, float]]] = {}

        # Event state store: event_id -> state
        self._event_states: dict[str, EventState] = {}

        if rules:
            self._load_rules(rules)
        else:
            self._setup_default_rules()

        logger.info("event_detector_init", num_rules=len(self.rules))

    def _setup_default_rules(self) -> None:
        """Configure default out-of-the-box security rules."""
        defaults = [
            EventRule(
                rule_id="default_zone_intrusion",
                event_type=EventType.ZONE_INTRUSION,
                severity=EventSeverity.HIGH,
                zone_id="restricted_zone",
                polygon=[(0, 0), (1000, 0), (1000, 1000), (0, 1000)],
                cooldown_seconds=15.0,
            ),
            EventRule(
                rule_id="default_fall_detection",
                event_type=EventType.FALL_DETECTION,
                severity=EventSeverity.CRITICAL,
                cooldown_seconds=30.0,
            ),
            EventRule(
                rule_id="default_abandoned_object",
                event_type=EventType.ABANDONED_OBJECT,
                severity=EventSeverity.HIGH,
                threshold_seconds=15.0,
                cooldown_seconds=30.0,
            ),
            EventRule(
                rule_id="default_crowd_density",
                event_type=EventType.CROWD_DENSITY_ANOMALY,
                severity=EventSeverity.MEDIUM,
                capacity_limit=10,
                cooldown_seconds=20.0,
            ),
            EventRule(
                rule_id="default_camera_tamper",
                event_type=EventType.CAMERA_TAMPER,
                severity=EventSeverity.CRITICAL,
                cooldown_seconds=60.0,
            ),
            EventRule(
                rule_id="default_loitering",
                event_type=EventType.LOITERING,
                severity=EventSeverity.MEDIUM,
                threshold_seconds=15.0,
                cooldown_seconds=30.0,
            ),
            EventRule(
                rule_id="default_wrong_way",
                event_type=EventType.VEHICLE_WRONG_WAY,
                severity=EventSeverity.HIGH,
                allowed_direction=(1.0, 0.0),
                cooldown_seconds=15.0,
            ),
        ]
        for r in defaults:
            self.rules[r.rule_id] = r

    def _load_rules(self, rules: list[EventRule | dict[str, Any]]) -> None:
        """Parse and register rules."""
        for r in rules:
            if isinstance(r, EventRule):
                self.rules[r.rule_id] = r
            elif isinstance(r, dict):
                sev = r.get("severity")
                if isinstance(sev, str):
                    try:
                        sev = EventSeverity(sev.lower())
                    except ValueError:
                        sev = None
                rule_obj = EventRule(
                    rule_id=r.get("rule_id", str(uuid.uuid4())),
                    event_type=r.get("event_type", EventType.ZONE_INTRUSION),
                    enabled=r.get("enabled", True),
                    severity=sev,
                    zone_id=r.get("zone_id", "default"),
                    polygon=[tuple(p) for p in r.get("polygon", [])],
                    cooldown_seconds=float(r.get("cooldown_seconds", self.default_cooldown)),
                    threshold_seconds=float(r.get("threshold_seconds", 10.0)),
                    capacity_limit=int(r.get("capacity_limit", 5)),
                    allowed_direction=tuple(r.get("allowed_direction", (1.0, 0.0))),
                    classes=r.get("classes", ["person", "car", "truck"]),
                    min_confidence=float(r.get("min_confidence", 0.5)),
                    parameters=r.get("parameters", {}),
                )
                self.rules[rule_obj.rule_id] = rule_obj

    async def configure_rules(self, rules: list[dict[str, Any]]) -> None:
        """Hot-reload detection rules without restarting the pipeline."""
        self.rules.clear()
        self._load_rules(rules)
        logger.info("event_rules_reloaded", count=len(self.rules))

    # ------------------------------------------------------------------
    # Deduplication & Cooldown
    # ------------------------------------------------------------------

    def _is_cooling_down(
        self,
        event_type: str,
        target_id: int | str,
        zone_id: str,
        now_ts: float,
        cooldown_sec: float,
    ) -> bool:
        """Check if an event is in its cooldown period."""
        key = (event_type, target_id, zone_id)
        last_fired = self._cooldown_cache.get(key)
        if last_fired is not None and (now_ts - last_fired) < cooldown_sec:
            return True
        return False

    def _record_fire(
        self,
        event_type: str,
        target_id: int | str,
        zone_id: str,
        now_ts: float,
    ) -> None:
        """Record the fire timestamp for cooldown checking."""
        key = (event_type, target_id, zone_id)
        self._cooldown_cache[key] = now_ts

    # ------------------------------------------------------------------
    # State Machine Transitions
    # ------------------------------------------------------------------

    def get_event_state(self, event_id: str) -> EventState:
        """Query state of an event."""
        return self._event_states.get(event_id, EventState.DETECTED)

    def transition_event_state(
        self,
        event_id: str,
        new_state: EventState,
    ) -> bool:
        """Transition event through lifecycle state machine.

        Allowed transitions:
        - DETECTED -> PENDING_VERIFICATION
        - DETECTED -> VERIFIED
        - DETECTED -> DISMISSED
        - PENDING_VERIFICATION -> VERIFIED
        - PENDING_VERIFICATION -> DISMISSED

        Returns True if transition succeeded.
        """
        curr = self._event_states.get(event_id, EventState.DETECTED)

        valid_transitions = {
            EventState.DETECTED: {
                EventState.PENDING_VERIFICATION,
                EventState.VERIFIED,
                EventState.DISMISSED,
            },
            EventState.PENDING_VERIFICATION: {
                EventState.VERIFIED,
                EventState.DISMISSED,
            },
            EventState.VERIFIED: set(),
            EventState.DISMISSED: set(),
        }

        if new_state in valid_transitions.get(curr, set()):
            self._event_states[event_id] = new_state
            logger.info("event_state_transition", event_id=event_id, from_state=curr.value, to_state=new_state.value)
            return True

        logger.warning(
            "invalid_event_state_transition",
            event_id=event_id,
            from_state=curr.value,
            to_state=new_state.value,
        )
        return False

    # ------------------------------------------------------------------
    # Main Evaluation Loop
    # ------------------------------------------------------------------

    def evaluate(
        self,
        tracks: list[Track],
        detections: list[Detection] | None = None,
        frame: Frame | None = None,
    ) -> AwaitableList:
        """Evaluate rules and detect events from current frame observations.

        Parameters
        ----------
        tracks:
            Active object tracks.
        detections:
            Raw frame detections.
        frame:
            Video frame metadata and image.

        Returns
        -------
        AwaitableList[Event]
            List of detected Event objects. All events have ``is_prediction=True``.
        """
        detections = detections or []
        events: list[Event] = []

        now = frame.timestamp if frame is not None else datetime.now(timezone.utc)
        now_ts = now.timestamp()
        camera_id = frame.camera_id if frame is not None else (tracks[0].camera_id if tracks else "unknown_camera")

        # Clean up stale cooldowns periodically
        if len(self._cooldown_cache) > 2000:
            self._cooldown_cache = {
                k: v for k, v in self._cooldown_cache.items() if (now_ts - v) < 300.0
            }

        # 1. Zone-based rules (Intrusion, Loitering, Crowd Density)
        events.extend(self._evaluate_zone_rules(tracks, now, now_ts, camera_id))

        # 2. Fall detection
        events.extend(self._evaluate_fall_detection(tracks, now, now_ts, camera_id))

        # 3. Abandoned object detection
        events.extend(self._evaluate_abandoned_objects(tracks, detections, now, now_ts, camera_id))

        # 4. Vehicle wrong way
        events.extend(self._evaluate_vehicle_wrong_way(tracks, now, now_ts, camera_id))

        # 5. Camera tamper detection
        if frame is not None and frame.image is not None:
            events.extend(self._evaluate_camera_tamper(frame, now, now_ts))

        # Register states for new events
        for ev in events:
            initial_state = EventState.PENDING_VERIFICATION if ev.requires_verification else EventState.DETECTED
            self._event_states[ev.event_id] = initial_state

        return AwaitableList(events)

    # ------------------------------------------------------------------
    # Rule Evaluation Sub-methods
    # ------------------------------------------------------------------

    def _create_event(
        self,
        event_type: str,
        rule_severity: EventSeverity | None,
        confidence: float,
        camera_id: str,
        timestamp: datetime,
        description: str,
        zone_id: str | None = None,
        related_tracks: list[Track] | None = None,
        related_detections: list[Detection] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Event:
        """Helper to create an Event instance with policy enforcement."""
        # Severity selection: rule override > default for event type > MEDIUM
        severity = rule_severity or DEFAULT_SEVERITIES.get(event_type, EventSeverity.MEDIUM)

        # Consequential events (severity >= HIGH) MUST require human verification
        requires_verification = severity in (EventSeverity.HIGH, EventSeverity.CRITICAL)

        related_track_ids = [t.track_id for t in (related_tracks or [])]

        return Event(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            event_type=event_type,
            severity=severity,
            confidence=max(0.0, min(1.0, float(confidence))),
            camera_id=camera_id,
            timestamp=timestamp,
            requires_verification=requires_verification,
            description=description,
            related_track_ids=related_track_ids,
            related_detections=related_detections or [],
            zone_id=zone_id,
            is_prediction=True,  # predictions are never facts
            metadata=metadata or {},
        )

    def _evaluate_zone_rules(
        self,
        tracks: list[Track],
        now: datetime,
        now_ts: float,
        camera_id: str,
    ) -> list[Event]:
        """Evaluate zone intrusion, loitering, and crowd density."""
        events: list[Event] = []

        # Find all zone rules
        zone_rules = [
            r for r in self.rules.values()
            if r.enabled and r.polygon and len(r.polygon) >= 3
        ]

        for rule in zone_rules:
            tracks_in_zone: list[Track] = []

            for track in tracks:
                if rule.classes and track.class_name not in rule.classes:
                    continue

                # Point in polygon using track bounding box center or bottom center
                cx, cy = track.bbox.center
                # Use bottom center (ground position) for better spatial precision
                ground_pt = (cx, track.bbox.y2)

                if PointInPolygon.contains(ground_pt, rule.polygon) or PointInPolygon.contains((cx, cy), rule.polygon):
                    tracks_in_zone.append(track)

                    # Update dwell times
                    if track.track_id not in self._zone_dwell_times:
                        self._zone_dwell_times[track.track_id] = {}
                    dwells = self._zone_dwell_times[track.track_id]

                    if rule.zone_id not in dwells:
                        dwells[rule.zone_id] = now_ts
                        # Check Zone Intrusion Event
                        if rule.event_type == EventType.ZONE_INTRUSION:
                            if not self._is_cooling_down(
                                EventType.ZONE_INTRUSION,
                                track.track_id,
                                rule.zone_id,
                                now_ts,
                                rule.cooldown_seconds,
                            ):
                                self._record_fire(
                                    EventType.ZONE_INTRUSION,
                                    track.track_id,
                                    rule.zone_id,
                                    now_ts,
                                )
                                ev = self._create_event(
                                    event_type=EventType.ZONE_INTRUSION,
                                    rule_severity=rule.severity,
                                    confidence=track.confidence,
                                    camera_id=camera_id,
                                    timestamp=now,
                                    description=f"Track #{track.track_id} ({track.class_name}) entered restricted zone '{rule.zone_id}'.",
                                    zone_id=rule.zone_id,
                                    related_tracks=[track],
                                    metadata={"zone_id": rule.zone_id, "track_id": track.track_id},
                                )
                                events.append(ev)
                    else:
                        # Check Loitering Event
                        dwell_duration = now_ts - dwells[rule.zone_id]
                        if dwell_duration >= rule.threshold_seconds:
                            if not self._is_cooling_down(
                                EventType.LOITERING,
                                track.track_id,
                                rule.zone_id,
                                now_ts,
                                rule.cooldown_seconds,
                            ):
                                self._record_fire(
                                    EventType.LOITERING,
                                    track.track_id,
                                    rule.zone_id,
                                    now_ts,
                                )
                                ev = self._create_event(
                                    event_type=EventType.LOITERING,
                                    rule_severity=rule.severity,
                                    confidence=track.confidence,
                                    camera_id=camera_id,
                                    timestamp=now,
                                    description=(
                                        f"Track #{track.track_id} loitering in zone '{rule.zone_id}' "
                                        f"for {dwell_duration:.1f}s (threshold: {rule.threshold_seconds}s)."
                                    ),
                                    zone_id=rule.zone_id,
                                    related_tracks=[track],
                                    metadata={"dwell_seconds": dwell_duration},
                                )
                                events.append(ev)
                else:
                    # Exited zone: remove dwell time
                    if track.track_id in self._zone_dwell_times:
                        self._zone_dwell_times[track.track_id].pop(rule.zone_id, None)

            # Check Crowd Density Anomaly
            if rule.event_type == EventType.CROWD_DENSITY_ANOMALY or rule.capacity_limit > 0:
                count = len(tracks_in_zone)
                if count > rule.capacity_limit:
                    if not self._is_cooling_down(
                        EventType.CROWD_DENSITY_ANOMALY,
                        camera_id,
                        rule.zone_id,
                        now_ts,
                        rule.cooldown_seconds,
                    ):
                        self._record_fire(
                            EventType.CROWD_DENSITY_ANOMALY,
                            camera_id,
                            rule.zone_id,
                            now_ts,
                        )
                        ev = self._create_event(
                            event_type=EventType.CROWD_DENSITY_ANOMALY,
                            rule_severity=rule.severity or EventSeverity.MEDIUM,
                            confidence=0.9,
                            camera_id=camera_id,
                            timestamp=now,
                            description=(
                                f"Crowd density anomaly in zone '{rule.zone_id}': "
                                f"{count} objects detected (capacity limit: {rule.capacity_limit})."
                            ),
                            zone_id=rule.zone_id,
                            related_tracks=tracks_in_zone,
                            metadata={"count": count, "capacity": rule.capacity_limit},
                        )
                        events.append(ev)

        return events

    def _evaluate_fall_detection(
        self,
        tracks: list[Track],
        now: datetime,
        now_ts: float,
        camera_id: str,
    ) -> list[Event]:
        """Detect potential human falls via sudden aspect ratio change + low velocity."""
        events: list[Event] = []

        fall_rules = [
            r for r in self.rules.values()
            if r.enabled and r.event_type == EventType.FALL_DETECTION
        ]
        if not fall_rules:
            return events

        rule = fall_rules[0]

        for track in tracks:
            if track.class_name not in ("person", "object", ""):
                continue

            w = max(track.bbox.width, 1.0)
            h = max(track.bbox.height, 1.0)
            # Aspect ratio: height / width (standing person typically > 1.5, lying person < 1.0)
            hw_ratio = h / w

            history = self._track_ratios.setdefault(track.track_id, [])
            history.append((now_ts, hw_ratio))
            # Keep last 15 frames (~0.5 - 1.5s)
            if len(history) > 15:
                history.pop(0)

            if len(history) >= 3:
                prev_ts, prev_ratio = history[0]
                # Check for rapid drop from standing (prev_ratio >= 1.4) to lying (hw_ratio <= 0.8)
                if prev_ratio >= 1.4 and hw_ratio <= 0.8:
                    vx, vy = track.velocity
                    speed = math.hypot(vx, vy)
                    # Low horizontal velocity after falling
                    if speed < 15.0:
                        if not self._is_cooling_down(
                            EventType.FALL_DETECTION,
                            track.track_id,
                            "global",
                            now_ts,
                            rule.cooldown_seconds,
                        ):
                            self._record_fire(
                                EventType.FALL_DETECTION,
                                track.track_id,
                                "global",
                                now_ts,
                            )
                            ev = self._create_event(
                                event_type=EventType.FALL_DETECTION,
                                rule_severity=rule.severity or EventSeverity.CRITICAL,
                                confidence=min(1.0, float(track.confidence * 1.1)),
                                camera_id=camera_id,
                                timestamp=now,
                                description=(
                                    f"Fall detected for track #{track.track_id}: "
                                    f"aspect ratio collapsed from {prev_ratio:.2f} to {hw_ratio:.2f}."
                                ),
                                related_tracks=[track],
                                metadata={"prev_ratio": prev_ratio, "curr_ratio": hw_ratio},
                            )
                            events.append(ev)

        return events

    def _evaluate_abandoned_objects(
        self,
        tracks: list[Track],
        detections: list[Detection],
        now: datetime,
        now_ts: float,
        camera_id: str,
    ) -> list[Event]:
        """Detect stationary objects (e.g. luggage) left unattended without an owner."""
        events: list[Event] = []

        rules = [
            r for r in self.rules.values()
            if r.enabled and r.event_type == EventType.ABANDONED_OBJECT
        ]
        if not rules:
            return events

        rule = rules[0]
        stationary_threshold_dist = rule.parameters.get("stationary_distance", 15.0)
        owner_proximity_dist = rule.parameters.get("owner_proximity", 80.0)

        person_centers = [
            t.bbox.center for t in tracks if t.class_name in ("person", "human")
        ]

        candidate_classes = rule.parameters.get(
            "object_classes", ["backpack", "suitcase", "handbag", "bag", "object"]
        )

        for track in tracks:
            if track.class_name not in candidate_classes:
                continue

            cx, cy = track.bbox.center

            if track.track_id not in self._stationary_tracks:
                self._stationary_tracks[track.track_id] = {
                    "first_seen": now_ts,
                    "anchor": (cx, cy),
                }
            else:
                info = self._stationary_tracks[track.track_id]
                ax, ay = info["anchor"]
                dist = math.hypot(cx - ax, cy - ay)

                if dist > stationary_threshold_dist:
                    # Moved significantly; reset anchor
                    info["anchor"] = (cx, cy)
                    info["first_seen"] = now_ts
                else:
                    duration = now_ts - info["first_seen"]
                    if duration >= rule.threshold_seconds:
                        # Check if any person is within owner_proximity_dist
                        has_nearby_person = any(
                            math.hypot(cx - px, cy - py) < owner_proximity_dist
                            for px, py in person_centers
                        )

                        if not has_nearby_person:
                            if not self._is_cooling_down(
                                EventType.ABANDONED_OBJECT,
                                track.track_id,
                                "global",
                                now_ts,
                                rule.cooldown_seconds,
                            ):
                                self._record_fire(
                                    EventType.ABANDONED_OBJECT,
                                    track.track_id,
                                    "global",
                                    now_ts,
                                )
                                ev = self._create_event(
                                    event_type=EventType.ABANDONED_OBJECT,
                                    rule_severity=rule.severity or EventSeverity.HIGH,
                                    confidence=track.confidence,
                                    camera_id=camera_id,
                                    timestamp=now,
                                    description=(
                                        f"Abandoned object #{track.track_id} ({track.class_name}) "
                                        f"stationary for {duration:.1f}s without nearby person."
                                    ),
                                    related_tracks=[track],
                                    metadata={"stationary_seconds": duration},
                                )
                                events.append(ev)

        return events

    def _evaluate_vehicle_wrong_way(
        self,
        tracks: list[Track],
        now: datetime,
        now_ts: float,
        camera_id: str,
    ) -> list[Event]:
        """Detect vehicles moving against the permitted flow direction."""
        events: list[Event] = []

        rules = [
            r for r in self.rules.values()
            if r.enabled and r.event_type == EventType.VEHICLE_WRONG_WAY
        ]

        for rule in rules:
            allowed_dir = rule.allowed_direction
            norm = math.hypot(allowed_dir[0], allowed_dir[1])
            if norm == 0:
                continue
            u_dir = (allowed_dir[0] / norm, allowed_dir[1] / norm)

            for track in tracks:
                if track.class_name not in ("car", "truck", "bus", "vehicle", "motorcycle"):
                    continue

                vx, vy = track.velocity
                speed = math.hypot(vx, vy)
                if speed < 2.0:
                    continue  # Ignore stationary or slow moving vehicles

                v_norm = (vx / speed, vy / speed)
                dot = v_norm[0] * u_dir[0] + v_norm[1] * u_dir[1]

                # If dot product < -0.5, moving substantially in opposite direction
                if dot < -0.5:
                    if not self._is_cooling_down(
                        EventType.VEHICLE_WRONG_WAY,
                        track.track_id,
                        rule.zone_id,
                        now_ts,
                        rule.cooldown_seconds,
                    ):
                        self._record_fire(
                            EventType.VEHICLE_WRONG_WAY,
                            track.track_id,
                            rule.zone_id,
                            now_ts,
                        )
                        ev = self._create_event(
                            event_type=EventType.VEHICLE_WRONG_WAY,
                            rule_severity=rule.severity or EventSeverity.HIGH,
                            confidence=0.85,
                            camera_id=camera_id,
                            timestamp=now,
                            description=(
                                f"Vehicle #{track.track_id} moving wrong way in '{rule.zone_id}' "
                                f"(alignment: {dot:.2f})."
                            ),
                            zone_id=rule.zone_id,
                            related_tracks=[track],
                            metadata={"alignment": dot, "speed": speed},
                        )
                        events.append(ev)

        return events

    def _evaluate_camera_tamper(
        self,
        frame: Frame,
        now: datetime,
        now_ts: float,
    ) -> list[Event]:
        """Detect camera tampering: occlusion, spray paint, blinding, sudden scene change."""
        events: list[Event] = []

        rules = [
            r for r in self.rules.values()
            if r.enabled and r.event_type == EventType.CAMERA_TAMPER
        ]
        if not rules:
            return events

        rule = rules[0]
        img = frame.image

        # Downsample image for fast analysis
        if img.ndim == 3:
            gray = np.mean(img, axis=2).astype(np.float32)
        else:
            gray = img.astype(np.float32)

        # 1. Low variance check (occlusion, lens covered, total darkness)
        variance = float(np.var(gray))
        mean_val = float(np.mean(gray))

        tamper_detected = False
        reason = ""

        if variance < 10.0:
            tamper_detected = True
            reason = f"Lens covered or occluded (variance: {variance:.1f})"
        elif mean_val > 250.0:
            tamper_detected = True
            reason = f"Camera blinded with high light (mean: {mean_val:.1f})"

        # 2. Frame similarity drop
        cam_id = frame.camera_id
        if cam_id in self._prev_frames and not tamper_detected:
            prev = self._prev_frames[cam_id]
            if prev.shape == gray.shape:
                diff = np.abs(gray - prev)
                mean_diff = float(np.mean(diff))
                # Sudden massive scene change (camera reoriented / swung)
                if mean_diff > 120.0:
                    tamper_detected = True
                    reason = f"Drastic scene change (mean diff: {mean_diff:.1f})"

        self._prev_frames[cam_id] = gray

        if tamper_detected:
            if not self._is_cooling_down(
                EventType.CAMERA_TAMPER,
                cam_id,
                "global",
                now_ts,
                rule.cooldown_seconds,
            ):
                self._record_fire(
                    EventType.CAMERA_TAMPER,
                    cam_id,
                    "global",
                    now_ts,
                )
                ev = self._create_event(
                    event_type=EventType.CAMERA_TAMPER,
                    rule_severity=rule.severity or EventSeverity.CRITICAL,
                    confidence=0.95,
                    camera_id=cam_id,
                    timestamp=now,
                    description=f"Camera tamper detected on {cam_id}: {reason}.",
                    metadata={"reason": reason, "variance": variance, "mean": mean_val},
                )
                events.append(ev)

        return events
