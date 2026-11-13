"""ByteTrack multi-object tracker.

Implements the ByteTrack algorithm (Zhang et al., ECCV 2022) which performs
two-stage data association — first matching high-confidence detections, then
low-confidence detections — to recover objects that are partially occluded
or have weak detector responses.

**All track IDs are anonymous incrementing integers.** This module never
infers, stores, or associates real-world identities or biometric PII.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment

try:
    import structlog
    logger = structlog.get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from camserv.pipeline.interfaces import (
    BoundingBox,
    Detection,
    Frame,
    ObjectTracker,
    Track,
    TrackState as PipelineTrackState,
)
from camserv.tracking.kalman import KalmanBoxTracker

__all__ = ["ByteTracker", "STrack", "TrackState"]


# ---------------------------------------------------------------------------
# Helper Awaitable list for dual sync/async compatibility
# ---------------------------------------------------------------------------

class AwaitableList(list):
    """A list that can also be awaited in async contexts."""

    def __await__(self):
        async def _resolve():
            return self

        return _resolve().__await__()


# ---------------------------------------------------------------------------
# Track state machine
# ---------------------------------------------------------------------------

class TrackState(enum.IntEnum):
    """Lifecycle state of a single track."""

    New = 0
    Tracked = 1
    Lost = 2
    Removed = 3


# ---------------------------------------------------------------------------
# Single-track representation
# ---------------------------------------------------------------------------

_next_track_id: int = 0


def _allocate_track_id() -> int:
    """Return the next anonymous track ID (incrementing integer)."""
    global _next_track_id
    _next_track_id += 1
    return _next_track_id


@dataclass
class STrack:
    """Single-track state container.

    Attributes
    ----------
    track_id:
        Anonymous integer identifier — carries no real-world identity.
    bbox:
        Current bounding box ``[x1, y1, x2, y2]``.
    state:
        Current lifecycle state.
    confidence:
        Latest detection confidence that was associated with this track.
    class_name:
        Detected object class (e.g. ``"person"``).
    age:
        Total frames since track creation.
    hits:
        Number of frames with a matched detection.
    time_since_update:
        Consecutive frames without a matched detection.
    is_prediction:
        Always ``True`` — tracking output is a *prediction*, not ground truth.
    """

    track_id: int = field(default_factory=_allocate_track_id)
    bbox: np.ndarray = field(default_factory=lambda: np.zeros(4, dtype=np.float64))
    state: TrackState = TrackState.New
    confidence: float = 0.0
    class_name: str = ""
    age: int = 0
    hits: int = 0
    time_since_update: int = 0
    is_prediction: bool = True  # always True — never treat as fact

    # Internal Kalman filter
    _kalman: KalmanBoxTracker | None = field(default=None, repr=False)

    # Feature vector for appearance matching (BoT-SORT)
    _feature: np.ndarray | None = field(default=None, repr=False)

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def activate(self, bbox: np.ndarray, confidence: float, class_name: str) -> None:
        """Initialise the track with its first detection."""
        self.bbox = bbox.copy().astype(np.float64)
        self.confidence = float(confidence)
        self.class_name = class_name
        self._kalman = KalmanBoxTracker(self.bbox)
        self.state = TrackState.Tracked
        self.hits = 1
        self.age = 1
        self.time_since_update = 0

    def predict(self) -> None:
        """Advance Kalman state by one frame."""
        if self._kalman is not None:
            self.bbox = self._kalman.predict()
            self.age += 1
            self.time_since_update += 1

    def update(self, bbox: np.ndarray, confidence: float) -> None:
        """Update track with a matched detection."""
        if self._kalman is not None:
            self._kalman.update(bbox)
            self.bbox = self._kalman.get_bbox()
        else:
            self.bbox = bbox.copy().astype(np.float64)
        self.confidence = float(confidence)
        self.state = TrackState.Tracked
        self.hits += 1
        self.time_since_update = 0

    def mark_lost(self) -> None:
        """Transition to Lost state."""
        self.state = TrackState.Lost

    def mark_removed(self) -> None:
        """Transition to Removed state."""
        self.state = TrackState.Removed


# ---------------------------------------------------------------------------
# IoU utilities
# ---------------------------------------------------------------------------

def _iou_batch(bboxes_a: np.ndarray, bboxes_b: np.ndarray) -> np.ndarray:
    """Compute pairwise IoU between two sets of bounding boxes.

    Parameters
    ----------
    bboxes_a: (N, 4) array of [x1, y1, x2, y2].
    bboxes_b: (M, 4) array of [x1, y1, x2, y2].

    Returns
    -------
    (N, M) IoU matrix.
    """
    n = bboxes_a.shape[0]
    m = bboxes_b.shape[0]
    if n == 0 or m == 0:
        return np.empty((n, m), dtype=np.float64)

    x1 = np.maximum(bboxes_a[:, 0:1], bboxes_b[:, 0:1].T)
    y1 = np.maximum(bboxes_a[:, 1:2], bboxes_b[:, 1:2].T)
    x2 = np.minimum(bboxes_a[:, 2:3], bboxes_b[:, 2:3].T)
    y2 = np.minimum(bboxes_a[:, 3:4], bboxes_b[:, 3:4].T)

    inter = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)

    area_a = (bboxes_a[:, 2] - bboxes_a[:, 0]) * (bboxes_a[:, 3] - bboxes_a[:, 1])
    area_b = (bboxes_b[:, 2] - bboxes_b[:, 0]) * (bboxes_b[:, 3] - bboxes_b[:, 1])

    union = area_a[:, None] + area_b[None, :] - inter
    return inter / np.maximum(union, 1e-6)


def _linear_assignment(
    cost_matrix: np.ndarray,
    thresh: float,
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Solve the linear assignment problem with a cost threshold.

    Parameters
    ----------
    cost_matrix: (N, M) cost matrix (lower is better).
    thresh: Maximum acceptable cost.

    Returns
    -------
    (matches, unmatched_rows, unmatched_cols)
    """
    if cost_matrix.size == 0:
        return (
            [],
            list(range(cost_matrix.shape[0])),
            list(range(cost_matrix.shape[1])),
        )

    row_idx, col_idx = linear_sum_assignment(cost_matrix)

    matches: list[tuple[int, int]] = []
    unmatched_rows = set(range(cost_matrix.shape[0]))
    unmatched_cols = set(range(cost_matrix.shape[1]))

    for r, c in zip(row_idx, col_idx):
        if cost_matrix[r, c] > thresh:
            continue
        matches.append((r, c))
        unmatched_rows.discard(r)
        unmatched_cols.discard(c)

    return matches, sorted(unmatched_rows), sorted(unmatched_cols)


# ---------------------------------------------------------------------------
# ByteTracker
# ---------------------------------------------------------------------------

@dataclass
class _Detection:
    """Lightweight detection container for internal use."""

    bbox: np.ndarray
    confidence: float
    class_name: str


class ByteTracker:
    """ByteTrack multi-object tracker.

    Implements two-stage association:
    1. **High-confidence** detections are matched to existing tracks via IoU.
    2. **Low-confidence** detections are matched to tracks that remain
       unmatched after the first stage, recovering partially-occluded objects.

    All emitted track IDs are **anonymous incrementing integers** — this
    tracker never infers or stores real-world identities.

    Parameters
    ----------
    track_thresh:
        Confidence threshold dividing high/low detections.
    match_thresh:
        IoU threshold for accepting a match (as a *cost*, i.e. ``1 - IoU``).
    max_age:
        Maximum frames a lost track is kept before removal.
    min_hits:
        Minimum consecutive hits before a track is reported externally.
    track_buffer:
        Number of frames to buffer lost tracks (defaults to *max_age*).
    low_thresh:
        Detections below this confidence are discarded entirely.
    """

    def __init__(
        self,
        track_thresh: float = 0.5,
        match_thresh: float = 0.8,
        max_age: int = 30,
        min_hits: int = 3,
        track_buffer: int | None = None,
        low_thresh: float = 0.1,
    ) -> None:
        self.track_thresh = track_thresh
        self.match_thresh = match_thresh
        self.max_age = max_age
        self.min_hits = min_hits
        self.track_buffer = track_buffer if track_buffer is not None else max_age
        self.low_thresh = low_thresh

        self._tracked: list[STrack] = []
        self._lost: list[STrack] = []
        self._removed: list[STrack] = []

        self.frame_id: int = 0
        self.id_switch_count: int = 0
        self.fragmentation_count: int = 0

        logger.info(
            "bytetracker_init",
            track_thresh=track_thresh,
            match_thresh=match_thresh,
            max_age=max_age,
            min_hits=min_hits,
        )

    # ------------------------------------------------------------------
    # Public API (Dual Sync / Async & Numpy / Pipeline support)
    # ------------------------------------------------------------------

    def update(
        self,
        detections_or_bboxes: list[Detection] | np.ndarray,
        frame_or_confidences: Frame | np.ndarray | None = None,
        class_names: Sequence[str] | None = None,
    ) -> AwaitableList:
        """Process one frame of detections and return active tracks.

        Supports two invocation patterns:
        1. Pipeline Protocol mode:
           ``tracker.update(detections: list[Detection], frame: Frame) -> list[Track]``
        2. Standalone Array mode:
           ``tracker.update(bboxes: np.ndarray, confidences: np.ndarray, ...) -> list[STrack]``

        Returns an ``AwaitableList`` that can either be used directly as a list
        or awaited asynchronously with ``await tracker.update(...)``.
        """
        is_pipeline_mode = isinstance(detections_or_bboxes, list) and (
            len(detections_or_bboxes) == 0
            or isinstance(detections_or_bboxes[0], Detection)
        )

        camera_id = ""
        current_time = datetime.now(timezone.utc)

        if is_pipeline_mode:
            pipeline_dets: list[Detection] = detections_or_bboxes  # type: ignore
            frame_obj: Frame | None = frame_or_confidences if isinstance(frame_or_confidences, Frame) else None

            if frame_obj is not None:
                camera_id = frame_obj.camera_id
                current_time = frame_obj.timestamp

            n_dets = len(pipeline_dets)
            bboxes = np.zeros((n_dets, 4), dtype=np.float64)
            confidences = np.zeros(n_dets, dtype=np.float64)
            c_names = []
            for i, d in enumerate(pipeline_dets):
                bboxes[i] = [d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2]
                confidences[i] = d.confidence
                c_names.append(d.class_name)
            class_names = c_names
        else:
            bboxes = np.asarray(detections_or_bboxes, dtype=np.float64)
            if bboxes.ndim == 1 and len(bboxes) == 0:
                bboxes = np.empty((0, 4), dtype=np.float64)
            confidences = np.asarray(frame_or_confidences, dtype=np.float64) if frame_or_confidences is not None else np.empty(0)

        self.frame_id += 1

        if class_names is None:
            class_names = ["object"] * len(bboxes)

        # ---- Build detection lists ------------------------------------
        dets_high: list[_Detection] = []
        dets_low: list[_Detection] = []

        for i in range(len(bboxes)):
            conf = float(confidences[i])
            if conf < self.low_thresh:
                continue
            d = _Detection(
                bbox=bboxes[i].astype(np.float64),
                confidence=conf,
                class_name=class_names[i],
            )
            if conf >= self.track_thresh:
                dets_high.append(d)
            else:
                dets_low.append(d)

        # ---- Predict existing tracks ----------------------------------
        all_tracks = self._tracked + self._lost
        for t in all_tracks:
            t.predict()

        tracked_stracks = [t for t in self._tracked if t.state == TrackState.Tracked]
        lost_stracks = list(self._lost)

        # ==============================================================
        # STAGE 1: match high-confidence detections to tracked tracks
        # ==============================================================
        matches_1, unmatched_tracks_1, unmatched_dets_1 = self._match(
            tracked_stracks, dets_high, self.match_thresh
        )

        for t_idx, d_idx in matches_1:
            track = tracked_stracks[t_idx]
            det = dets_high[d_idx]
            track.update(det.bbox, det.confidence)

        # ==============================================================
        # STAGE 2: match low-confidence detections to remaining tracks
        # ==============================================================
        remaining_tracks = [tracked_stracks[i] for i in unmatched_tracks_1]
        matches_2, unmatched_tracks_2, _ = self._match(
            remaining_tracks, dets_low, 0.5
        )

        for t_idx, d_idx in matches_2:
            track = remaining_tracks[t_idx]
            det = dets_low[d_idx]
            track.update(det.bbox, det.confidence)

        still_unmatched = [remaining_tracks[i] for i in unmatched_tracks_2]

        # ==============================================================
        # STAGE 3: match unmatched high-conf dets to lost tracks
        # ==============================================================
        unmatched_high_dets = [dets_high[i] for i in unmatched_dets_1]
        matches_3, unmatched_lost, unmatched_dets_final = self._match(
            lost_stracks, unmatched_high_dets, self.match_thresh
        )

        for t_idx, d_idx in matches_3:
            track = lost_stracks[t_idx]
            det = unmatched_high_dets[d_idx]
            track.update(det.bbox, det.confidence)
            self.fragmentation_count += 1

        # ==============================================================
        # Mark lost & removed
        # ==============================================================
        for t in still_unmatched:
            t.mark_lost()
            self.fragmentation_count += 1

        for idx in unmatched_lost:
            track = lost_stracks[idx]
            if track.time_since_update > self.max_age:
                track.mark_removed()

        # ==============================================================
        # Create new tracks from remaining unmatched high-conf dets
        # ==============================================================
        new_tracks: list[STrack] = []
        for idx in unmatched_dets_final:
            det = unmatched_high_dets[idx]
            t = STrack()
            t.activate(det.bbox, det.confidence, det.class_name)
            new_tracks.append(t)

        # ==============================================================
        # Rebuild track pools (deduplicated by track_id)
        # ==============================================================
        tracked_candidates = [
            t
            for t in (tracked_stracks + lost_stracks + new_tracks)
            if t.state == TrackState.Tracked
        ]
        self._tracked = list({t.track_id: t for t in tracked_candidates}.values())

        lost_candidates = [
            t
            for t in (all_tracks + still_unmatched)
            if t.state == TrackState.Lost and t.time_since_update <= self.max_age
        ]
        self._lost = list({t.track_id: t for t in lost_candidates if t.track_id not in {tr.track_id for tr in self._tracked}}.values())

        removed_candidates = [
            t for t in (all_tracks + still_unmatched) if t.state == TrackState.Removed
        ]
        self._removed = list({t.track_id: t for t in (self._removed + removed_candidates)}.values())

        # ---- Return confirmed tracks ---------------------------------
        output_stracks = [
            t
            for t in self._tracked
            if t.hits >= self.min_hits or self.frame_id <= self.min_hits
        ]

        if is_pipeline_mode:
            pipeline_tracks = []
            for s in output_stracks:
                bbox_obj = BoundingBox(
                    x1=float(s.bbox[0]),
                    y1=float(s.bbox[1]),
                    x2=float(s.bbox[2]),
                    y2=float(s.bbox[3]),
                )
                vx, vy = 0.0, 0.0
                if s._kalman is not None:
                    vx = float(s._kalman.x[4, 0])
                    vy = float(s._kalman.x[5, 0])

                p_track = Track(
                    track_id=s.track_id,
                    bbox=bbox_obj,
                    class_name=s.class_name,
                    class_id=0,
                    confidence=s.confidence,
                    age=s.age,
                    state=PipelineTrackState.CONFIRMED if s.hits >= self.min_hits else PipelineTrackState.TENTATIVE,
                    camera_id=camera_id,
                    velocity=(vx, vy),
                    trajectory=[bbox_obj.center],
                    last_seen=current_time,
                    metadata={"is_prediction": True, "anonymous": True},
                )
                pipeline_tracks.append(p_track)
            return AwaitableList(pipeline_tracks)

        return AwaitableList(output_stracks)

    @property
    def active_tracks(self) -> list[Track]:
        """Currently active tracks formatted as pipeline Track dataclasses."""
        results = []
        for s in self._tracked:
            bbox_obj = BoundingBox(
                x1=float(s.bbox[0]),
                y1=float(s.bbox[1]),
                x2=float(s.bbox[2]),
                y2=float(s.bbox[3]),
            )
            results.append(
                Track(
                    track_id=s.track_id,
                    bbox=bbox_obj,
                    class_name=s.class_name,
                    class_id=0,
                    confidence=s.confidence,
                    age=s.age,
                    state=PipelineTrackState.CONFIRMED if s.hits >= self.min_hits else PipelineTrackState.TENTATIVE,
                    camera_id="",
                    velocity=(0.0, 0.0),
                    trajectory=[bbox_obj.center],
                    last_seen=datetime.now(timezone.utc),
                    metadata={"is_prediction": True, "anonymous": True},
                )
            )
        return results

    async def reset(self) -> None:
        """Reset all internal state."""
        self._tracked.clear()
        self._lost.clear()
        self._removed.clear()
        self.frame_id = 0
        self.id_switch_count = 0
        self.fragmentation_count = 0

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _match(
        tracks: list[STrack],
        detections: list[_Detection],
        thresh: float,
    ) -> tuple[list[tuple[int, int]], list[int], list[int]]:
        """Match tracks to detections using IoU cost."""
        if not tracks or not detections:
            return [], list(range(len(tracks))), list(range(len(detections)))

        track_bboxes = np.array([t.bbox for t in tracks], dtype=np.float64)
        det_bboxes = np.array([d.bbox for d in detections], dtype=np.float64)

        iou_matrix = _iou_batch(track_bboxes, det_bboxes)
        cost_matrix = 1.0 - iou_matrix

        return _linear_assignment(cost_matrix, thresh)
