"""
camserv.storage.isep.capacity_predictor
=======================================

Storage Capacity Forecasting and Retention Runway Predictor.
Uses empirical bitrate observations to project daily, weekly, and monthly storage
growth, calculate remaining retention days, and forecast disk-full dates.
Provides confidence indicators and separates measured consumption from projections.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from camserv.storage.isep.bitrate_analyzer import StreamBitrateAnalyzer
from camserv.storage.isep.disk_health import DiskHealthMonitor
from camserv.storage.isep.models import CapacityForecast

logger = structlog.get_logger(__name__)


class StorageCapacityPredictor:
    """
    Computes storage growth projections and disk exhaustion forecasts.
    """

    def __init__(
        self,
        bitrate_analyzer: StreamBitrateAnalyzer,
        disk_monitor: DiskHealthMonitor,
        safety_reserve_percent: float = 10.0,
    ) -> None:
        self.bitrate_analyzer = bitrate_analyzer
        self.disk_monitor = disk_monitor
        self.safety_reserve_percent = safety_reserve_percent

    def forecast_camera_consumption(
        self,
        camera_id: str,
        pool_id: str = "default_pool",
    ) -> CapacityForecast:
        """
        Generate consumption forecast for a single camera stream based on observed metrics.
        """
        metrics = self.bitrate_analyzer.get_stream_metrics(camera_id)
        has_data = metrics["has_data"]
        bitrate_kbps = metrics["measured_bitrate_kbps"]
        sample_count = metrics.get("sample_count", 0)

        if not has_data or bitrate_kbps <= 0.0:
            # Conservative baseline estimate when stream has no packets yet (4000 kbps)
            bitrate_kbps = 4000.0
            confidence = 0.2
            is_simulated = True
        else:
            confidence = min(1.0, 0.4 + (sample_count / 100.0) * 0.6)
            is_simulated = False

        # Bytes calculations
        bytes_per_sec = (bitrate_kbps * 1000.0) / 8.0
        daily_bytes = int(bytes_per_sec * 86400.0)
        weekly_bytes = int(daily_bytes * 7)
        monthly_bytes = int(daily_bytes * 30)

        # Query pool available capacity
        cap = self.disk_monitor.probe_volume_capacity(self.disk_monitor.monitored_paths[0])
        usable_free_bytes = max(
            0,
            int(cap["free_bytes"] - (cap["total_bytes"] * (self.safety_reserve_percent / 100.0)))
        )

        if daily_bytes > 0:
            remaining_days = round(usable_free_bytes / daily_bytes, 1)
        else:
            remaining_days = 999.0

        full_date = datetime.now(timezone.utc) + timedelta(days=remaining_days)
        full_date_iso = full_date.isoformat()

        warning_level = "nominal"
        if remaining_days <= 2.0:
            warning_level = "critical_imminent"
        elif remaining_days <= 7.0:
            warning_level = "warning"

        return CapacityForecast(
            pool_id=pool_id,
            camera_id=camera_id,
            measured_bitrate_kbps=round(bitrate_kbps, 1),
            daily_bytes=daily_bytes,
            weekly_bytes=weekly_bytes,
            monthly_bytes=monthly_bytes,
            remaining_retention_days=remaining_days,
            projected_disk_full_date=full_date_iso,
            confidence_score=round(confidence, 2),
            observed_sample_count=sample_count,
            is_simulated_projection=is_simulated,
            warning_level=warning_level,
        )

    def forecast_pool_consumption(
        self,
        camera_ids: list[str],
        pool_id: str = "default_pool",
        pool_path: str | None = None,
    ) -> CapacityForecast:
        """
        Aggregate consumption forecast across all cameras assigned to a storage pool.
        """
        target_path = pool_path or str(self.disk_monitor.monitored_paths[0])
        cap = self.disk_monitor.probe_volume_capacity(target_path)

        total_daily_bytes = 0
        total_bitrate = 0.0
        sample_sum = 0
        camera_forecasts = []

        for cid in camera_ids:
            fc = self.forecast_camera_consumption(cid, pool_id=pool_id)
            camera_forecasts.append(fc)
            total_daily_bytes += fc.daily_bytes
            total_bitrate += fc.measured_bitrate_kbps
            sample_sum += fc.observed_sample_count

        usable_free_bytes = max(
            0,
            int(cap["free_bytes"] - (cap["total_bytes"] * (self.safety_reserve_percent / 100.0)))
        )

        if total_daily_bytes > 0:
            remaining_days = round(usable_free_bytes / total_daily_bytes, 1)
        else:
            remaining_days = 999.0

        full_date = datetime.now(timezone.utc) + timedelta(days=remaining_days)
        full_date_iso = full_date.isoformat()

        confidence = (
            sum(fc.confidence_score for fc in camera_forecasts) / max(1, len(camera_forecasts))
            if camera_forecasts
            else 0.0
        )

        warning_level = "nominal"
        if remaining_days <= 3.0:
            warning_level = "critical_imminent"
        elif remaining_days <= 14.0:
            warning_level = "warning"

        return CapacityForecast(
            pool_id=pool_id,
            camera_id=None,
            measured_bitrate_kbps=round(total_bitrate, 1),
            daily_bytes=total_daily_bytes,
            weekly_bytes=int(total_daily_bytes * 7),
            monthly_bytes=int(total_daily_bytes * 30),
            remaining_retention_days=remaining_days,
            projected_disk_full_date=full_date_iso,
            confidence_score=round(confidence, 2),
            observed_sample_count=sample_sum,
            is_simulated_projection=any(fc.is_simulated_projection for fc in camera_forecasts),
            warning_level=warning_level,
        )
