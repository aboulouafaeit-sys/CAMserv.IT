"""
camserv.analytics.zones
=======================

Spatial zone analytics: virtual tripwire line crossing, polygon zone inclusion,
entry/exit tracking, and non-accusatory loitering candidate classification.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def _ccw(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> bool:
    """Return True if points a, b, c are in counter-clockwise order."""
    return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    p4: tuple[float, float],
) -> bool:
    """Determine whether segment p1-p2 intersects segment p3-p4."""
    return (
        _ccw(p1, p3, p4) != _ccw(p2, p3, p4)
        and _ccw(p1, p2, p3) != _ccw(p1, p2, p4)
    )


def _point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    """Ray-casting algorithm to test point inclusion in 2D polygon."""
    x, y = point
    n = len(polygon)
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


@dataclass(slots=True)
class Tripwire:
    """Virtual boundary line with crossing direction enforcement."""

    tripwire_id: str
    camera_id: str
    name: str
    start_point: tuple[float, float]
    end_point: tuple[float, float]
    direction: str = "bidirectional"  # 'bidirectional', 'forward', 'reverse'
    is_active: bool = True

    def check_crossing(
        self,
        prev_pos: tuple[float, float],
        curr_pos: tuple[float, float],
    ) -> bool:
        """Evaluate whether an object trajectory crossed the tripwire line."""
        if not self.is_active:
            return False

        if not _segments_intersect(prev_pos, curr_pos, self.start_point, self.end_point):
            return False

        if self.direction == "bidirectional":
            return True

        # Compute dot product with line normal vector (vy, -vx) to determine crossing direction
        ax, ay = self.start_point
        bx, by = self.end_point
        vx, vy = bx - ax, by - ay
        dx, dy = curr_pos[0] - prev_pos[0], curr_pos[1] - prev_pos[1]

        # Dot product with normal vector (vy, -vx)
        normal_dot = dx * vy - dy * vx
        if self.direction == "forward" and normal_dot > 0:
            return True
        elif self.direction == "reverse" and normal_dot < 0:
            return True

        return False


@dataclass(slots=True)
class PolygonZone:
    """Arbitrary 2D polygon defining a protected perimeter or dwell monitoring area."""

    zone_id: str
    camera_id: str
    name: str
    vertices: list[tuple[float, float]]
    loitering_threshold_sec: float = 10.0  # Seconds before flagging loitering candidate
    is_active: bool = True

    def contains(self, point: tuple[float, float]) -> bool:
        """Check if 2D coordinate falls inside the polygon."""
        if not self.is_active or len(self.vertices) < 3:
            return False
        return _point_in_polygon(point, self.vertices)


@dataclass(slots=True)
class ZoneEventCandidate:
    """Probabilistic spatial event hypothesis."""

    event_type: str  # 'tripwire_crossed', 'zone_entered', 'zone_exited', 'loitering_candidate'
    camera_id: str
    zone_or_tripwire_id: str
    track_id: int
    timestamp_utc: float
    confidence: float
    dwell_duration_sec: float = 0.0
    is_prediction: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ZoneAnalyticsEngine:
    """
    Evaluates tracking trajectories against defined tripwires and polygon zones.
    """

    def __init__(self) -> None:
        self.tripwires: dict[str, list[Tripwire]] = {}
        self.zones: dict[str, list[PolygonZone]] = {}

        # Tracking state: camera_id -> track_id -> dict(last_pos, enter_time, in_zones)
        self._track_states: dict[str, dict[int, dict[str, Any]]] = {}

    def add_tripwire(self, tripwire: Tripwire) -> None:
        """Register a tripwire line."""
        self.tripwires.setdefault(tripwire.camera_id, []).append(tripwire)

    register_tripwire = add_tripwire

    def add_zone(self, zone: PolygonZone) -> None:
        """Register a polygon zone."""
        self.zones.setdefault(zone.camera_id, []).append(zone)

    register_zone = add_zone

    def evaluate_tracks(
        self,
        camera_id: str,
        tracks: list[dict[str, Any]],
        timestamp_utc: float | None = None,
    ) -> list[ZoneEventCandidate]:
        """
        Evaluate active tracks against registered tripwires and zones.
        Each track dict should contain: 'track_id', 'bbox' or 'ground_contact' [x, y], 'confidence'.
        """
        now = timestamp_utc or time.time()
        events: list[ZoneEventCandidate] = []
        cam_states = self._track_states.setdefault(camera_id, {})
        active_ids = set()

        for trk in tracks:
            track_id = int(trk["track_id"])
            active_ids.add(track_id)
            conf = float(trk.get("confidence", 0.85))

            # Determine point of interest (ground contact center)
            if "ground_contact" in trk:
                pos = tuple(trk["ground_contact"])
            elif "bbox" in trk:
                bbox = trk["bbox"]  # [x1, y1, x2, y2]
                pos = ((bbox[0] + bbox[2]) / 2.0, bbox[3])
            else:
                continue

            prev_state = cam_states.get(track_id)

            if prev_state is not None:
                prev_pos = prev_state["last_pos"]

                # 1. Evaluate Tripwires
                for tw in self.tripwires.get(camera_id, []):
                    if tw.check_crossing(prev_pos, pos):
                        events.append(
                            ZoneEventCandidate(
                                event_type="tripwire_crossed",
                                camera_id=camera_id,
                                zone_or_tripwire_id=tw.tripwire_id,
                                track_id=track_id,
                                timestamp_utc=now,
                                confidence=conf,
                                metadata={"tripwire_name": tw.name},
                            )
                        )

                # 2. Evaluate Polygon Zones (Entry, Exit, Loitering)
                for zone in self.zones.get(camera_id, []):
                    is_inside = zone.contains(pos)
                    was_inside = zone.zone_id in prev_state["in_zones"]

                    if is_inside and not was_inside:
                        # Entry Event
                        prev_state["in_zones"][zone.zone_id] = now
                        events.append(
                            ZoneEventCandidate(
                                event_type="zone_entered",
                                camera_id=camera_id,
                                zone_or_tripwire_id=zone.zone_id,
                                track_id=track_id,
                                timestamp_utc=now,
                                confidence=conf,
                                metadata={"zone_name": zone.name},
                            )
                        )
                    elif not is_inside and was_inside:
                        # Exit Event
                        entry_time = prev_state["in_zones"].pop(zone.zone_id, now)
                        dwell = now - entry_time
                        events.append(
                            ZoneEventCandidate(
                                event_type="zone_exited",
                                camera_id=camera_id,
                                zone_or_tripwire_id=zone.zone_id,
                                track_id=track_id,
                                timestamp_utc=now,
                                confidence=conf,
                                dwell_duration_sec=round(dwell, 1),
                                metadata={"zone_name": zone.name},
                            )
                        )
                    elif is_inside and was_inside:
                        # Check Loitering
                        entry_time = prev_state["in_zones"][zone.zone_id]
                        dwell = now - entry_time
                        if dwell >= zone.loitering_threshold_sec:
                            # Flag loitering candidate if not already flagged in metadata
                            flagged = prev_state.setdefault("loitering_flagged", set())
                            if zone.zone_id not in flagged:
                                flagged.add(zone.zone_id)
                                events.append(
                                    ZoneEventCandidate(
                                        event_type="loitering_candidate",
                                        camera_id=camera_id,
                                        zone_or_tripwire_id=zone.zone_id,
                                        track_id=track_id,
                                        timestamp_utc=now,
                                        confidence=conf,
                                        dwell_duration_sec=round(dwell, 1),
                                        metadata={"zone_name": zone.name, "threshold_sec": zone.loitering_threshold_sec},
                                    )
                                )

                prev_state["last_pos"] = pos
                prev_state["last_seen"] = now
            else:
                # Initialize new track
                in_zones = {}
                for zone in self.zones.get(camera_id, []):
                    if zone.contains(pos):
                        in_zones[zone.zone_id] = now
                        events.append(
                            ZoneEventCandidate(
                                event_type="zone_entered",
                                camera_id=camera_id,
                                zone_or_tripwire_id=zone.zone_id,
                                track_id=track_id,
                                timestamp_utc=now,
                                confidence=conf,
                                metadata={"zone_name": zone.name},
                            )
                        )

                cam_states[track_id] = {
                    "last_pos": pos,
                    "first_seen": now,
                    "last_seen": now,
                    "in_zones": in_zones,
                    "loitering_flagged": set(),
                }

        # Clean up stale tracks not seen in this evaluation
        expired = [tid for tid in cam_states if tid not in active_ids]
        for tid in expired:
            del cam_states[tid]

        return events
