"""
camserv.storage.isep.models
===========================

Domain models, schemas, and enumerations for the CAMserv Intelligent Storage
and Evidence Preservation Engine (ISEP).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class StorageTopology(str, enum.Enum):
    """Storage hardware arrangement topology."""

    HDD_ONLY = "hdd_only"                  # Direct sequential recording to spinning disk
    SSD_HDD_HYBRID = "ssd_hdd_hybrid"      # Fast SSD staging buffer + sequential HDD archive
    MULTI_DISK_POOL = "multi_disk_pool"    # Multi-volume pool with camera-to-disk allocation
    NETWORK_STORAGE = "network_storage"    # Remote NAS / SAN / Network share adapter


class StorageTierType(str, enum.Enum):
    """Logical and physical storage tier."""

    HOT_INGEST = "hot_ingest"              # RAM pre-roll or active SSD write staging
    WARM_ARCHIVE = "warm_archive"          # Long-term continuous HDD sequential storage
    EVIDENCE_VAULT = "evidence_vault"      # Cryptographically sealed immutable incident storage
    COLD_EXPORT = "cold_export"            # External detached court-admissible archive


class RecordingCodec(str, enum.Enum):
    """Supported video codecs for camera recording."""

    H264 = "h264"
    H265 = "h265"
    MJPEG = "mjpeg"
    SMART_CODEC_H264 = "smart_h264"
    SMART_CODEC_H265 = "smart_h265"
    NATIVE_PASS_THROUGH = "native_pass_through"


class SceneComplexity(str, enum.Enum):
    """Visual motion and scene complexity classification for bitrate optimization."""

    STABLE = "stable"                      # Negligible motion, static background
    LOW_MOTION = "low_motion"              # Occasional slow movement (e.g., indoor corridor)
    MODERATE = "moderate"                  # Standard activity (e.g., staff office entry)
    HIGH_MOTION = "high_motion"            # Rapid activity (e.g., vehicular roadway)
    COMPLEX = "complex"                    # Dynamic foliage, rain, or high detail variance
    NOISY_LOW_LIGHT = "noisy_low_light"    # Low light / sensor noise requiring denoising


class StorageProfile(str, enum.Enum):
    """Capability-aware storage and retention management profile."""

    ECONOMY = "economy"                    # Aggressive bitrate optimization, sub-stream retention
    BALANCED = "balanced"                  # Continuous standard stream + incident high-res
    PERFORMANCE = "performance"            # Unconstrained full-resolution continuous recording
    EVIDENCE_PRIORITY = "evidence_priority"# Zero-transcode camera-native + prolonged forensic holds
    OPERATOR_CONFIGURED = "custom"         # User-customized rules


class SegmentState(str, enum.Enum):
    """Lifecycle state of an individual recording segment."""

    RECORDING = "recording"                # Actively being written
    STAGED = "staged"                      # Completed on SSD staging buffer, awaiting transfer
    TRANSFERRING = "transferring"          # Transfer in-flight to warm archive
    FINALIZED = "finalized"                # Safely committed and verified on primary archive
    VAULT_SEALED = "vault_sealed"          # Protected under evidence vault with WORM hold
    QUARANTINED = "quarantined"            # Fenced or aborted write isolated for inspection
    CORRUPTED = "corrupted"                # Failed cryptographic integrity check
    PURGED = "purged"                      # Safely deleted per authorized retention policy
    RECOVERED_PARTIAL = "recovered_partial"# Recovered unfinalized fragment post-crash (NEVER finalized)


class TelemetrySource(str, enum.Enum):
    """Authoritative source for hardware and storage telemetry."""

    PHYSICAL_OS = "physical_os"
    OS_FSYNC_PROBE = "os_fsync_probe"
    OS_SHUTIL_DISK_USAGE = "os_shutil_disk_usage"
    WMI_MSFT_PHYSICALDISK = "wmi_msft_physicaldisk"
    LINUX_SYSFS = "linux_sysfs"
    SMARTCTL = "smartctl"
    UNAVAILABLE = "unavailable"


class HardwareAvailabilityState(str, enum.Enum):
    """Operational availability state of a hardware sensor or subsystem."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class HardwareTelemetryMetric:
    """Attributed hardware telemetry field declaring genuine source and availability."""

    metric_name: str
    value: Any
    source: TelemetrySource
    timestamp_utc: str
    availability: HardwareAvailabilityState
    confidence: float = 1.0
    details: str = ""


@dataclass(slots=True)
class RecordingSegmentMetadata:
    """Documented, versioned metadata schema for an individual video recording segment."""

    schema_version: str
    segment_id: str
    recording_id: str
    camera_id: str
    segment_index: int
    start_time_utc: str
    end_time_utc: str
    duration_seconds: float
    file_path: str
    file_size_bytes: int
    sha256_hash: str
    codec: str
    resolution: tuple[int, int]
    fps: float
    bitrate_kbps: float
    tier: StorageTierType
    storage_pool_id: str = "default_pool"
    state: SegmentState = SegmentState.FINALIZED
    has_motion: bool = False
    has_event: bool = False
    event_ids: list[str] = field(default_factory=list)
    is_protected_evidence: bool = False
    preservation_hold_ids: list[str] = field(default_factory=list)
    is_partial: bool = False
    recovery_notes: str | None = None
    keyframe_count: int = 0
    has_keyframes: bool = False
    source_part_path: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize segment metadata to structured dictionary."""
        return {
            "schema_version": self.schema_version,
            "segment_id": self.segment_id,
            "recording_id": self.recording_id,
            "camera_id": self.camera_id,
            "segment_index": self.segment_index,
            "start_time_utc": self.start_time_utc,
            "end_time_utc": self.end_time_utc,
            "duration_seconds": round(self.duration_seconds, 3),
            "file_path": self.file_path,
            "file_size_bytes": self.file_size_bytes,
            "sha256_hash": self.sha256_hash,
            "codec": self.codec,
            "resolution": list(self.resolution),
            "fps": round(self.fps, 2),
            "bitrate_kbps": round(self.bitrate_kbps, 1),
            "tier": self.tier.value,
            "storage_pool_id": self.storage_pool_id,
            "state": self.state.value,
            "has_motion": self.has_motion,
            "has_event": self.has_event,
            "event_ids": list(self.event_ids),
            "is_protected_evidence": self.is_protected_evidence,
            "preservation_hold_ids": list(self.preservation_hold_ids),
            "is_partial": self.is_partial,
            "recovery_notes": self.recovery_notes,
            "keyframe_count": self.keyframe_count,
            "has_keyframes": self.has_keyframes,
            "source_part_path": self.source_part_path,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecordingSegmentMetadata:
        """Deserialize structured dictionary into RecordingSegmentMetadata."""
        res_raw = data.get("resolution", [1920, 1080])
        res = (int(res_raw[0]), int(res_raw[1])) if len(res_raw) >= 2 else (1920, 1080)
        return cls(
            schema_version=str(data.get("schema_version", "1.0")),
            segment_id=str(data["segment_id"]),
            recording_id=str(data["recording_id"]),
            camera_id=str(data["camera_id"]),
            segment_index=int(data.get("segment_index", 0)),
            start_time_utc=str(data["start_time_utc"]),
            end_time_utc=str(data["end_time_utc"]),
            duration_seconds=float(data.get("duration_seconds", 0.0)),
            file_path=str(data["file_path"]),
            file_size_bytes=int(data.get("file_size_bytes", 0)),
            sha256_hash=str(data["sha256_hash"]),
            codec=str(data.get("codec", "h264")),
            resolution=res,
            fps=float(data.get("fps", 15.0)),
            bitrate_kbps=float(data.get("bitrate_kbps", 0.0)),
            tier=StorageTierType(data.get("tier", StorageTierType.WARM_ARCHIVE.value)),
            storage_pool_id=str(data.get("storage_pool_id", "default_pool")),
            state=SegmentState(data.get("state", SegmentState.FINALIZED.value)),
            has_motion=bool(data.get("has_motion", False)),
            has_event=bool(data.get("has_event", False)),
            event_ids=list(data.get("event_ids", [])),
            is_protected_evidence=bool(data.get("is_protected_evidence", False)),
            preservation_hold_ids=list(data.get("preservation_hold_ids", [])),
            is_partial=bool(data.get("is_partial", False)),
            recovery_notes=data.get("recovery_notes"),
            keyframe_count=int(data.get("keyframe_count", 0)),
            has_keyframes=bool(data.get("has_keyframes", False)),
            source_part_path=data.get("source_part_path"),
            created_at=str(data.get("created_at", datetime.now(timezone.utc).isoformat())),
        )


@dataclass(slots=True)
class DiskHealthInfo:
    """Hardware telemetry and diagnostic telemetry for a physical or logical storage disk."""

    device_path: str
    mount_point: str
    disk_type: str                        # "HDD_CMR", "HDD_SMR", "SSD_SATA", "SSD_NVME", "NETWORK_SHARE", "UNKNOWN"
    total_bytes: int
    free_bytes: int
    used_bytes: int
    temperature_c: float | None = None
    power_on_hours: int | None = None
    reallocated_sectors: int | None = None
    pending_sectors: int | None = None
    uncorrectable_errors: int | None = None
    write_amplification_factor: float | None = None
    endurance_remaining_percent: float | None = None
    io_queue_depth: int = 0
    write_latency_ms: float = 0.0
    is_healthy: bool = True
    warnings: list[str] = field(default_factory=list)
    metric_sources: dict[str, str] = field(default_factory=dict)
    metric_availabilities: dict[str, str] = field(default_factory=dict)

    @property
    def used_percent(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return round((self.used_bytes / self.total_bytes) * 100.0, 2)

    @property
    def free_gb(self) -> float:
        return round(self.free_bytes / (1024 ** 3), 2)

    @property
    def total_gb(self) -> float:
        return round(self.total_bytes / (1024 ** 3), 2)


@dataclass(slots=True)
class CapacityForecast:
    """Forecasting report for storage consumption and remaining retention duration."""

    pool_id: str
    camera_id: str | None                 # None for entire pool
    measured_bitrate_kbps: float
    daily_bytes: int
    weekly_bytes: int
    monthly_bytes: int
    remaining_retention_days: float
    projected_disk_full_date: str
    confidence_score: float               # 0.0 to 1.0 based on observation sample size
    observed_sample_count: int
    is_simulated_projection: bool = False
    warning_level: str = "nominal"        # "nominal", "warning", "critical_imminent"


@dataclass(slots=True)
class StoragePool:
    """Logical grouping of storage capacity assigned to specific cameras."""

    pool_id: str
    name: str
    topology: StorageTopology
    primary_path: Path
    staging_path: Path | None = None      # Optional SSD staging path
    archive_paths: list[Path] = field(default_factory=list)
    max_capacity_bytes: int = 0
    assigned_camera_ids: list[str] = field(default_factory=list)
    quota_safety_reserve_percent: float = 10.0


@dataclass(slots=True)
class PreservationHold:
    """Legal, administrative, or incident preservation hold locking recordings from purge."""

    hold_id: str
    target_id: str                        # segment_id, recording_id, or event_id
    target_type: str                      # "segment", "recording", "event"
    reason: str
    authorized_by: str
    hold_type: str = "incident"           # "incident", "legal_hold", "administrative"
    active: bool = True
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    expires_at: str | None = None         # None = indefinite until manually released

    def to_dict(self) -> dict[str, Any]:
        """Serialize preservation hold to structured dictionary."""
        return {
            "hold_id": self.hold_id,
            "target_id": self.target_id,
            "target_type": self.target_type,
            "reason": self.reason,
            "authorized_by": self.authorized_by,
            "hold_type": self.hold_type,
            "active": self.active,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PreservationHold:
        """Deserialize structured dictionary into PreservationHold."""
        return cls(
            hold_id=str(data["hold_id"]),
            target_id=str(data["target_id"]),
            target_type=str(data.get("target_type", "segment")),
            reason=str(data.get("reason", "")),
            authorized_by=str(data.get("authorized_by", "")),
            hold_type=str(data.get("hold_type", "incident")),
            active=bool(data.get("active", True)),
            created_at=str(data.get("created_at", datetime.now(timezone.utc).isoformat())),
            expires_at=data.get("expires_at"),
        )
