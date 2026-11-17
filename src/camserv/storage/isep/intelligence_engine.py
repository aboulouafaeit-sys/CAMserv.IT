"""
camserv.storage.isep.intelligence_engine
========================================

Storage Intelligence Engine — Central Coordinator for CAMserv ISEP.
Unifies stream bitrate analysis, adaptive segmented recording,
hybrid SSD+HDD staging, cryptographic evidence preservation,
policy-based retention, disk workload optimization, and health telemetry.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
import structlog

from camserv.storage.isep.bitrate_analyzer import StreamBitrateAnalyzer
from camserv.storage.isep.capacity_predictor import StorageCapacityPredictor
from camserv.storage.isep.disk_health import DiskHealthMonitor
from camserv.storage.isep.evidence_preservation import EvidencePreservationManager
from camserv.storage.isep.integrity_verifier import StorageIntegrityVerifier
from camserv.storage.isep.models import (
    RecordingCodec,
    RecordingSegmentMetadata,
    SceneComplexity,
    StorageProfile,
    StorageTierType,
    StorageTopology,
)
from camserv.storage.isep.recovery_manager import StorageRecoveryManager
from camserv.storage.isep.retention_engine import RetentionPolicyEngine
from camserv.storage.isep.segment_manager import RecordingSegmentManager
from camserv.storage.isep.telemetry_service import StorageTelemetryService
from camserv.storage.isep.tier_manager import StorageTierManager

logger = structlog.get_logger(__name__)


class StorageIntelligenceEngine:
    """
    Unified Intelligent Storage & Evidence Preservation Engine (ISEP).
    Coordinates the entire surveillance recording lifecycle:
    Acquire -> Analyze -> Record -> Optimize -> Verify -> Archive -> Preserve -> Retrieve.
    """

    PROFILE_CONFIGURATIONS: dict[StorageProfile, dict[str, Any]] = {
        StorageProfile.ECONOMY: {
            "segment_duration_seconds": 120.0,
            "max_segment_size_bytes": 300 * 1024 * 1024,
            "prefer_substream_when_stable": True,
            "enable_transcoding": False,
            "continuous_retention_hours": 24.0,
            "incident_retention_days": 90.0,
        },
        StorageProfile.BALANCED: {
            "segment_duration_seconds": 60.0,
            "max_segment_size_bytes": 500 * 1024 * 1024,
            "prefer_substream_when_stable": False,
            "enable_transcoding": False,
            "continuous_retention_hours": 48.0,
            "incident_retention_days": 365.0,
        },
        StorageProfile.PERFORMANCE: {
            "segment_duration_seconds": 60.0,
            "max_segment_size_bytes": 1024 * 1024 * 1024,
            "prefer_substream_when_stable": False,
            "enable_transcoding": False,
            "continuous_retention_hours": 168.0,  # 7 days
            "incident_retention_days": 730.0,  # 2 years
        },
        StorageProfile.EVIDENCE_PRIORITY: {
            "segment_duration_seconds": 30.0,
            "max_segment_size_bytes": 500 * 1024 * 1024,
            "prefer_substream_when_stable": False,
            "enable_transcoding": False,
            "continuous_retention_hours": 336.0,  # 14 days
            "incident_retention_days": 1825.0,  # 5 years
        },
    }

    def __init__(
        self,
        primary_storage_dir: Path | str = "data/storage/archive",
        staging_dir: Path | str | None = None,
        vault_dir: Path | str = "data/storage/vault",
        topology: StorageTopology = StorageTopology.HDD_ONLY,
        profile: StorageProfile = StorageProfile.BALANCED,
    ) -> None:
        self.primary_dir = Path(primary_storage_dir).resolve()
        self.staging_dir = Path(staging_dir).resolve() if staging_dir else None
        self.vault_dir = Path(vault_dir).resolve()
        self.topology = topology
        self.current_profile = profile

        # Initialize modular subsystems
        self.bitrate_analyzer = StreamBitrateAnalyzer(window_seconds=30.0)
        self.disk_monitor = DiskHealthMonitor(monitored_paths=[self.primary_dir])
        self.tier_manager = StorageTierManager(
            primary_storage_dir=self.primary_dir,
            staging_dir=self.staging_dir,
            topology=self.topology,
        )

        cfg = self.PROFILE_CONFIGURATIONS.get(self.current_profile, self.PROFILE_CONFIGURATIONS[StorageProfile.BALANCED])
        self.segment_manager = RecordingSegmentManager(
            base_storage_dir=self.tier_manager.get_ingest_path_for_camera("default"),
            segment_duration_seconds=cfg["segment_duration_seconds"],
            max_segment_size_bytes=cfg["max_segment_size_bytes"],
            tier=StorageTierType.HOT_INGEST if self.topology == StorageTopology.SSD_HDD_HYBRID else StorageTierType.WARM_ARCHIVE,
        )

        self.evidence_manager = EvidencePreservationManager(vault_dir=self.vault_dir)
        self.retention_engine = RetentionPolicyEngine(evidence_manager=self.evidence_manager)
        self.capacity_predictor = StorageCapacityPredictor(
            bitrate_analyzer=self.bitrate_analyzer,
            disk_monitor=self.disk_monitor,
        )
        self.verifier = StorageIntegrityVerifier()
        self.recovery_manager = StorageRecoveryManager(
            segment_manager=self.segment_manager,
            tier_manager=self.tier_manager,
            verifier=self.verifier,
        )
        self.telemetry_service = StorageTelemetryService(
            disk_monitor=self.disk_monitor,
            tier_manager=self.tier_manager,
            segment_manager=self.segment_manager,
            evidence_manager=self.evidence_manager,
            capacity_predictor=self.capacity_predictor,
            current_profile=self.current_profile,
        )

        self.indexed_segments: dict[str, RecordingSegmentMetadata] = {}

    def switch_profile(self, new_profile: StorageProfile) -> None:
        """Activate a different capability-aware storage performance profile."""
        self.current_profile = new_profile
        self.telemetry_service.current_profile = new_profile
        cfg = self.PROFILE_CONFIGURATIONS.get(new_profile, self.PROFILE_CONFIGURATIONS[StorageProfile.BALANCED])
        self.segment_manager.segment_duration_seconds = cfg["segment_duration_seconds"]
        self.segment_manager.max_segment_size_bytes = cfg["max_segment_size_bytes"]
        logger.info("isep.storage_profile_switched", profile=new_profile.value)

    def start_camera_recording(
        self,
        camera_id: str,
        codec: RecordingCodec = RecordingCodec.H264,
        fps: float = 15.0,
        resolution: tuple[int, int] = (1920, 1080),
    ) -> str:
        """Initialize or start recording for a camera channel."""
        rec_id = f"rec_{camera_id}_{int(time.time())}"
        target_dir = self.tier_manager.get_ingest_path_for_camera(camera_id)
        self.segment_manager.base_storage_dir = target_dir.parent

        writer = self.segment_manager.start_segment(
            recording_id=rec_id,
            camera_id=camera_id,
            codec=codec,
            fps=fps,
            resolution=resolution,
        )
        return writer.segment_id

    def ingest_packet(
        self,
        camera_id: str,
        packet_bytes: bytes,
        is_keyframe: bool = False,
    ) -> None:
        """Ingest raw camera-native encoded packet without decoding or transcoding."""
        self.bitrate_analyzer.record_packet(camera_id, len(packet_bytes))

        # Check if roll over needed
        if self.segment_manager.should_roll_over(camera_id):
            meta = self.segment_manager.finalize_segment(camera_id)
            if meta:
                self._handle_finalized_segment(meta)
            self.start_camera_recording(camera_id)

        writer = self.segment_manager.active_writers.get(camera_id)
        if writer:
            writer.write_raw_packet(packet_bytes, is_keyframe=is_keyframe)

    def ingest_frame(
        self,
        camera_id: str,
        frame: np.ndarray,
        motion_detected: bool = False,
        event_id: str | None = None,
    ) -> None:
        """Ingest uncompressed frame, analyze scene complexity, and record."""
        complexity = self.bitrate_analyzer.record_frame_for_scene_analysis(camera_id, frame)
        self.bitrate_analyzer.record_packet(camera_id, frame.nbytes // 10)  # Approximate compressed equivalent

        # Check roll over
        if self.segment_manager.should_roll_over(camera_id):
            meta = self.segment_manager.finalize_segment(camera_id)
            if meta:
                self._handle_finalized_segment(meta)
            self.start_camera_recording(camera_id)

        writer = self.segment_manager.active_writers.get(camera_id)
        if writer:
            writer.write_numpy_frame(frame, motion_detected=motion_detected, event_id=event_id)

    def _handle_finalized_segment(self, segment: RecordingSegmentMetadata) -> RecordingSegmentMetadata:
        """Handle finalized segment: migrate from staging to warm archive if hybrid topology."""
        self.indexed_segments[segment.segment_id] = segment

        if self.topology == StorageTopology.SSD_HDD_HYBRID and self.staging_dir:
            try:
                migrated = self.tier_manager.transfer_staging_to_archive(segment, archive_path=self.primary_dir)
                self.indexed_segments[migrated.segment_id] = migrated
                return migrated
            except Exception as exc:
                logger.error("isep.staging_migration_error", segment_id=segment.segment_id, error=str(exc))

        return segment

    def promote_to_evidence_vault(
        self,
        segment_id: str,
        reason: str,
        authorized_by: str,
    ) -> RecordingSegmentMetadata:
        """Promote an archived segment into the protected Evidence Vault with an active hold."""
        segment = self.indexed_segments.get(segment_id)
        if not segment:
            raise FileNotFoundError(f"Segment '{segment_id}' not found in ISEP index.")

        vault_meta = self.evidence_manager.ingest_to_vault(
            segment=segment,
            hold_reason=reason,
            authorized_by=authorized_by,
        )
        self.indexed_segments[vault_meta.segment_id] = vault_meta
        return vault_meta

    def run_retention_cycle(self, operator_authorization: str = "SCHEDULED_POLICY_RUN") -> dict[str, Any]:
        """Execute scheduled 6-step retention cleanup against active indexed segments."""
        all_segs = list(self.indexed_segments.values())
        result = self.retention_engine.execute_safe_cleanup(
            segments=all_segs,
            operator_authorization=operator_authorization,
        )
        # Update index
        for purged_id in result["purged_segment_ids"]:
            if purged_id in self.indexed_segments:
                self.indexed_segments[purged_id].state = "purged"
        return result

    def get_telemetry(self) -> dict[str, Any]:
        """Retrieve unified real-time storage telemetry."""
        return self.telemetry_service.get_storage_dashboard_telemetry()
