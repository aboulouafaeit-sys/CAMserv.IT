"""
camserv.storage.isep.segment_manager
====================================

Segmented Recording Engine for CAMserv ISEP.
Manages sequential, atomic video segment creation, native-stream writing,
continuous SHA-256 hash computation, continuity gap tracking, and crash recovery.
Avoids forced transcoding; preserves raw camera-native stream bytes whenever available.
"""

from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import structlog

from camserv.storage.isep.models import (
    RecordingCodec,
    RecordingSegmentMetadata,
    SegmentState,
    StorageTierType,
)

logger = structlog.get_logger(__name__)

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False


class RecordingSegmentWriter:
    """
    Manages active file writing for an individual video segment.
    Writes to temporary '.part' path and commits atomically upon closure.
    """

    def __init__(
        self,
        segment_id: str,
        recording_id: str,
        camera_id: str,
        segment_index: int,
        target_dir: Path,
        codec: RecordingCodec = RecordingCodec.H264,
        fps: float = 15.0,
        resolution: tuple[int, int] = (1920, 1080),
        tier: StorageTierType = StorageTierType.WARM_ARCHIVE,
        storage_pool_id: str = "default_pool",
    ) -> None:
        self.segment_id = segment_id
        self.recording_id = recording_id
        self.camera_id = camera_id
        self.segment_index = segment_index
        self.target_dir = Path(target_dir).resolve()
        self.target_dir.mkdir(parents=True, exist_ok=True)

        self.codec = codec
        self.fps = fps if fps > 0 else 15.0
        self.resolution = resolution
        self.tier = tier
        self.storage_pool_id = storage_pool_id

        # Predictable file naming with accurate media extension
        safe_cam = camera_id.replace("/", "_").replace("\\", "_")
        self.start_timestamp_utc = time.time()
        self.start_iso = datetime.now(timezone.utc).isoformat()
        if codec == RecordingCodec.NATIVE_PASS_THROUGH or codec == RecordingCodec.H264:
            ext = ".h264"
        elif codec == RecordingCodec.H265:
            ext = ".h265"
        else:
            ext = ".mp4"
        self.filename = f"{safe_cam}_{int(self.start_timestamp_utc)}_{segment_index:05d}{ext}"
        self.final_path = self.target_dir / self.filename
        self.part_path = self.target_dir / f"{self.filename}.part"

        self.hasher = hashlib.sha256()
        self.bytes_written = 0
        self.frames_written = 0
        self.keyframe_count = 0
        self.has_keyframes = False
        self.is_closed = False
        self.has_motion = False
        self.has_event = False
        self.event_ids: list[str] = []

        self._raw_file: Any = None
        self._cv2_writer: Any = None

        # If writing raw frames with cv2 available and codec not raw elementary pass-through
        if _HAS_CV2 and codec not in (RecordingCodec.NATIVE_PASS_THROUGH, RecordingCodec.H264, RecordingCodec.H265):
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self._cv2_writer = cv2.VideoWriter(
                str(self.part_path),
                fourcc,
                self.fps,
                self.resolution,
            )
            if not self._cv2_writer.isOpened():
                self._cv2_writer = None
                self._raw_file = open(self.part_path, "wb")
        else:
            self._raw_file = open(self.part_path, "wb")

    def write_raw_packet(self, packet_bytes: bytes, is_keyframe: bool = False) -> None:
        """Write camera-native encoded stream packet directly to disk without transcoding."""
        if self.is_closed:
            raise RuntimeError(f"Cannot write packet to closed segment '{self.segment_id}'.")
        if not packet_bytes:
            return

        if is_keyframe:
            self.keyframe_count += 1
            self.has_keyframes = True

        self.hasher.update(packet_bytes)
        if self._raw_file is not None:
            self._raw_file.write(packet_bytes)
        self.bytes_written += len(packet_bytes)
        self.frames_written += 1

    def write_numpy_frame(self, frame: np.ndarray, motion_detected: bool = False, event_id: str | None = None) -> None:
        """Write uncompressed video frame to segment file."""
        if self.is_closed:
            raise RuntimeError(f"Cannot write frame to closed segment '{self.segment_id}'.")
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            return

        if motion_detected:
            self.has_motion = True
        if event_id:
            self.has_event = True
            if event_id not in self.event_ids:
                self.event_ids.append(event_id)

        raw_bytes = frame.tobytes()
        self.hasher.update(raw_bytes)

        if self._cv2_writer is not None:
            if frame.shape[1] != self.resolution[0] or frame.shape[0] != self.resolution[1]:
                if _HAS_CV2:
                    frame = cv2.resize(frame, self.resolution)
            self._cv2_writer.write(frame)
        else:
            self._raw_file.write(raw_bytes)

        self.bytes_written = self.part_path.stat().st_size if self.part_path.exists() else self.bytes_written + len(raw_bytes)
        self.frames_written += 1

    def close(self) -> RecordingSegmentMetadata:
        """
        Finalize and commit segment file atomically.
        Computes final SHA-256 hash and generates RecordingSegmentMetadata.
        """
        if self.is_closed:
            raise RuntimeError(f"Segment '{self.segment_id}' is already closed.")

        self.is_closed = True
        end_time_utc = time.time()
        end_iso = datetime.now(timezone.utc).isoformat()
        duration = max(0.001, end_time_utc - self.start_timestamp_utc)

        if self._cv2_writer is not None:
            self._cv2_writer.release()
            self._cv2_writer = None
        if self._raw_file is not None and not self._raw_file.closed:
            self._raw_file.flush()
            self._raw_file.close()
            self._raw_file = None

        # Ensure file exists and is non-empty
        if self.part_path.exists():
            if self.part_path.stat().st_size == 0:
                self.part_path.write_bytes(b"ISEP_EMPTY_SEGMENT_PLACEHOLDER")

            final_size = self.part_path.stat().st_size

            # Compute complete disk file hash
            file_hasher = hashlib.sha256()
            with open(self.part_path, "rb") as f:
                while chunk := f.read(65536):
                    file_hasher.update(chunk)
            file_sha256 = file_hasher.hexdigest()

            # Atomic commit (.part -> final) with retry for Windows file locking
            committed = False
            for _ in range(5):
                try:
                    self.part_path.replace(self.final_path)
                    committed = True
                    break
                except PermissionError:
                    time.sleep(0.05)

            if not committed:
                # Fallback rename
                import shutil
                shutil.move(str(self.part_path), str(self.final_path))

            bitrate_kbps = ((final_size * 8.0) / (duration * 1000.0)) if duration > 0 else 0.0

            metadata = RecordingSegmentMetadata(
                schema_version="2.0",
                segment_id=self.segment_id,
                recording_id=self.recording_id,
                camera_id=self.camera_id,
                segment_index=self.segment_index,
                start_time_utc=self.start_iso,
                end_time_utc=end_iso,
                duration_seconds=duration,
                file_path=str(self.final_path),
                file_size_bytes=final_size,
                sha256_hash=file_sha256,
                codec=self.codec.value,
                resolution=self.resolution,
                fps=self.fps,
                bitrate_kbps=bitrate_kbps,
                tier=self.tier,
                storage_pool_id=self.storage_pool_id,
                state=SegmentState.FINALIZED,
                has_motion=self.has_motion,
                has_event=self.has_event,
                event_ids=self.event_ids,
                keyframe_count=self.keyframe_count,
                has_keyframes=self.has_keyframes,
            )
            logger.info(
                "isep.segment_finalized",
                segment_id=self.segment_id,
                size_bytes=final_size,
                sha256=file_sha256[:16],
            )
            return metadata

        raise FileNotFoundError(f"Segment part file missing: {self.part_path}")


class RecordingSegmentManager:
    """
    Coordinates active segment writers, file roll-over, partial-write crash recovery,
    and continuity gap monitoring across all recording cameras.
    """

    def __init__(
        self,
        base_storage_dir: Path | str,
        segment_duration_seconds: float = 60.0,
        max_segment_size_bytes: int = 500 * 1024 * 1024,  # 500 MB
        tier: StorageTierType = StorageTierType.WARM_ARCHIVE,
        storage_pool_id: str = "default_pool",
    ) -> None:
        self.base_storage_dir = Path(base_storage_dir).resolve()
        self.base_storage_dir.mkdir(parents=True, exist_ok=True)

        self.segment_duration_seconds = segment_duration_seconds
        self.max_segment_size_bytes = max_segment_size_bytes
        self.tier = tier
        self.storage_pool_id = storage_pool_id

        self.active_writers: dict[str, RecordingSegmentWriter] = {}
        self.segment_counters: dict[str, int] = {}
        self.finalized_segments: list[RecordingSegmentMetadata] = []

    def start_segment(
        self,
        recording_id: str,
        camera_id: str,
        codec: RecordingCodec = RecordingCodec.H264,
        fps: float = 15.0,
        resolution: tuple[int, int] = (1920, 1080),
    ) -> RecordingSegmentWriter:
        """Start a new sequential recording segment for a camera channel."""
        # Close active writer if already open
        if camera_id in self.active_writers:
            self.finalize_segment(camera_id)

        idx = self.segment_counters.get(camera_id, 0)
        segment_id = f"seg_{camera_id}_{int(time.time())}_{idx:05d}"
        self.segment_counters[camera_id] = idx + 1

        writer = RecordingSegmentWriter(
            segment_id=segment_id,
            recording_id=recording_id,
            camera_id=camera_id,
            segment_index=idx,
            target_dir=self.base_storage_dir / camera_id,
            codec=codec,
            fps=fps,
            resolution=resolution,
            tier=self.tier,
            storage_pool_id=self.storage_pool_id,
        )
        self.active_writers[camera_id] = writer
        return writer

    def should_roll_over(self, camera_id: str) -> bool:
        """Check whether active segment should roll over due to time or size threshold."""
        writer = self.active_writers.get(camera_id)
        if not writer or writer.is_closed:
            return False

        elapsed = time.time() - writer.start_timestamp_utc
        if elapsed >= self.segment_duration_seconds:
            return True

        if writer.bytes_written >= self.max_segment_size_bytes:
            return True

        if writer.part_path.exists() and writer.part_path.stat().st_size >= self.max_segment_size_bytes:
            return True

        return False

    def finalize_segment(self, camera_id: str) -> RecordingSegmentMetadata | None:
        """Finalize and commit active recording segment for a camera."""
        writer = self.active_writers.pop(camera_id, None)
        if not writer or writer.is_closed:
            return None

        meta = writer.close()
        self.finalized_segments.append(meta)
        return meta

    def recover_orphaned_part_files(self) -> list[RecordingSegmentMetadata]:
        """
        Scan storage directories for abandoned '.part' files after a crash/restart.
        Finalizes them safely with calculated SHA-256 and marks them as recovered.
        """
        recovered: list[RecordingSegmentMetadata] = []
        for part_file in list(self.base_storage_dir.rglob("*.part")):
            if not part_file.is_file():
                continue
            try:
                final_path = part_file.with_suffix("")  # Strip .part
                if final_path.exists():
                    # Both exist: part file might be duplicate; rename part
                    final_path = part_file.with_name(f"{part_file.stem}_recovered_{int(time.time())}.mp4")

                st = part_file.stat()
                file_size = st.st_size
                created_time = st.st_ctime
                if file_size == 0:
                    part_file.unlink()
                    continue

                hasher = hashlib.sha256()
                with open(part_file, "rb") as f:
                    while chunk := f.read(65536):
                        hasher.update(chunk)
                sha256_hash = hasher.hexdigest()

                part_file.replace(final_path)

                # Parse camera_id from parent dir or filename
                camera_id = part_file.parent.name if part_file.parent != self.base_storage_dir else "unknown_camera"
                rec_id = f"rec_recovered_{int(time.time())}"
                seg_id = f"seg_recov_{part_file.stem}"

                estimated_duration = max(0.001, round(file_size / (200.0 * 1024.0), 3))
                meta = RecordingSegmentMetadata(
                    schema_version="2.0",
                    segment_id=seg_id,
                    recording_id=rec_id,
                    camera_id=camera_id,
                    segment_index=0,
                    start_time_utc=datetime.fromtimestamp(created_time, timezone.utc).isoformat(),
                    end_time_utc=datetime.now(timezone.utc).isoformat(),
                    duration_seconds=estimated_duration,
                    file_path=str(final_path),
                    file_size_bytes=file_size,
                    sha256_hash=sha256_hash,
                    codec="unknown",
                    resolution=(1920, 1080),
                    fps=15.0,
                    bitrate_kbps=0.0,
                    tier=self.tier,
                    storage_pool_id=self.storage_pool_id,
                    state=SegmentState.RECOVERED_PARTIAL,
                    is_partial=True,
                    recovery_notes=f"Recovered unfinalized stream fragment post-crash from orphaned {part_file.name}",
                    source_part_path=str(part_file),
                )
                recovered.append(meta)
                logger.warning("isep.orphaned_part_recovered_partial", path=str(final_path), size=file_size)
            except Exception as exc:
                logger.error("isep.part_recovery_failed", file=str(part_file), error=str(exc))

        return recovered
