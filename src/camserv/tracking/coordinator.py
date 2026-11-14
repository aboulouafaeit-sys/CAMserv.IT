"""
camserv.tracking.coordinator
============================

Camera-Isolated Multi-Object Tracking Coordinator and Kinematics Engine for CAMserv.

Features:
- Strict Camera Isolation: No cross-camera feature matching or cross-camera tracking.
- Track Lifecycle State Machine: TENTATIVE -> CONFIRMED -> OCCLUDED -> EXPIRED.
- Non-Biometric Anonymity: Ephemeral integer IDs, no facial or biometric templates.
- Kinematic Analysis: Trajectory history, smoothed velocity vector, and speed.
- Occlusion Recovery: Re-identification of occluded objects within camera field-of-view.
"""

from __future__ import annotations

import collections
import enum
import math
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

try:
    import structlog
except ImportError:
    import logging
    class _FallbackLogger:
        def __init__(self, name: str = "camserv") -> None:
            self._logger = logging.getLogger(name)
        def bind(self, **kwargs: Any) -> _FallbackLogger:
            return self
        def info(self, event: str, **kwargs: Any) -> None:
            self._logger.info(f"{event} {kwargs}" if kwargs else event)
        def warning(self, event: str, **kwargs: Any) -> None:
            self._logger.warning(f"{event} {kwargs}" if kwargs else event)
        def error(self, event: str, **kwargs: Any) -> None:
            self._logger.error(f"{event} {kwargs}" if kwargs else event)
        def debug(self, event: str, **kwargs: Any) -> None:
            self._logger.debug(f"{event} {kwargs}" if kwargs else event)
    class _MockStructlog:
        @staticmethod
        def get_logger(name: str | None = None) -> _FallbackLogger:
            return _FallbackLogger(name or "camserv")
    structlog = _MockStructlog()  # type: ignore[assignment]

from camserv.inference.detector import BoundingBox, Detection
from camserv.tracking.bytetrack import ByteTracker, STrack

logger = structlog.get_logger(__name__)


class CrossCameraMatchingForbiddenError(RuntimeError):
    """Raised when an operation attempts to link or match tracks across camera boundaries."""


class TrackState(str, enum.Enum):
    """Formal lifecycle state machine for object tracks."""

    TENTATIVE = "TENTATIVE"    # Initial detection, hits < min_hits
    CONFIRMED = "CONFIRMED"    # Actively tracked across consecutive frames
    OCCLUDED = "OCCLUDED"      # Temporarily lost/occluded, within recovery window
    EXPIRED = "EXPIRED"        # Exceeded lost window, removed from active tracking


@dataclass(slots=True)
class EnhancedTrack:
    """Production track representation with kinematics and strict privacy properties."""

    track_id: int
    camera_id: str
    class_name: str
    class_id: int
    bbox: BoundingBox
    confidence: float
    state: TrackState
    hits: int
    age: int
    lost_frames: int
    trajectory: list[tuple[float, float]] = field(default_factory=list)
    velocity: tuple[float, float] = (0.0, 0.0)  # (vx, vy) in pixels/sec
    speed: float = 0.0                          # Euclidean speed in pixels/sec
    last_seen_timestamp: float = field(default_factory=time.monotonic)
    is_prediction: bool = True                  # Non-biometric prediction, never ground truth

    @property
    def qualified_id(self) -> str:
        """Globally unambiguous scoped identifier (e.g. 'cam-01:42')."""
        return f"{self.camera_id}:{self.track_id}"


class CameraTracker:
    """Isolated single-camera tracking coordinator with kinematic trajectory analysis."""

    def __init__(
        self,
        camera_id: str,
        track_thresh: float = 0.5,
        match_thresh: float = 0.7,
        max_age: int = 30,
        min_hits: int = 3,
        trajectory_maxlen: int = 50,
    ) -> None:
        self.camera_id = camera_id
        self.min_hits = min_hits
        self.max_age = max_age
        self.trajectory_maxlen = trajectory_maxlen
        self._tracker = ByteTracker(
            track_thresh=track_thresh,
            match_thresh=match_thresh,
            max_age=max_age,
            min_hits=1,  # We manage TENTATIVE vs CONFIRMED here
        )
        self._trajectories: dict[int, collections.deque[tuple[float, float, float]]] = {}
        self._active_enhanced_tracks: dict[int, EnhancedTrack] = {}
        self._log = logger.bind(component="camera_tracker", camera_id=camera_id)

    def update(
        self,
        detections: Sequence[Detection],
        frame_time: float | None = None,
    ) -> list[EnhancedTrack]:
        """Update tracker with frame detections and compute kinematics."""
        t_now = frame_time or time.monotonic()

        # 1. Prepare inputs for ByteTracker
        if detections:
            bboxes = np.array([list(d.bbox) for d in detections], dtype=np.float64)
            confs = np.array([d.confidence for d in detections], dtype=np.float64)
            class_names = [d.class_name for d in detections]
            class_ids = [d.class_id for d in detections]
        else:
            bboxes = np.empty((0, 4), dtype=np.float64)
            confs = np.empty((0,), dtype=np.float64)
            class_names = []
            class_ids = []

        # 2. Advance ByteTracker
        tracked_stracks = self._tracker.update(bboxes, confs, class_names=class_names)

        current_active_ids = set()
        enhanced_results: list[EnhancedTrack] = []

        for st in tracked_stracks:
            tid = st.track_id
            current_active_ids.add(tid)
            x1, y1, x2, y2 = st.bbox
            bbox = BoundingBox(float(x1), float(y1), float(x2), float(y2))
            cx, cy = bbox.center

            # Maintain trajectory
            if tid not in self._trajectories:
                self._trajectories[tid] = collections.deque(maxlen=self.trajectory_maxlen)
            self._trajectories[tid].append((cx, cy, t_now))

            # Compute velocity & speed from recent trajectory points
            vx, vy, speed = self._calculate_velocity(self._trajectories[tid])

            # Determine state
            if st.hits < self.min_hits:
                state = TrackState.TENTATIVE
            else:
                state = TrackState.CONFIRMED

            # Map class
            c_name = st.class_name or "person"
            c_id = 0

            et = EnhancedTrack(
                track_id=tid,
                camera_id=self.camera_id,
                class_name=c_name,
                class_id=c_id,
                bbox=bbox,
                confidence=st.confidence,
                state=state,
                hits=st.hits,
                age=st.age,
                lost_frames=st.time_since_update,
                trajectory=[(x, y) for (x, y, _) in self._trajectories[tid]],
                velocity=(vx, vy),
                speed=speed,
                last_seen_timestamp=t_now,
            )
            self._active_enhanced_tracks[tid] = et
            enhanced_results.append(et)

        # 3. Handle occluded/lost tracks
        lost_tracks = getattr(self._tracker, "_lost", [])
        for lost_st in lost_tracks:
            tid = lost_st.track_id
            if tid in self._active_enhanced_tracks:
                existing = self._active_enhanced_tracks[tid]
                x1, y1, x2, y2 = lost_st.bbox
                occluded_track = EnhancedTrack(
                    track_id=tid,
                    camera_id=self.camera_id,
                    class_name=existing.class_name,
                    class_id=existing.class_id,
                    bbox=BoundingBox(float(x1), float(y1), float(x2), float(y2)),
                    confidence=existing.confidence * 0.8,  # Degrade confidence during occlusion
                    state=TrackState.OCCLUDED,
                    hits=existing.hits,
                    age=lost_st.age,
                    lost_frames=lost_st.time_since_update,
                    trajectory=existing.trajectory,
                    velocity=existing.velocity,
                    speed=existing.speed * 0.5,
                    last_seen_timestamp=existing.last_seen_timestamp,
                )
                self._active_enhanced_tracks[tid] = occluded_track
                enhanced_results.append(occluded_track)

        # 4. Clean up purged trajectories
        active_ids = {st.track_id for st in tracked_stracks}.union({st.track_id for st in lost_tracks})
        dead_ids = set(self._trajectories.keys()) - active_ids
        for dead_id in dead_ids:
            self._trajectories.pop(dead_id, None)
            self._active_enhanced_tracks.pop(dead_id, None)

        return enhanced_results

    def _calculate_velocity(
        self, traj: collections.deque[tuple[float, float, float]]
    ) -> tuple[float, float, float]:
        """Calculate smoothed velocity vector (pixels/sec) and scalar speed."""
        if len(traj) < 2:
            return 0.0, 0.0, 0.0

        # Sample over last few points
        pts = list(traj)
        p_latest = pts[-1]
        # Look back up to 5 points
        p_earlier = pts[-min(5, len(pts))]

        dt = p_latest[2] - p_earlier[2]
        if dt <= 1e-4:
            return 0.0, 0.0, 0.0

        dx = p_latest[0] - p_earlier[0]
        dy = p_latest[1] - p_earlier[1]

        vx = dx / dt
        vy = dy / dt
        speed = math.hypot(vx, vy)
        return float(vx), float(vy), float(speed)


class MultiCameraTrackingCoordinator:
    """Strictly partitioned multi-camera tracker coordinator ensuring zero cross-camera identity linkage."""

    def __init__(self) -> None:
        self._camera_trackers: dict[str, CameraTracker] = {}

    def get_or_create_tracker(self, camera_id: str) -> CameraTracker:
        """Retrieve or instantiate an isolated CameraTracker for a given stream."""
        if camera_id not in self._camera_trackers:
            self._camera_trackers[camera_id] = CameraTracker(camera_id=camera_id)
        return self._camera_trackers[camera_id]

    def update(self, camera_id: str, detections: Sequence[Detection]) -> list[EnhancedTrack]:
        """Dispatch detections exclusively to the camera's isolated tracking engine."""
        tracker = self.get_or_create_tracker(camera_id)
        return tracker.update(detections)

    def correlate_cross_camera(self, camera_a: str, camera_b: str, track_a: int, track_b: int) -> None:
        """Explicitly rejected operation to prevent illegal cross-camera biometric tracking."""
        raise CrossCameraMatchingForbiddenError(
            f"Cross-camera correlation between camera '{camera_a}' and '{camera_b}' is strictly prohibited. "
            f"CAMserv enforces non-biometric anonymous perimeter tracking by design (GDPR Art. 9)."
        )

    def get_active_track_count(self) -> dict[str, int]:
        """Return count of active confirmed tracks per camera."""
        return {
            cid: len(t._active_enhanced_tracks)
            for cid, t in self._camera_trackers.items()
        }
