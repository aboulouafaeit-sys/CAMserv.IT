"""
camserv.analytics.crowd
=======================

Crowd density estimation, real-time occupancy counting,
and facility capacity threshold monitoring for CAMserv NVR.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class OccupancyReport:
    """Snapshot of active occupancy and density for a camera or zone."""

    camera_id: str
    zone_id: str
    timestamp_utc: float
    total_persons: int
    total_vehicles: int
    density_per_sq_m: float
    capacity_limit: int
    is_overcrowded: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CrowdDensityEstimator:
    """
    Estimates pedestrian occupancy and crowd density across monitored areas.
    """

    def __init__(self, zone_area_sq_m: float = 50.0, max_capacity: int = 20) -> None:
        self.zone_area_sq_m = zone_area_sq_m if zone_area_sq_m > 0 else 50.0
        self.max_capacity = max_capacity

    def estimate_occupancy(
        self,
        camera_id: str,
        tracks: list[dict[str, Any]],
        zone_id: str = "default_view",
        timestamp_utc: float | None = None,
    ) -> OccupancyReport:
        """
        Count active tracks and calculate density.
        """
        now = timestamp_utc or time.time()
        persons = 0
        vehicles = 0

        for trk in tracks:
            cls_name = trk.get("class_name", "person").lower()
            if cls_name == "person":
                persons += 1
            elif cls_name in ("car", "truck", "bus", "vehicle", "motorcycle"):
                vehicles += 1

        density = persons / self.zone_area_sq_m
        is_overcrowded = persons > self.max_capacity

        report = OccupancyReport(
            camera_id=camera_id,
            zone_id=zone_id,
            timestamp_utc=now,
            total_persons=persons,
            total_vehicles=vehicles,
            density_per_sq_m=round(density, 3),
            capacity_limit=self.max_capacity,
            is_overcrowded=is_overcrowded,
        )

        if is_overcrowded:
            logger.warning(
                "analytics.crowd.overcrowded",
                camera_id=camera_id,
                zone_id=zone_id,
                persons=persons,
                capacity=self.max_capacity,
            )

        return report
