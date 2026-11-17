"""
camserv.storage.isep.tier_manager
=================================

Storage Tier Manager and Hybrid SSD+HDD Workload Coordinator.
Manages physical storage topologies:
  * HDD-Only (direct sequential writes to spinning disk)
  * SSD+HDD Hybrid (fast SSD staging + verified migration to HDD archive)
  * Enterprise Multi-Disk Pools (capacity-aware volume placement)
  * Network Storage Adapters (disconnection resilience and re-sync)

Rule: A staging transfer is NEVER complete until destination SHA-256 is verified
and recording metadata committed. Never delete source data on a failed transfer.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import time
from pathlib import Path
from typing import Any

import structlog

from camserv.storage.isep.models import (
    RecordingSegmentMetadata,
    SegmentState,
    StoragePool,
    StorageTierType,
    StorageTopology,
)

logger = structlog.get_logger(__name__)


class TransferVerificationError(Exception):
    """Raised when data transfer verification fails or checksum mismatches."""


class StorageTierManager:
    """
    Manages physical storage tiers, pools, and transfer queues.
    Safely coordinates movement of segments from Hot/Staging to Warm/Archive.
    """

    def __init__(
        self,
        primary_storage_dir: Path | str,
        staging_dir: Path | str | None = None,
        topology: StorageTopology = StorageTopology.HDD_ONLY,
    ) -> None:
        self.primary_dir = Path(primary_storage_dir).resolve()
        self.primary_dir.mkdir(parents=True, exist_ok=True)

        self.staging_dir = Path(staging_dir).resolve() if staging_dir else None
        if self.staging_dir:
            self.staging_dir.mkdir(parents=True, exist_ok=True)

        self.topology = topology
        self.pools: dict[str, StoragePool] = {}
        self._init_default_pool()

        # In-flight transfer tracking: segment_id -> transfer_state
        self._active_transfers: dict[str, dict[str, Any]] = {}
        self._failed_transfers: list[dict[str, Any]] = []

    def _init_default_pool(self) -> None:
        """Initialize primary storage pool based on configured topology."""
        default_pool = StoragePool(
            pool_id="default_pool",
            name="Primary Surveillance Storage Pool",
            topology=self.topology,
            primary_path=self.primary_dir,
            staging_path=self.staging_dir,
            archive_paths=[self.primary_dir],
            max_capacity_bytes=0,
            assigned_camera_ids=[],
            quota_safety_reserve_percent=10.0,
        )
        self.pools["default_pool"] = default_pool

    def add_storage_pool(self, pool: StoragePool) -> None:
        """Register an enterprise storage pool with independent volume paths."""
        pool.primary_path.mkdir(parents=True, exist_ok=True)
        if pool.staging_path:
            pool.staging_path.mkdir(parents=True, exist_ok=True)
        self.pools[pool.pool_id] = pool
        logger.info("isep.pool_registered", pool_id=pool.pool_id, topology=pool.topology.value)

    def get_ingest_path_for_camera(self, camera_id: str, pool_id: str = "default_pool") -> Path:
        """
        Determine target directory for an incoming recording segment.
        If SSD staging is configured in hybrid mode, returns staging path;
        otherwise returns primary HDD archive path.
        """
        pool = self.pools.get(pool_id, self.pools["default_pool"])
        if pool.topology == StorageTopology.SSD_HDD_HYBRID and pool.staging_path:
            target = pool.staging_path / camera_id
        else:
            target = pool.primary_path / camera_id
        target.mkdir(parents=True, exist_ok=True)
        return target

    def transfer_staging_to_archive(
        self,
        segment: RecordingSegmentMetadata,
        archive_path: Path | None = None,
    ) -> RecordingSegmentMetadata:
        """
        Migrate a staged segment from SSD buffer to Warm HDD Archive.
        Mandatory Verification Protocol:
          1. Copy file to destination temporary path (.staging_transfer).
          2. Compute complete destination SHA-256 hash.
          3. Compare destination hash against known segment.sha256_hash.
          4. Atomically commit destination file to final archive path.
          5. Update segment metadata (file_path, tier, state).
          6. ONLY THEN unlink staging source file.
          7. If ANY step fails, staging source is strictly PRESERVED.
        """
        source_path = Path(segment.file_path).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Staging source file not found: {source_path}")

        dest_dir = (archive_path or self.primary_dir) / segment.camera_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_final_path = dest_dir / source_path.name
        dest_temp_path = dest_dir / f"{source_path.name}.staging_transfer"

        self._active_transfers[segment.segment_id] = {
            "source": str(source_path),
            "dest": str(dest_final_path),
            "started_at": time.time(),
        }

        try:
            # Step 1: Copy chunks with synchronous flush
            with open(source_path, "rb") as f_src, open(dest_temp_path, "wb") as f_dst:
                while chunk := f_src.read(1024 * 1024):  # 1MB buffer
                    f_dst.write(chunk)
                f_dst.flush()
                os.fsync(f_dst.fileno())

            # Step 2: Compute destination hash
            hasher = hashlib.sha256()
            with open(dest_temp_path, "rb") as f_check:
                while chunk := f_check.read(65536):
                    hasher.update(chunk)
            dest_sha256 = hasher.hexdigest()

            # Step 3: Verify cryptographic equality
            if dest_sha256 != segment.sha256_hash:
                dest_temp_path.unlink(missing_ok=True)
                raise TransferVerificationError(
                    f"Integrity check failed during staging transfer of '{segment.segment_id}'. "
                    f"Expected {segment.sha256_hash}, calculated {dest_sha256}."
                )

            # Step 4: Atomic commit at destination
            dest_temp_path.replace(dest_final_path)

            # Step 5: Update metadata
            updated_meta = RecordingSegmentMetadata(
                schema_version=segment.schema_version,
                segment_id=segment.segment_id,
                recording_id=segment.recording_id,
                camera_id=segment.camera_id,
                segment_index=segment.segment_index,
                start_time_utc=segment.start_time_utc,
                end_time_utc=segment.end_time_utc,
                duration_seconds=segment.duration_seconds,
                file_path=str(dest_final_path),
                file_size_bytes=dest_final_path.stat().st_size,
                sha256_hash=dest_sha256,
                codec=segment.codec,
                resolution=segment.resolution,
                fps=segment.fps,
                bitrate_kbps=segment.bitrate_kbps,
                tier=StorageTierType.WARM_ARCHIVE,
                storage_pool_id=segment.storage_pool_id,
                state=SegmentState.FINALIZED,
                has_motion=segment.has_motion,
                has_event=segment.has_event,
                event_ids=list(segment.event_ids),
                is_protected_evidence=segment.is_protected_evidence,
                preservation_hold_ids=list(segment.preservation_hold_ids),
            )

            # Step 6: Safe release of source staging file
            source_path.unlink()

            del self._active_transfers[segment.segment_id]
            logger.info("isep.staging_transfer_verified", segment_id=segment.segment_id, path=str(dest_final_path))
            return updated_meta

        except Exception as exc:
            dest_temp_path.unlink(missing_ok=True)
            self._failed_transfers.append({
                "segment_id": segment.segment_id,
                "error": str(exc),
                "timestamp": time.time(),
                "source_preserved": source_path.exists(),
            })
            logger.error("isep.staging_transfer_failed_source_preserved", segment_id=segment.segment_id, error=str(exc))
            raise

    def recover_interrupted_transfers(self) -> int:
        """Clean up orphaned '.staging_transfer' files left behind by abrupt crashes."""
        cleaned = 0
        for p in self.primary_dir.rglob("*.staging_transfer"):
            try:
                p.unlink()
                cleaned += 1
            except Exception:
                pass
        return cleaned

    def check_network_storage_health(self, pool_id: str) -> dict[str, Any]:
        """
        Evaluate connectivity and responsiveness of a network storage pool.
        Ensures disconnected network shares are never reported as successful recording destinations.
        """
        pool = self.pools.get(pool_id)
        if not pool or pool.topology != StorageTopology.NETWORK_STORAGE:
            return {"is_network": False, "connected": True, "writable": True}

        is_connected = False
        is_writable = False
        latency_ms = 0.0

        try:
            t0 = time.time()
            if pool.primary_path.exists():
                is_connected = True
                # Write probe token
                probe_file = pool.primary_path / f".probe_{int(time.time()*1000)}"
                probe_file.write_bytes(b"ISEP_NET_PROBE")
                probe_file.unlink()
                is_writable = True
                latency_ms = (time.time() - t0) * 1000.0
        except Exception as exc:
            logger.warning("isep.network_storage_degraded", pool_id=pool_id, error=str(exc))

        return {
            "is_network": True,
            "connected": is_connected,
            "writable": is_writable,
            "latency_ms": round(latency_ms, 2),
        }
