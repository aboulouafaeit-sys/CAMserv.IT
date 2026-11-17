"""
camserv.storage.isep.telemetry_service
======================================

Storage Telemetry & Real-Time Operational Metrics Service for CAMserv ISEP.
Collects and aggregates live storage statistics, pool capacities,
stream bitrates, staging queues, Evidence Vault consumption, and disk health metrics.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from camserv.storage.isep.capacity_predictor import StorageCapacityPredictor
from camserv.storage.isep.disk_health import DiskHealthMonitor
from camserv.storage.isep.evidence_preservation import EvidencePreservationManager
from camserv.storage.isep.models import StorageProfile
from camserv.storage.isep.segment_manager import RecordingSegmentManager
from camserv.storage.isep.tier_manager import StorageTierManager

logger = structlog.get_logger(__name__)


class StorageTelemetryService:
    """
    Exposes unified operational telemetry for CAMserv consoles and REST APIs.
    """

    def __init__(
        self,
        disk_monitor: DiskHealthMonitor,
        tier_manager: StorageTierManager,
        segment_manager: RecordingSegmentManager,
        evidence_manager: EvidencePreservationManager,
        capacity_predictor: StorageCapacityPredictor,
        current_profile: StorageProfile = StorageProfile.BALANCED,
    ) -> None:
        self.disk_monitor = disk_monitor
        self.tier_manager = tier_manager
        self.segment_manager = segment_manager
        self.evidence_manager = evidence_manager
        self.capacity_predictor = capacity_predictor
        self.current_profile = current_profile

    def get_storage_dashboard_telemetry(self) -> dict[str, Any]:
        """
        Aggregate complete real-time telemetry payload for the Storage Dashboard.
        """
        # Primary volume health
        health = self.disk_monitor.inspect_disk_health(self.disk_monitor.monitored_paths[0])

        # Active recording streams
        active_cams = list(self.segment_manager.active_writers.keys())

        # Staging transfer metrics
        in_flight_transfers = len(self.tier_manager._active_transfers)

        # Evidence Vault usage
        vault_count = len(self.evidence_manager.vault_segments)
        vault_bytes = sum(s.file_size_bytes for s in self.evidence_manager.vault_segments.values())

        # Pool forecasting
        forecast = self.capacity_predictor.forecast_pool_consumption(
            active_cams,
            pool_id="default_pool",
        )

        return {
            "timestamp_epoch": time.time(),
            "profile": self.current_profile.value,
            "topology": self.tier_manager.topology.value,
            "disk": {
                "mount_point": health.mount_point,
                "disk_type": health.disk_type,
                "total_gb": health.total_gb,
                "free_gb": health.free_gb,
                "used_percent": health.used_percent,
                "write_latency_ms": health.write_latency_ms,
                "temperature_c": health.temperature_c,
                "is_healthy": health.is_healthy,
                "warnings": health.warnings,
            },
            "streams": {
                "active_recording_count": len(active_cams),
                "active_camera_ids": active_cams,
                "aggregate_bitrate_kbps": forecast.measured_bitrate_kbps,
            },
            "staging": {
                "has_staging": self.tier_manager.staging_dir is not None,
                "in_flight_transfers": in_flight_transfers,
            },
            "evidence_vault": {
                "preserved_segments_count": vault_count,
                "total_vault_mb": round(vault_bytes / (1024 * 1024), 2),
                "active_holds_count": sum(1 for h in self.evidence_manager.holds.values() if h.active),
            },
            "forecast": {
                "daily_gb": round(forecast.daily_bytes / (1024 ** 3), 2),
                "monthly_gb": round(forecast.monthly_bytes / (1024 ** 3), 2),
                "remaining_retention_days": forecast.remaining_retention_days,
                "projected_disk_full_date": forecast.projected_disk_full_date,
                "warning_level": forecast.warning_level,
                "confidence_score": forecast.confidence_score,
            },
        }
