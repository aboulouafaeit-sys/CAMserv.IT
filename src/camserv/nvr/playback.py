"""
camserv.nvr.playback
====================

Recording playback engine, multi-camera synchronized timeline generator,
event marker indexing, and clipped time-range export for CAMserv NVR.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from camserv.storage.sqlite_store import SQLiteStore

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class TimelineMarker:
    """Individual event or motion point-of-interest on a playback timeline."""

    marker_id: str
    camera_id: str
    timestamp_utc: str
    marker_type: str  # 'motion', 'event', 'detection', 'human_verification'
    severity: str = "info"  # 'info', 'warning', 'critical'
    description: str = ""
    event_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TimelineSpan:
    """Contiguous block of recorded footage available for playback."""

    camera_id: str
    start_time_utc: str
    end_time_utc: str
    duration_seconds: float
    segment_ids: list[str]
    has_motion: bool = False
    has_event: bool = False
    markers: list[TimelineMarker] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["markers"] = [m.to_dict() for m in self.markers]
        return d


@dataclass
class PlaybackSession:
    """Operator playback control state for single or multi-camera views."""

    session_id: str
    camera_ids: list[str]
    current_position_utc: str
    speed: float = 1.0  # 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0 (negative for rewind)
    is_paused: bool = False
    loop: bool = False

    def seek(self, target_utc: str) -> None:
        """Seek synchronized playback head to target UTC timestamp."""
        self.current_position_utc = target_utc

    def set_speed(self, speed: float) -> None:
        """Update playback speed factor."""
        self.speed = speed

    def toggle_pause(self) -> bool:
        """Toggle play / pause state."""
        self.is_paused = not self.is_paused
        return self.is_paused


class PlaybackTimelineEngine:
    """
    Coordinates recording queries, multi-camera timeline assembly,
    event navigation, and clipped video range export.
    """

    def __init__(self, store: SQLiteStore, storage_dir: Path | str) -> None:
        self.store = store
        self.storage_dir = Path(storage_dir).resolve()
        self.active_playback_sessions: dict[str, PlaybackSession] = {}

    def get_camera_timeline(
        self,
        camera_id: str,
        start_time_utc: str,
        end_time_utc: str,
    ) -> list[TimelineSpan]:
        """
        Assemble contiguous recording spans and overlays for a camera across a time range.
        """
        segments = self.store.query_segments_by_time_range(
            camera_id=camera_id,
            start_time_utc=start_time_utc,
            end_time_utc=end_time_utc,
        )
        if not segments:
            return []

        # Retrieve events in window to generate markers
        events = self.store.query_events(camera_id=camera_id, limit=200)
        events_in_window = [
            e for e in events
            if start_time_utc <= e.get("timestamp", "") <= end_time_utc
        ]

        markers: list[TimelineMarker] = []
        for ev in events_in_window:
            markers.append(
                TimelineMarker(
                    marker_id=f"marker_{ev['event_id']}",
                    camera_id=camera_id,
                    timestamp_utc=ev.get("timestamp", ""),
                    marker_type="event",
                    severity=ev.get("severity", "warning"),
                    description=ev.get("description", ""),
                    event_id=ev.get("event_id"),
                    metadata=ev.get("metadata", {}),
                )
            )

        spans: list[TimelineSpan] = []
        for seg in segments:
            seg_start = seg["start_time_utc"]
            seg_end = seg["end_time_utc"]
            seg_markers = [
                m for m in markers
                if seg_start <= m.timestamp_utc <= seg_end
            ]

            spans.append(
                TimelineSpan(
                    camera_id=camera_id,
                    start_time_utc=seg_start,
                    end_time_utc=seg_end,
                    duration_seconds=float(seg["duration_seconds"]),
                    segment_ids=[seg["segment_id"]],
                    has_motion=seg.get("has_motion", False),
                    has_event=seg.get("has_event", False) or len(seg_markers) > 0,
                    markers=seg_markers,
                )
            )

        return spans

    def get_multi_camera_timeline(
        self,
        camera_ids: list[str],
        start_time_utc: str,
        end_time_utc: str,
    ) -> dict[str, list[TimelineSpan]]:
        """
        Retrieve synchronized timelines across multiple camera feeds.
        """
        return {
            cam_id: self.get_camera_timeline(cam_id, start_time_utc, end_time_utc)
            for cam_id in camera_ids
        }

    def create_playback_session(
        self,
        session_id: str,
        camera_ids: list[str],
        start_position_utc: str,
    ) -> PlaybackSession:
        """Create and track an interactive playback session."""
        session = PlaybackSession(
            session_id=session_id,
            camera_ids=camera_ids,
            current_position_utc=start_position_utc,
        )
        self.active_playback_sessions[session_id] = session
        return session

    def export_clipped_range(
        self,
        camera_id: str,
        start_time_utc: str,
        end_time_utc: str,
        output_path: Path | str,
    ) -> dict[str, Any]:
        """
        Export a clipped video range matching the requested time window.
        Locates matching segments, concatenates or bundles payload,
        and generates a verifiable cryptographic manifest.
        """
        target_path = Path(output_path).resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)

        segments = self.store.query_segments_by_time_range(
            camera_id=camera_id,
            start_time_utc=start_time_utc,
            end_time_utc=end_time_utc,
        )

        if not segments:
            raise FileNotFoundError(f"No video segments found for camera '{camera_id}' between {start_time_utc} and {end_time_utc}.")

        total_bytes = 0
        hasher = hashlib.sha256()

        # Concatenate segment files into target output file
        with open(target_path, "wb") as out_f:
            for seg in segments:
                src_path = Path(seg["file_path"])
                if src_path.exists():
                    with open(src_path, "rb") as in_f:
                        while chunk := in_f.read(65536):
                            out_f.write(chunk)
                            hasher.update(chunk)
                            total_bytes += len(chunk)

        manifest = {
            "export_id": f"clip_{camera_id}_{int(time.time())}",
            "camera_id": camera_id,
            "start_time_utc": start_time_utc,
            "end_time_utc": end_time_utc,
            "output_file": str(target_path),
            "file_size_bytes": total_bytes,
            "sha256_hash": hasher.hexdigest(),
            "segments_included": [s["segment_id"] for s in segments],
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info("nvr.playback.clip_exported", camera_id=camera_id, size=total_bytes, sha256=manifest["sha256_hash"][:12])
        return manifest
