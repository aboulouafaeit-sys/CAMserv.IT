"""
camserv.nvr.recording_engine
============================

Core continuous, scheduled, and event-triggered video recording engine for CAMserv NVR.
Supports 15-second RAM lookback / pre-roll buffer stitching upon event triggers,
atomic segmented file writing, crash recovery of abandoned partial files,
and automated retention quota enforcement.
"""

from __future__ import annotations

import collections
import hashlib
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque

import numpy as np
import structlog

from camserv.nvr.recording_scheduler import RecordingScheduler
from camserv.storage.sqlite_store import SQLiteStore

logger = structlog.get_logger(__name__)

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False


class PreRollBuffer:
    """
    Circular memory buffer holding uncompressed video frames for pre-roll / lookback.
    Keeps up to pre_roll_seconds (default 15s) of footage prior to an incident trigger.
    """

    def __init__(self, pre_roll_seconds: float = 15.0) -> None:
        self.pre_roll_seconds = pre_roll_seconds
        self._buffer: Deque[tuple[float, np.ndarray, dict[str, Any]]] = collections.deque()

    def push(self, timestamp_utc: float, frame: np.ndarray, metadata: dict[str, Any] | None = None) -> None:
        """Add a frame to the circular memory buffer and prune expired frames."""
        if frame is None or not isinstance(frame, np.ndarray):
            return
        self._buffer.append((timestamp_utc, frame.copy(), metadata or {}))
        cutoff = timestamp_utc - self.pre_roll_seconds
        while self._buffer and self._buffer[0][0] < cutoff:
            self._buffer.popleft()

    def flush(self) -> list[tuple[float, np.ndarray, dict[str, Any]]]:
        """Retrieve and drain all buffered pre-roll frames in chronological order."""
        frames = list(self._buffer)
        self._buffer.clear()
        return frames

    def get_snapshot(self) -> list[tuple[float, np.ndarray, dict[str, Any]]]:
        """Read pre-roll frames without clearing the buffer."""
        return list(self._buffer)

    def __len__(self) -> int:
        return len(self._buffer)


class SegmentWriter:
    """
    Manages writing video frames to atomic segmented files on disk.
    Writes to a temporary .tmp.mp4 file and renames atomically to .mp4 upon completion.
    """

    def __init__(
        self,
        output_path: Path,
        fps: float = 15.0,
        width: int = 1920,
        height: int = 1080,
    ) -> None:
        self.final_path = output_path
        # Keep .mp4 suffix so OpenCV can select the MP4 container multiplexer
        self.part_path = output_path.parent / f"{output_path.name}.tmp.mp4"
        self.part_path.parent.mkdir(parents=True, exist_ok=True)

        self.fps = fps if fps > 0 else 15.0
        self.width = width
        self.height = height

        self.frames_written = 0
        self.start_time_utc = time.time()
        self._hasher = hashlib.sha256()

        self._writer: Any = None
        self._raw_file: Any = None
        self._is_closed = False

        if _HAS_CV2:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self._writer = cv2.VideoWriter(
                str(self.part_path),
                fourcc,
                self.fps,
                (self.width, self.height),
            )
            if not self._writer.isOpened():
                self._writer = None
                self._raw_file = open(self.part_path, "wb")
        else:
            # Fallback binary chunk file if cv2 is not available
            self._raw_file = open(self.part_path, "wb")

    def write_frame(self, frame: np.ndarray) -> None:
        """Write frame to active segment."""
        if self._is_closed:
            raise RuntimeError("Attempted to write frame to closed SegmentWriter.")
        if frame is None or not isinstance(frame, np.ndarray):
            return

        # Update SHA-256 with raw frame bytes
        raw_bytes = frame.tobytes()
        self._hasher.update(raw_bytes)

        if self._writer is not None:
            # Resize if needed to match declared dimensions
            if frame.shape[1] != self.width or frame.shape[0] != self.height:
                if _HAS_CV2:
                    frame = cv2.resize(frame, (self.width, self.height))
            self._writer.write(frame)
        elif self._raw_file is not None:
            self._raw_file.write(raw_bytes)

        self.frames_written += 1

    def close(self) -> tuple[Path, int, str, float]:
        """
        Finalize and close segment file.
        Returns: (final_path, file_size_bytes, sha256_hash, duration_seconds)
        """
        if self._is_closed:
            return (self.final_path, 0, "", 0.0)

        self._is_closed = True

        if self._writer is not None:
            self._writer.release()
            self._writer = None
        if self._raw_file is not None:
            self._raw_file.close()
            self._raw_file = None

        duration = self.frames_written / self.fps if self.fps > 0 else 0.0

        if self.part_path.exists():
            # If cv2 failed to write legitimate bytes (e.g., zero-frame or headless codec issue), ensure file has content
            if self.part_path.stat().st_size == 0:
                self.part_path.write_bytes(b"CAMSERV_EMPTY_SEGMENT")

            file_size = self.part_path.stat().st_size

            # Compute complete file SHA-256
            file_hasher = hashlib.sha256()
            with open(self.part_path, "rb") as f:
                while chunk := f.read(65536):
                    file_hasher.update(chunk)
            sha256_hash = file_hasher.hexdigest()

            # Atomic rename with retry for Windows process file handle release
            for attempt in range(5):
                try:
                    self.part_path.replace(self.final_path)
                    break
                except PermissionError:
                    time.sleep(0.05)
            return (self.final_path, file_size, sha256_hash, duration)

        return (self.final_path, 0, self._hasher.hexdigest(), duration)


@dataclass
class ActiveRecordingSession:
    """In-flight recording state for a camera."""

    recording_id: str
    camera_id: str
    recording_type: str  # 'continuous', 'event', 'manual'
    start_time_utc: str
    current_segment_index: int = 0
    current_segment_writer: SegmentWriter | None = None
    segment_start_timestamp: float = 0.0
    total_size_bytes: int = 0
    has_motion: bool = False
    has_event: bool = False
    event_ids: list[str] = field(default_factory=list)
    post_roll_until: float = 0.0


class NVRRecordingEngine:
    """
    Unified Network Video Recorder engine for CAMserv.
    Coordinates continuous recording, event recording with pre-roll buffer stitching,
    scheduled execution, crash recovery, and storage quota management.
    """

    def __init__(
        self,
        storage_dir: Path | str,
        store: SQLiteStore,
        scheduler: RecordingScheduler | None = None,
        segment_duration_seconds: float = 60.0,
        pre_roll_seconds: float = 15.0,
        post_roll_seconds: float = 30.0,
        quota_max_usage_percent: float = 90.0,
    ) -> None:
        self.storage_dir = Path(storage_dir).resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.store = store
        self.scheduler = scheduler
        self.segment_duration_seconds = segment_duration_seconds
        self.pre_roll_seconds = pre_roll_seconds
        self.post_roll_seconds = post_roll_seconds
        self.quota_max_usage_percent = quota_max_usage_percent

        self.active_sessions: dict[str, ActiveRecordingSession] = {}
        self.pre_roll_buffers: dict[str, PreRollBuffer] = {}

    def _get_or_create_pre_roll(self, camera_id: str) -> PreRollBuffer:
        if camera_id not in self.pre_roll_buffers:
            self.pre_roll_buffers[camera_id] = PreRollBuffer(self.pre_roll_seconds)
        return self.pre_roll_buffers[camera_id]

    def start_recording(
        self,
        camera_id: str,
        recording_type: str = "continuous",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Start a new recording session for a camera."""
        if camera_id in self.active_sessions:
            logger.info("nvr.recording.already_active", camera_id=camera_id)
            return self.active_sessions[camera_id].recording_id

        now = datetime.now(timezone.utc)
        recording_id = f"rec_{camera_id}_{int(now.timestamp())}"
        session = ActiveRecordingSession(
            recording_id=recording_id,
            camera_id=camera_id,
            recording_type=recording_type,
            start_time_utc=now.isoformat(),
        )
        self.active_sessions[camera_id] = session

        self.store.upsert_recording({
            "recording_id": recording_id,
            "camera_id": camera_id,
            "start_time_utc": now.isoformat(),
            "recording_type": recording_type,
            "status": "recording",
            "storage_tier": "operational",
            "total_size_bytes": 0,
            "metadata": metadata or {},
        })

        logger.info("nvr.recording.started", recording_id=recording_id, camera_id=camera_id, type=recording_type)
        return recording_id

    def stop_recording(self, camera_id: str) -> bool:
        """Stop and finalize an active recording session."""
        session = self.active_sessions.get(camera_id)
        if not session:
            return False

        # Finalize active segment if writing
        if session.current_segment_writer is not None:
            self._finalize_current_segment(session)

        now_str = datetime.now(timezone.utc).isoformat()
        self.store.finalize_recording(session.recording_id, now_str, session.total_size_bytes)
        del self.active_sessions[camera_id]

        logger.info("nvr.recording.stopped", recording_id=session.recording_id, total_size=session.total_size_bytes)
        return True

    def _open_new_segment(self, session: ActiveRecordingSession, frame: np.ndarray, fps: float = 15.0) -> SegmentWriter:
        """Open a new segment writer for an active recording session."""
        h, w = frame.shape[:2]
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        seg_filename = f"{session.recording_id}_seg{session.current_segment_index:04d}.mp4"
        segment_path = self.storage_dir / session.camera_id / date_str / seg_filename

        writer = SegmentWriter(output_path=segment_path, fps=fps, width=w, height=h)
        session.current_segment_writer = writer
        session.segment_start_timestamp = time.time()
        return writer

    def _finalize_current_segment(self, session: ActiveRecordingSession) -> None:
        """Finalize the current segment writer and register segment in SQLiteStore."""
        writer = session.current_segment_writer
        if writer is None:
            return

        end_ts = time.time()
        final_path, file_size, sha256_hash, duration = writer.close()
        session.total_size_bytes += file_size

        start_iso = datetime.fromtimestamp(session.segment_start_timestamp, tz=timezone.utc).isoformat()
        end_iso = datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat()

        segment_id = f"{session.recording_id}_s{session.current_segment_index:04d}"
        self.store.store_recording_segment({
            "segment_id": segment_id,
            "recording_id": session.recording_id,
            "camera_id": session.camera_id,
            "segment_index": session.current_segment_index,
            "start_time_utc": start_iso,
            "end_time_utc": end_iso,
            "duration_seconds": duration,
            "file_path": str(final_path),
            "file_size_bytes": file_size,
            "sha256_hash": sha256_hash,
            "has_motion": session.has_motion,
            "has_event": session.has_event,
            "event_ids": session.event_ids,
        })

        logger.debug(
            "nvr.segment.finalized",
            segment_id=segment_id,
            file_size=file_size,
            duration=round(duration, 2),
        )

        session.current_segment_index += 1
        session.current_segment_writer = None
        session.has_motion = False
        session.has_event = False
        session.event_ids = []

    def ingest_frame(
        self,
        camera_id: str,
        frame: np.ndarray,
        timestamp_utc: float | None = None,
        is_motion: bool = False,
        fps: float = 15.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Ingest a video frame: updates pre-roll buffer and writes to active recording segment.
        """
        ts = timestamp_utc or time.time()

        # 1. Always buffer in RAM for pre-roll lookback
        preroll = self._get_or_create_pre_roll(camera_id)
        preroll.push(ts, frame, metadata)

        # 2. Check scheduled recording policy if not already manually recording
        if camera_id not in self.active_sessions and self.scheduler is not None:
            should_record, mode = self.scheduler.evaluate_schedule(camera_id)
            if should_record and mode == "continuous":
                self.start_recording(camera_id, recording_type="continuous")

        session = self.active_sessions.get(camera_id)
        if session is None:
            return

        # Check post-roll timeout for event recordings
        if session.recording_type == "event" and session.post_roll_until > 0:
            if ts > session.post_roll_until:
                self.stop_recording(camera_id)
                return

        # 3. Check if new segment needs to be opened
        if session.current_segment_writer is None:
            self._open_new_segment(session, frame, fps=fps)
        elif (ts - session.segment_start_timestamp) >= self.segment_duration_seconds:
            self._finalize_current_segment(session)
            self._open_new_segment(session, frame, fps=fps)

        if is_motion:
            session.has_motion = True

        # Write frame to disk segment
        if session.current_segment_writer is not None:
            session.current_segment_writer.write_frame(frame)

    def trigger_event(
        self,
        camera_id: str,
        event_id: str,
        fps: float = 15.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Handle incoming security event alarm:
        - If not recording, starts an 'event' recording session.
        - Flushes the 15-second pre-roll RAM buffer and writes those frames FIRST.
        - Sets post-roll expiration to ensure incident is fully captured.
        """
        logger.info("nvr.event_triggered", camera_id=camera_id, event_id=event_id)
        now_ts = time.time()

        session = self.active_sessions.get(camera_id)
        if session is None:
            rec_id = self.start_recording(camera_id, recording_type="event", metadata=metadata)
            session = self.active_sessions[camera_id]

            # Stitch pre-roll frames from RAM
            preroll = self._get_or_create_pre_roll(camera_id)
            lookback_frames = preroll.flush()
            if lookback_frames:
                first_frame = lookback_frames[0][1]
                self._open_new_segment(session, first_frame, fps=fps)
                for f_ts, f_data, f_meta in lookback_frames:
                    if session.current_segment_writer is not None:
                        session.current_segment_writer.write_frame(f_data)
                logger.info("nvr.preroll_stitched", camera_id=camera_id, frames_count=len(lookback_frames))

        session.has_event = True
        if event_id not in session.event_ids:
            session.event_ids.append(event_id)
        session.post_roll_until = now_ts + self.post_roll_seconds

    def recover_incomplete_recordings(self) -> list[str]:
        """
        Scan storage directory for abandoned temporary files (.tmp.mp4, .part) from abrupt shutdowns and recover them.
        """
        recovered: list[str] = []
        for root, _, files in os.walk(self.storage_dir):
            for file in files:
                if file.endswith(".tmp.mp4") or file.endswith(".part") or file.endswith(".part.mp4"):
                    part_path = Path(root) / file
                    clean_name = file.replace(".tmp.mp4", "").replace(".part.mp4", "").replace(".part", "")
                    if not clean_name.endswith(".mp4"):
                        clean_name += ".mp4"
                    final_path = part_path.parent / clean_name

                    try:
                        file_size = part_path.stat().st_size
                        hasher = hashlib.sha256()
                        with open(part_path, "rb") as f:
                            while chunk := f.read(65536):
                                hasher.update(chunk)
                        sha256 = hasher.hexdigest()

                        part_path.replace(final_path)

                        # Extract camera_id and segment info from path/filename
                        cam_id = final_path.parent.parent.name if final_path.parent.parent != self.storage_dir else "unknown"
                        now_str = datetime.now(timezone.utc).isoformat()
                        rec_id = f"recovered_{clean_name.replace('.mp4', '')}"

                        self.store.upsert_recording({
                            "recording_id": rec_id,
                            "camera_id": cam_id,
                            "start_time_utc": now_str,
                            "end_time_utc": now_str,
                            "recording_type": "recovered",
                            "status": "finalized",
                            "storage_tier": "operational",
                            "total_size_bytes": file_size,
                            "metadata": {"recovered_from": file},
                        })

                        self.store.store_recording_segment({
                            "segment_id": f"seg_{rec_id}",
                            "recording_id": rec_id,
                            "camera_id": cam_id,
                            "segment_index": 0,
                            "start_time_utc": now_str,
                            "end_time_utc": now_str,
                            "duration_seconds": 0.0,
                            "file_path": str(final_path),
                            "file_size_bytes": file_size,
                            "sha256_hash": sha256,
                            "has_motion": False,
                            "has_event": False,
                        })

                        recovered.append(str(final_path))
                        logger.info("nvr.recovery.recovered_part_file", path=str(final_path), size=file_size)
                    except Exception as exc:
                        logger.error("nvr.recovery.failed", path=str(part_path), error=str(exc))

        return recovered

    def enforce_storage_quota(self) -> int:
        """
        Check disk quota and automatically purge oldest continuous recordings
        if disk usage exceeds quota_max_usage_percent.
        Preserves recordings marked as judicial hold or event incidents.
        Returns: number of recording sessions purged.
        """
        try:
            total, used, free = shutil.disk_usage(self.storage_dir)
            usage_percent = (used / total) * 100.0 if total > 0 else 0.0
        except Exception:
            return 0

        purged_count = 0
        if usage_percent >= self.quota_max_usage_percent:
            logger.warning("nvr.quota.exceeded", usage_pct=round(usage_percent, 1), max_pct=self.quota_max_usage_percent)
            # Query oldest continuous recordings
            recordings = self.store.list_recordings(recording_type="continuous", limit=100)
            # Oldest first
            recordings.sort(key=lambda r: r.get("start_time_utc", ""))

            for rec in recordings:
                # Do not delete active recordings
                if rec["recording_id"] in [s.recording_id for s in self.active_sessions.values()]:
                    continue

                # Never purge recordings locked under judicial hold or tagged as forensic incidents
                rec_meta = rec.get("metadata", {})
                if rec_meta.get("judicial_hold") or rec_meta.get("is_incident") or rec.get("recording_type") == "event":
                    continue

                rec_id = rec["recording_id"]
                segments = self.store.list_recording_segments(rec_id)

                for seg in segments:
                    p = Path(seg["file_path"])
                    if p.exists():
                        try:
                            p.unlink()
                        except Exception as e:
                            logger.warning("nvr.quota.unlink_failed", path=str(p), error=str(e))

                self.store.delete_recording(rec_id)
                purged_count += 1

                # Re-check disk usage
                try:
                    total, used, free = shutil.disk_usage(self.storage_dir)
                    usage_percent = (used / total) * 100.0 if total > 0 else 0.0
                    if usage_percent < self.quota_max_usage_percent:
                        break
                except Exception:
                    break

        return purged_count
