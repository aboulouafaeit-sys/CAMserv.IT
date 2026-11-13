"""BoT-SORT multi-object tracker with camera motion compensation and Re-ID.

Implements the BoT-SORT algorithm (Aharon et al., 2022) which extends ByteTrack with:
1. Camera Motion Compensation (GMC) via optical flow / ECC.
2. Optional appearance feature (Re-ID) embedding integration with EMA updates.
3. Combined IoU + Appearance cost matrix with spatial proximity gating.

**All track IDs are anonymous incrementing integers.** This module never
infers, stores, or associates real-world identities or biometric PII.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

import numpy as np

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
from camserv.tracking.bytetrack import (
    STrack,
    TrackState,
    _allocate_track_id,
    _iou_batch,
    _linear_assignment,
)
from camserv.tracking.kalman import KalmanBoxTracker

__all__ = ["BoTSORTracker", "GMC", "GMCMethod"]


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
# Camera Motion Compensation (GMC)
# ---------------------------------------------------------------------------

class GMCMethod:
    """Supported GMC algorithms."""

    SPARSE_OPTICAL_FLOW = "sparse_optical_flow"
    ORB = "orb"
    ECC = "ecc"
    NONE = "none"


class GMC:
    """Camera Motion Compensation estimator.

    Estimates the 2D affine transformation between consecutive video frames
    to compensate for camera pan/tilt/zoom motion.
    Gracefully falls back to identity transform (no motion) if OpenCV is
    not installed or feature tracking fails.
    """

    def __init__(self, method: str = GMCMethod.SPARSE_OPTICAL_FLOW) -> None:
        self.method = method.lower()
        self.prev_gray: np.ndarray | None = None
        self.prev_keypoints: Any = None
        self.prev_descriptors: Any = None

    def apply(self, frame_img: np.ndarray | None) -> np.ndarray:
        """Estimate 2x3 affine transformation matrix from previous to current frame.

        Parameters
        ----------
        frame_img:
            Current frame image as numpy array (H, W, 3) or (H, W), or None.

        Returns
        -------
        np.ndarray
            2x3 affine transformation matrix [R | t]. Defaults to [I | 0].
        """
        # Default identity affine matrix: [ [1, 0, 0], [0, 1, 0] ]
        identity = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64)

        if frame_img is None or self.method == GMCMethod.NONE:
            return identity

        try:
            import cv2
        except ImportError:
            # OpenCV not available; graceful fallback to identity
            return identity

        try:
            # Convert to grayscale
            if frame_img.ndim == 3 and frame_img.shape[2] == 3:
                curr_gray = cv2.cvtColor(frame_img, cv2.COLOR_BGR2GRAY)
            elif frame_img.ndim == 2:
                curr_gray = frame_img
            else:
                return identity

            if self.prev_gray is None:
                self.prev_gray = curr_gray
                return identity

            H = identity.copy()

            if self.method in (GMCMethod.SPARSE_OPTICAL_FLOW, "optflow"):
                # Good features to track + Lucas-Kanade optical flow
                p0 = cv2.goodFeaturesToTrack(
                    self.prev_gray,
                    maxCorners=1000,
                    qualityLevel=0.01,
                    minDistance=8,
                    blockSize=15,
                )
                if p0 is not None and len(p0) >= 4:
                    p1, status, _ = cv2.calcOpticalFlowPyrLK(
                        self.prev_gray, curr_gray, p0, None
                    )
                    good_p0 = p0[status == 1]
                    good_p1 = p1[status == 1]
                    if len(good_p0) >= 4:
                        M, _ = cv2.estimateAffinePartial2D(
                            good_p0, good_p1, method=cv2.RANSAC
                        )
                        if M is not None:
                            H = M

            elif self.method == GMCMethod.ORB:
                orb = cv2.ORB_create(nfeatures=1000)
                kp1, des1 = orb.detectAndCompute(self.prev_gray, None)
                kp2, des2 = orb.detectAndCompute(curr_gray, None)
                if des1 is not None and des2 is not None and len(des1) >= 4 and len(des2) >= 4:
                    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
                    matches = bf.match(des1, des2)
                    if len(matches) >= 4:
                        pts1 = np.float32([kp1[m.queryIdx].pt for m in matches])
                        pts2 = np.float32([kp2[m.trainIdx].pt for m in matches])
                        M, _ = cv2.estimateAffinePartial2D(pts1, pts2, method=cv2.RANSAC)
                        if M is not None:
                            H = M

            elif self.method == GMCMethod.ECC:
                warp_matrix = np.eye(2, 3, dtype=np.float32)
                criteria = (
                    cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
                    50,
                    0.001,
                )
                _, warp_matrix = cv2.findTransformECC(
                    self.prev_gray,
                    curr_gray,
                    warp_matrix,
                    cv2.MOTION_EUCLIDEAN,
                    criteria,
                )
                H = warp_matrix.astype(np.float64)

            self.prev_gray = curr_gray
            return H

        except Exception as exc:
            logger.debug("gmc_estimation_failed", error=str(exc))
            return identity

    def reset(self) -> None:
        """Reset internal state."""
        self.prev_gray = None
        self.prev_keypoints = None
        self.prev_descriptors = None


# ---------------------------------------------------------------------------
# Cosine distance computation
# ---------------------------------------------------------------------------

def _cosine_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute cosine distance matrix between two sets of feature vectors.

    Parameters
    ----------
    a: (N, D) array of feature vectors.
    b: (M, D) array of feature vectors.

    Returns
    -------
    (N, M) matrix of cosine distances in range [0, 2], lower is more similar.
    """
    if a.size == 0 or b.size == 0:
        return np.empty((a.shape[0], b.shape[0]), dtype=np.float64)

    a_norm = np.linalg.norm(a, axis=1, keepdims=True)
    b_norm = np.linalg.norm(b, axis=1, keepdims=True)

    a_normalized = a / np.maximum(a_norm, 1e-6)
    b_normalized = b / np.maximum(b_norm, 1e-6)

    similarity = np.dot(a_normalized, b_normalized.T)
    # Cosine distance: 1 - cosine similarity
    distance = 1.0 - similarity
    return np.clip(distance, 0.0, 2.0)


# ---------------------------------------------------------------------------
# BoTSORTracker
# ---------------------------------------------------------------------------

class BoTSORTracker:
    """BoT-SORT tracker with Camera Motion Compensation and Re-ID features.

    Parameters
    ----------
    track_thresh:
        Confidence threshold dividing high/low detections (default: 0.5).
    match_thresh:
        Cost threshold for IoU matching (default: 0.8).
    appearance_thresh:
        Maximum cosine distance to allow appearance association (default: 0.25).
    proximity_thresh:
        IoU cost gating threshold: if 1-IoU > proximity_thresh, appearance is gated.
    appearance_weight:
        Weight factor lambda for combined cost: (1 - lambda) * IoU + lambda * App.
    gmc_method:
        Camera motion compensation method ('sparse_optical_flow', 'orb', 'ecc', 'none').
    max_age:
        Maximum frames a lost track is retained before deletion (default: 30).
    min_hits:
        Minimum consecutive hits before track is confirmed (default: 3).
    track_buffer:
        Lost track retention buffer (defaults to max_age).
    low_thresh:
        Detections below this confidence are discarded.
    ema_alpha:
        Exponential moving average weight for updating appearance features.
    """

    def __init__(
        self,
        track_thresh: float = 0.5,
        match_thresh: float = 0.8,
        appearance_thresh: float = 0.25,
        proximity_thresh: float = 0.5,
        appearance_weight: float = 0.5,
        gmc_method: str = GMCMethod.SPARSE_OPTICAL_FLOW,
        max_age: int = 30,
        min_hits: int = 3,
        track_buffer: int | None = None,
        low_thresh: float = 0.1,
        ema_alpha: float = 0.9,
    ) -> None:
        self.track_thresh = track_thresh
        self.match_thresh = match_thresh
        self.appearance_thresh = appearance_thresh
        self.proximity_thresh = proximity_thresh
        self.appearance_weight = appearance_weight
        self.max_age = max_age
        self.min_hits = min_hits
        self.track_buffer = track_buffer if track_buffer is not None else max_age
        self.low_thresh = low_thresh
        self.ema_alpha = ema_alpha

        self.gmc = GMC(method=gmc_method)

        self._tracked: list[STrack] = []
        self._lost: list[STrack] = []
        self._removed: list[STrack] = []

        self.frame_id: int = 0
        self.id_switch_count: int = 0
        self.fragmentation_count: int = 0

        logger.info(
            "botsor_tracker_init",
            track_thresh=track_thresh,
            match_thresh=match_thresh,
            appearance_thresh=appearance_thresh,
            gmc_method=gmc_method,
            max_age=max_age,
        )

    # ------------------------------------------------------------------
    # Motion Compensation
    # ------------------------------------------------------------------

    def _apply_gmc(self, tracks: list[STrack], H: np.ndarray) -> None:
        """Apply affine motion compensation transformation to track Kalman filters."""
        # If H is close to identity, skip
        if np.allclose(H, np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])):
            return

        R = H[:2, :2]
        t = H[:2, 2]

        for track in tracks:
            if track._kalman is not None:
                # Transform center coordinates
                cx, cy = track._kalman.x[0, 0], track._kalman.x[1, 0]
                new_c = R @ np.array([cx, cy]) + t
                track._kalman.x[0, 0] = new_c[0]
                track._kalman.x[1, 0] = new_c[1]
                # Scale covariance appropriately
                track._kalman.P[:2, :2] = R @ track._kalman.P[:2, :2] @ R.T

            # Also update current bbox center
            if len(track.bbox) == 4:
                w = track.bbox[2] - track.bbox[0]
                h = track.bbox[3] - track.bbox[1]
                cx = track.bbox[0] + w / 2.0
                cy = track.bbox[1] + h / 2.0
                new_c = R @ np.array([cx, cy]) + t
                track.bbox[0] = new_c[0] - w / 2.0
                track.bbox[1] = new_c[1] - h / 2.0
                track.bbox[2] = new_c[0] + w / 2.0
                track.bbox[3] = new_c[1] + h / 2.0

    # ------------------------------------------------------------------
    # Cost Matrix with Re-ID Appearance
    # ------------------------------------------------------------------

    def _get_cost_matrix(
        self,
        tracks: list[STrack],
        det_bboxes: np.ndarray,
        det_features: np.ndarray | None,
    ) -> np.ndarray:
        """Compute combined IoU + appearance cost matrix."""
        if not tracks or len(det_bboxes) == 0:
            return np.empty((len(tracks), len(det_bboxes)), dtype=np.float64)

        track_bboxes = np.array([t.bbox for t in tracks], dtype=np.float64)
        iou_mat = _iou_batch(track_bboxes, det_bboxes)
        cost_iou = 1.0 - iou_mat

        # Check if features are available
        has_det_features = det_features is not None and len(det_features) == len(det_bboxes)
        track_features_list = [t._feature for t in tracks]
        has_track_features = any(f is not None for f in track_features_list)

        if not (has_det_features and has_track_features):
            # Graceful fallback: pure IoU cost matrix
            return cost_iou

        # Build track feature matrix
        feat_dim = det_features.shape[1] if det_features is not None else 128
        track_features = np.zeros((len(tracks), feat_dim), dtype=np.float64)
        track_has_feat = np.zeros(len(tracks), dtype=bool)

        for i, f in enumerate(track_features_list):
            if f is not None:
                track_features[i] = f
                track_has_feat[i] = True

        cost_app = _cosine_distance(track_features, det_features)

        # Combine costs
        fused_cost = cost_iou.copy()
        for i in range(len(tracks)):
            if not track_has_feat[i]:
                continue
            for j in range(len(det_bboxes)):
                # Spatial proximity gating:
                # If IoU cost > proximity_thresh or appearance cost > appearance_thresh, gate
                if cost_iou[i, j] > self.proximity_thresh:
                    fused_cost[i, j] = 1.0  # high cost
                elif cost_app[i, j] > self.appearance_thresh:
                    fused_cost[i, j] = 1.0  # appearance mismatch
                else:
                    # Weighted combination
                    w = self.appearance_weight
                    fused_cost[i, j] = (1.0 - w) * cost_iou[i, j] + w * cost_app[i, j]

        return fused_cost

    # ------------------------------------------------------------------
    # Update Method (Dual Sync/Async API)
    # ------------------------------------------------------------------

    def update(
        self,
        detections_or_bboxes: list[Detection] | np.ndarray,
        frame_or_confidences: Frame | np.ndarray | None = None,
        class_names: Sequence[str] | None = None,
        features: np.ndarray | None = None,
    ) -> AwaitableList:
        """Update tracker with new frame detections.

        Supports two invocation patterns:
        1. Pipeline Protocol mode:
           ``tracker.update(detections: list[Detection], frame: Frame) -> list[Track]``
        2. Standalone Array mode:
           ``tracker.update(bboxes: np.ndarray, confidences: np.ndarray, ...) -> list[STrack]``

        Returns an ``AwaitableList`` that can either be used directly as a list
        or awaited asynchronously with ``await tracker.update(...)``.
        """
        # Determine invocation mode
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
                # GMC on frame image
                H = self.gmc.apply(frame_obj.image)
            else:
                H = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64)

            n_dets = len(pipeline_dets)
            bboxes = np.zeros((n_dets, 4), dtype=np.float64)
            confidences = np.zeros(n_dets, dtype=np.float64)
            c_names = []
            extracted_features = []
            has_any_feature = False

            for i, d in enumerate(pipeline_dets):
                bboxes[i] = [d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2]
                confidences[i] = d.confidence
                c_names.append(d.class_name)
                if d.embedding is not None:
                    extracted_features.append(d.embedding)
                    has_any_feature = True
                else:
                    extracted_features.append(None)

            if has_any_feature:
                feat_dim = next(f.shape[0] for f in extracted_features if f is not None)
                feat_array = np.zeros((n_dets, feat_dim), dtype=np.float64)
                for i, f in enumerate(extracted_features):
                    if f is not None:
                        feat_array[i] = f
                features = feat_array
            else:
                features = None

            class_names = c_names

        else:
            # Standalone array mode
            bboxes = np.asarray(detections_or_bboxes, dtype=np.float64)
            if bboxes.ndim == 1 and len(bboxes) == 0:
                bboxes = np.empty((0, 4), dtype=np.float64)
            confidences = np.asarray(frame_or_confidences, dtype=np.float64) if frame_or_confidences is not None else np.empty(0)
            H = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64)

        # -------------------------------------------------------------
        # Core Tracking Logic
        # -------------------------------------------------------------
        self.frame_id += 1

        if class_names is None:
            class_names = ["object"] * len(bboxes)

        # 1. Split high/low confidence detections
        high_indices: list[int] = []
        low_indices: list[int] = []

        for i in range(len(bboxes)):
            c = float(confidences[i])
            if c < self.low_thresh:
                continue
            if c >= self.track_thresh:
                high_indices.append(i)
            else:
                low_indices.append(i)

        dets_high_bbox = bboxes[high_indices]
        dets_high_conf = confidences[high_indices]
        dets_high_names = [class_names[i] for i in high_indices]
        dets_high_feat = features[high_indices] if features is not None and len(features) > 0 else None

        dets_low_bbox = bboxes[low_indices]
        dets_low_conf = confidences[low_indices]

        # 2. Predict existing tracks & apply GMC
        all_tracks = self._tracked + self._lost
        for t in all_tracks:
            t.predict()

        self._apply_gmc(all_tracks, H)

        tracked_tracks = [t for t in self._tracked if t.state == TrackState.Tracked]
        lost_tracks = list(self._lost)

        # 3. Association Stage 1: High-confidence detections
        cost_mat_1 = self._get_cost_matrix(tracked_tracks, dets_high_bbox, dets_high_feat)
        matches_1, unmatched_tracks_1, unmatched_dets_1 = _linear_assignment(
            cost_mat_1, self.match_thresh
        )

        for t_idx, d_idx in matches_1:
            track = tracked_tracks[t_idx]
            track.update(dets_high_bbox[d_idx], float(dets_high_conf[d_idx]))
            # Update feature with EMA
            if dets_high_feat is not None:
                new_f = dets_high_feat[d_idx]
                if track._feature is None:
                    track._feature = new_f.copy()
                else:
                    track._feature = self.ema_alpha * track._feature + (1.0 - self.ema_alpha) * new_f

        # 4. Association Stage 2: Low-confidence detections
        remaining_tracked = [tracked_tracks[i] for i in unmatched_tracks_1]
        if remaining_tracked and len(dets_low_bbox) > 0:
            track_bboxes = np.array([t.bbox for t in remaining_tracked], dtype=np.float64)
            cost_mat_2 = 1.0 - _iou_batch(track_bboxes, dets_low_bbox)
            matches_2, unmatched_tracks_2, _ = _linear_assignment(cost_mat_2, 0.5)

            for t_idx, d_idx in matches_2:
                track = remaining_tracked[t_idx]
                track.update(dets_low_bbox[d_idx], float(dets_low_conf[d_idx]))

            still_unmatched = [remaining_tracked[i] for i in unmatched_tracks_2]
        else:
            still_unmatched = remaining_tracked

        # 5. Association Stage 3: Match unmatched high-confidence detections to lost tracks
        unmatched_high_indices = [unmatched_dets_1[k] for k in range(len(unmatched_dets_1))]
        if lost_tracks and unmatched_high_indices:
            sub_bboxes = dets_high_bbox[unmatched_high_indices]
            sub_feats = dets_high_feat[unmatched_high_indices] if dets_high_feat is not None else None
            cost_mat_3 = self._get_cost_matrix(lost_tracks, sub_bboxes, sub_feats)
            matches_3, unmatched_lost, unmatched_dets_final = _linear_assignment(
                cost_mat_3, self.match_thresh
            )

            for t_idx, d_idx in matches_3:
                track = lost_tracks[t_idx]
                orig_idx = unmatched_high_indices[d_idx]
                track.update(dets_high_bbox[orig_idx], float(dets_high_conf[orig_idx]))
                if dets_high_feat is not None:
                    new_f = dets_high_feat[orig_idx]
                    if track._feature is None:
                        track._feature = new_f.copy()
                    else:
                        track._feature = self.ema_alpha * track._feature + (1.0 - self.ema_alpha) * new_f
                self.fragmentation_count += 1

            new_det_indices = [unmatched_high_indices[i] for i in unmatched_dets_final]
        else:
            unmatched_lost = list(range(len(lost_tracks)))
            new_det_indices = unmatched_high_indices

        # 6. Mark lost & removed
        for t in still_unmatched:
            t.mark_lost()
            self.fragmentation_count += 1

        for idx in unmatched_lost:
            track = lost_tracks[idx]
            if track.time_since_update > self.max_age:
                track.mark_removed()

        # 7. Create new tracks for remaining high-confidence detections
        new_tracks: list[STrack] = []
        for idx in new_det_indices:
            t = STrack()
            t.activate(dets_high_bbox[idx], float(dets_high_conf[idx]), dets_high_names[idx])
            if dets_high_feat is not None:
                t._feature = dets_high_feat[idx].copy()
            new_tracks.append(t)

        # 8. Rebuild track pools
        self._tracked = [
            t
            for t in (tracked_tracks + lost_tracks + new_tracks)
            if t.state == TrackState.Tracked
        ]
        self._lost = [
            t
            for t in (all_tracks + still_unmatched)
            if t.state == TrackState.Lost and t.time_since_update <= self.max_age
        ]
        self._removed.extend(
            t for t in (all_tracks + still_unmatched) if t.state == TrackState.Removed
        )

        # 9. Return confirmed tracks
        confirmed_stracks = [
            t
            for t in self._tracked
            if t.hits >= self.min_hits or self.frame_id <= self.min_hits
        ]

        if is_pipeline_mode:
            # Convert to pipeline Track dataclasses
            pipeline_tracks = []
            for s in confirmed_stracks:
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

        return AwaitableList(confirmed_stracks)

    # ------------------------------------------------------------------
    # Properties & Reset
    # ------------------------------------------------------------------

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
        """Reset all internal tracking state."""
        self._tracked.clear()
        self._lost.clear()
        self._removed.clear()
        self.frame_id = 0
        self.id_switch_count = 0
        self.fragmentation_count = 0
        self.gmc.reset()
