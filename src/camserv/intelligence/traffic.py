"""
camserv.intelligence.traffic
============================

Traffic Intelligence, Flow Analytics & Calibration-Aware Velocity Engine.

Features:
- Directional virtual counting lines (forward / reverse counts).
- Region-based traffic density, queue length, and congestion estimation.
- Stationary vehicle and wrong-way travel trajectory detection.
- STRICT CALIBRATION TRUTHFULNESS:
  Speed in km/h is NEVER estimated on uncalibrated streams. Uncalibrated
  streams report relative pixel velocity only. Calibrated streams report
  km/h with documented margin of error.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Sequence

from camserv.intelligence.contracts import (
    CameraCalibration,
    EngineHealthStatus,
    SpeedMeasurementStatus,
    TrackRecord,
    TrafficCongestionLevel,
    TrafficCountingLine,
    TrafficFlowMeasurement,
    TrafficZone,
)


def _segments_cross(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    p4: tuple[float, float],
) -> bool:
    """Ray-intersection check for 2D line segments."""
    def _ccw(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> bool:
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])

    return (
        _ccw(p1, p3, p4) != _ccw(p2, p3, p4)
        and _ccw(p1, p2, p3) != _ccw(p1, p2, p4)
    )


class TrafficAnalyticsEngine:
    """
    Evaluates vehicle tracks against counting lines, travel corridors,
    and density zones with camera calibration awareness.
    """

    def __init__(
        self,
        camera_id: str,
        calibration: CameraCalibration | None = None,
        congestion_density_threshold: float = 0.65,
    ) -> None:
        self.camera_id = camera_id
        self.calibration = calibration or CameraCalibration(camera_id=camera_id)
        self._congestion_threshold = congestion_density_threshold

        self._lock = threading.RLock()
        self._counting_lines: dict[str, TrafficCountingLine] = {}
        self._zones: dict[str, TrafficZone] = {}
        self._track_history: dict[int, tuple[float, float]] = {}  # track_id -> last_pos
        self._crossed_tracks: dict[str, set[int]] = {}            # line_id -> set of track_ids
        self._wrong_direction_events: int = 0
        self._nominal_travel_vector: tuple[float, float] = (1.0, 0.0)  # Default rightward flow
        self._health_status = EngineHealthStatus.ACTIVE

    @property
    def health_status(self) -> EngineHealthStatus:
        with self._lock:
            return self._health_status

    def set_calibration(self, calibration: CameraCalibration) -> None:
        """Update geometric camera calibration."""
        with self._lock:
            self.calibration = calibration

    def set_nominal_flow_direction(self, vector: tuple[float, float]) -> None:
        """Define the expected lane travel direction (dx, dy)."""
        with self._lock:
            norm = (vector[0] ** 2 + vector[1] ** 2) ** 0.5
            if norm > 0:
                self._nominal_travel_vector = (vector[0] / norm, vector[1] / norm)

    def add_counting_line(self, line: TrafficCountingLine) -> None:
        """Register a directional virtual counting line."""
        with self._lock:
            self._counting_lines[line.line_id] = line
            self._crossed_tracks[line.line_id] = set()

    def add_zone(self, zone: TrafficZone) -> None:
        """Register a traffic monitoring zone."""
        with self._lock:
            self._zones[zone.zone_id] = zone

    def process_tracks(
        self,
        tracks: list[TrackRecord],
        timestamp_utc: float | None = None,
    ) -> TrafficFlowMeasurement:
        """
        Analyze traffic tracks, update counts, detect queues, and return measurement.
        """
        now = timestamp_utc or time.time()

        with self._lock:
            vehicles = [t for t in tracks if t.class_name in ("car", "truck", "van", "bus", "motorcycle")]
            pedestrians = [t for t in tracks if t.class_name in ("person", "pedestrian")]

            stationary_count = 0
            wrong_way_count = 0
            pixel_velocities: list[float] = []

            for trk in vehicles:
                vx, vy = trk.velocity_pixels_per_sec
                speed_px = (vx ** 2 + vy ** 2) ** 0.5
                pixel_velocities.append(speed_px)

                # Check stationary vehicle
                if speed_px < 5.0 and trk.age_frames > 20:
                    stationary_count += 1

                # Check wrong-way travel direction
                if speed_px > 10.0:
                    dot = (vx * self._nominal_travel_vector[0] + vy * self._nominal_travel_vector[1]) / speed_px
                    # Antiparallel movement (dot < -0.70 means opposing travel flow)
                    if dot < -0.70:
                        wrong_way_count += 1
                        self._wrong_direction_events += 1

                # Evaluate line crossings
                prev_pos = self._track_history.get(trk.track_id)
                curr_pos = trk.bbox.center

                if prev_pos is not None:
                    for line_id, line in self._counting_lines.items():
                        if not line.is_active or trk.track_id in self._crossed_tracks[line_id]:
                            continue

                        if _segments_cross(prev_pos, curr_pos, line.start_pt, line.end_pt):
                            self._crossed_tracks[line_id].add(trk.track_id)
                            # Determine crossing direction relative to line normal
                            lx = line.end_pt[0] - line.start_pt[0]
                            ly = line.end_pt[1] - line.start_pt[1]
                            dx = curr_pos[0] - prev_pos[0]
                            dy = curr_pos[1] - prev_pos[1]
                            normal_dot = dx * ly - dy * lx

                            if normal_dot >= 0:
                                line.forward_count += 1
                            else:
                                line.reverse_count += 1

                self._track_history[trk.track_id] = curr_pos

            # Prune obsolete track history
            active_ids = {t.track_id for t in tracks}
            stale_ids = [tid for tid in self._track_history if tid not in active_ids]
            for tid in stale_ids:
                self._track_history.pop(tid, None)
                for line_id in self._crossed_tracks:
                    self._crossed_tracks[line_id].discard(tid)

            # Compute traffic density (normalized 0.0 to 1.0)
            lane_capacity = max(1, len(self._zones) * 10 or 15)
            density = min(1.0, len(vehicles) / float(lane_capacity))

            # Determine congestion level
            if density >= 0.85 or (stationary_count >= 3 and density >= 0.60):
                congestion = TrafficCongestionLevel.STANDSTILL
            elif density >= self._congestion_threshold or stationary_count >= 2:
                congestion = TrafficCongestionLevel.CONGESTED
            elif density >= 0.35:
                congestion = TrafficCongestionLevel.MODERATE
            else:
                congestion = TrafficCongestionLevel.FREE_FLOW

            # Velocity & Speed Calculation
            avg_px_sec = float(sum(pixel_velocities) / len(pixel_velocities)) if pixel_velocities else 0.0

            calibrated_kmh: float | None = None
            queue_length_m: float = 0.0
            speed_status = SpeedMeasurementStatus.RELATIVE_MOVEMENT_ONLY

            if self.calibration.is_calibrated and self.calibration.pixels_per_meter > 0:
                ppm = self.calibration.pixels_per_meter
                speed_m_s = avg_px_sec / ppm
                calibrated_kmh = round(speed_m_s * 3.6, 2)
                queue_length_m = round(stationary_count * (5.0 / ppm * 10.0), 1)  # Est. 5m per vehicle
                speed_status = SpeedMeasurementStatus.CALIBRATED_ACCURATE
            elif not pixel_velocities:
                speed_status = SpeedMeasurementStatus.SPEED_UNAVAILABLE
            else:
                speed_status = SpeedMeasurementStatus.RELATIVE_MOVEMENT_ONLY

            return TrafficFlowMeasurement(
                camera_id=self.camera_id,
                timestamp_utc=now,
                observed_vehicle_count=len(vehicles),
                observed_pedestrian_count=len(pedestrians),
                estimated_density=round(density, 3),
                congestion_level=congestion,
                queue_length_meters=queue_length_m,
                stationary_vehicle_count=stationary_count,
                wrong_direction_count=wrong_way_count,
                is_calibrated=self.calibration.is_calibrated,
                calibrated_speed_kmh=calibrated_kmh,
                relative_velocity_pixels_sec=round(avg_px_sec, 2),
                speed_status=speed_status,
                metadata={
                    "counting_lines": {
                        lid: {"forward": l.forward_count, "reverse": l.reverse_count}
                        for lid, l in self._counting_lines.items()
                    },
                    "calibration_error_margin": self.calibration.error_margin_percent if self.calibration.is_calibrated else None,
                },
            )
