"""
camserv.intelligence.tracking
=============================

Spatio-Temporal Anonymous Multi-Object Tracking Engine.

Enforces:
- Anonymous integer track IDs scoped strictly to camera and session.
- Track lifecycle: NEW -> TRACKED -> LOST -> REMOVED.
- Occlusion tolerance and lost-track recovery.
- Track fragmentation detection and reporting.
- Frame discontinuity (packet loss / network stall) detection.
- Bounded memory footprint (max active tracks per camera).
- STRICT PRIVACY: Zero facial recognition, zero biometric profiling,
  and zero cross-camera identity linkage.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Sequence

from camserv.intelligence.contracts import (
    BoundingBox,
    DetectionPrediction,
    EngineHealthStatus,
    TrackLifecycleState,
    TrackRecord,
)


class ObjectTrackingEngine:
    """
    Thread-safe anonymous multi-object tracking engine enforcing spatial
    continuity, lifecycle accounting, and strict privacy isolation.
    """

    def __init__(
        self,
        camera_id: str,
        session_id: str = "default_session",
        max_lost_frames: int = 30,
        iou_threshold: float = 0.30,
        max_active_tracks: int = 200,
        discontinuity_threshold_sec: float = 1.0,
    ) -> None:
        self.camera_id = camera_id
        self.session_id = session_id
        self._max_lost_frames = max_lost_frames
        self._iou_threshold = iou_threshold
        self._max_active_tracks = max_active_tracks
        self._discontinuity_threshold_sec = discontinuity_threshold_sec

        self._lock = threading.RLock()
        self._next_track_id: int = 1
        self._tracks: dict[int, TrackRecord] = {}
        self._lost_counters: dict[int, int] = {}
        self._fragmentation_count: int = 0
        self._discontinuity_events: int = 0
        self._last_frame_timestamp: float = 0.0
        self._last_frame_id: int = -1
        self._health_status = EngineHealthStatus.ACTIVE

    @property
    def health_status(self) -> EngineHealthStatus:
        with self._lock:
            return self._health_status

    @property
    def active_track_count(self) -> int:
        with self._lock:
            return len([t for t in self._tracks.values() if t.state == TrackLifecycleState.TRACKED])

    @property
    def fragmentation_count(self) -> int:
        with self._lock:
            return self._fragmentation_count

    @property
    def discontinuity_events(self) -> int:
        with self._lock:
            return self._discontinuity_events

    def update(
        self,
        detections: list[DetectionPrediction],
        frame_id: int,
        timestamp_utc: float | None = None,
    ) -> list[TrackRecord]:
        """
        Update tracking state with new detections for the current frame.
        """
        now = timestamp_utc or time.time()

        with self._lock:
            # 1. Frame Discontinuity Check
            if self._last_frame_timestamp > 0.0:
                gap_sec = now - self._last_frame_timestamp
                frame_jump = frame_id - self._last_frame_id
                if gap_sec > self._discontinuity_threshold_sec or frame_jump > 10:
                    self._discontinuity_events += 1

            self._last_frame_timestamp = now
            self._last_frame_id = frame_id

            # 2. Bipartite Association between existing tracks and incoming detections
            active_track_ids = list(self._tracks.keys())
            matched_tracks: set[int] = set()
            matched_detections: set[int] = set()

            # Spatial association with velocity projection
            for det_idx, det in enumerate(detections):
                best_iou = 0.0
                best_track_id = -1

                for trk_id in active_track_ids:
                    if trk_id in matched_tracks:
                        continue
                    trk = self._tracks[trk_id]
                    # Evaluate both static IoU and motion-projected IoU
                    projected_box = self._project_bbox(trk, now)
                    iou = max(trk.bbox.iou(det.bbox), projected_box.iou(det.bbox))
                    if iou > best_iou and iou >= self._iou_threshold:
                        best_iou = iou
                        best_track_id = trk_id

                if best_track_id != -1:
                    matched_tracks.add(best_track_id)
                    matched_detections.add(det_idx)
                    self._update_existing_track(best_track_id, det, now)

            # 3. Handle Unmatched Existing Tracks (Lost handling)
            for trk_id in active_track_ids:
                if trk_id not in matched_tracks:
                    self._handle_unmatched_track(trk_id)

            # 4. Handle Unmatched Detections (New track creation)
            for det_idx, det in enumerate(detections):
                if det_idx not in matched_detections:
                    if len(self._tracks) < self._max_active_tracks:
                        self._create_new_track(det, now)

            # 5. Return currently confirmed tracks
            return [
                t for t in self._tracks.values()
                if t.state in (TrackLifecycleState.TRACKED, TrackLifecycleState.NEW)
            ]

    def _project_bbox(self, trk: TrackRecord, now: float) -> BoundingBox:
        """Project track bounding box forward using its estimated velocity vector."""
        dt = min(1.0, max(0.0, now - trk.last_seen_utc))
        vx, vy = trk.velocity_pixels_per_sec
        dx = vx * dt
        dy = vy * dt
        try:
            return BoundingBox(
                x1=trk.bbox.x1 + dx,
                y1=trk.bbox.y1 + dy,
                x2=trk.bbox.x2 + dx,
                y2=trk.bbox.y2 + dy,
            )
        except ValueError:
            return trk.bbox

    def _update_existing_track(
        self,
        track_id: int,
        det: DetectionPrediction,
        now: float,
    ) -> None:
        """Update an actively matched track with new detection coordinates."""
        trk = self._tracks[track_id]
        dt = max(0.001, now - trk.last_seen_utc)

        prev_center = trk.bbox.center
        curr_center = det.bbox.center
        vx = (curr_center[0] - prev_center[0]) / dt
        vy = (curr_center[1] - prev_center[1]) / dt

        trajectory = list(trk.trajectory)
        trajectory.append(curr_center)
        if len(trajectory) > 50:
            trajectory.pop(0)

        # Transition NEW -> TRACKED on temporal confirmation
        new_state = TrackLifecycleState.TRACKED

        updated_track = TrackRecord(
            track_id=trk.track_id,
            camera_id=self.camera_id,
            session_id=self.session_id,
            bbox=det.bbox,
            class_name=det.class_name,
            class_id=det.class_id,
            confidence=round((trk.confidence + det.confidence) / 2.0, 4),
            state=new_state,
            age_frames=trk.age_frames + 1,
            created_at_utc=trk.created_at_utc,
            last_seen_utc=now,
            velocity_pixels_per_sec=(round(vx, 2), round(vy, 2)),
            trajectory=trajectory,
            is_prediction=True,
            metadata=trk.metadata,
        )
        self._tracks[track_id] = updated_track
        self._lost_counters[track_id] = 0

    def _handle_unmatched_track(self, track_id: int) -> None:
        """Increment lost counter and evict track if expiration limit reached."""
        trk = self._tracks[track_id]
        lost_count = self._lost_counters.get(track_id, 0) + 1
        self._lost_counters[track_id] = lost_count

        if lost_count > self._max_lost_frames:
            # Track is removed due to age/loss
            self._fragmentation_count += 1
            self._tracks.pop(track_id, None)
            self._lost_counters.pop(track_id, None)
        else:
            # Mark track as temporarily lost
            self._tracks[track_id] = TrackRecord(
                track_id=trk.track_id,
                camera_id=trk.camera_id,
                session_id=trk.session_id,
                bbox=trk.bbox,
                class_name=trk.class_name,
                class_id=trk.class_id,
                confidence=max(0.1, trk.confidence * 0.95),
                state=TrackLifecycleState.LOST,
                age_frames=trk.age_frames + 1,
                created_at_utc=trk.created_at_utc,
                last_seen_utc=trk.last_seen_utc,
                velocity_pixels_per_sec=trk.velocity_pixels_per_sec,
                trajectory=trk.trajectory,
                is_prediction=True,
                metadata=trk.metadata,
            )

    def _create_new_track(self, det: DetectionPrediction, now: float) -> None:
        """Instantiate a new candidate track."""
        track_id = self._next_track_id
        self._next_track_id += 1

        new_track = TrackRecord(
            track_id=track_id,
            camera_id=self.camera_id,
            session_id=self.session_id,
            bbox=det.bbox,
            class_name=det.class_name,
            class_id=det.class_id,
            confidence=det.confidence,
            state=TrackLifecycleState.NEW,
            age_frames=1,
            created_at_utc=now,
            last_seen_utc=now,
            velocity_pixels_per_sec=(0.0, 0.0),
            trajectory=[det.bbox.center],
            is_prediction=True,
            metadata={"source_detection": det.metadata},
        )
        self._tracks[track_id] = new_track
        self._lost_counters[track_id] = 0

    def reset(self) -> None:
        """Clear all active tracks and reset tracking state."""
        with self._lock:
            self._tracks.clear()
            self._lost_counters.clear()
            self._fragmentation_count = 0
            self._discontinuity_events = 0
