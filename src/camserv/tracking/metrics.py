"""Tracking quality metrics.

Provides standard multi-object tracking evaluation metrics:

- **MOTA** — Multi-Object Tracking Accuracy
- **MOTP** — Multi-Object Tracking Precision
- **ID switches** — identity swap events
- **Fragmentations** — track continuity breaks
- **Track lifetime statistics** — min, max, mean duration per track

All metrics are computed incrementally so they can be reported in real time
alongside the tracking pipeline.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog

__all__ = ["TrackingMetrics"]

logger = structlog.get_logger(__name__)


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    """Compute IoU between two ``[x1, y1, x2, y2]`` boxes."""
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - inter
    return inter / max(union, 1e-6)


@dataclass
class _PerClassAccumulator:
    """Per-class statistics accumulator."""

    gt_count: int = 0
    det_count: int = 0
    matches: int = 0
    misses: int = 0
    false_positives: int = 0
    id_switches: int = 0
    total_iou: float = 0.0


@dataclass
class TrackingMetrics:
    """Incremental multi-object tracking metrics.

    Call :meth:`update` once per frame with ground-truth and predicted
    bounding boxes / IDs to accumulate statistics.  Call the various
    property accessors (e.g. :attr:`mota`, :attr:`motp`) to query current
    values at any time.

    Attributes
    ----------
    id_switch_count:
        Total ID switches observed so far.
    fragmentation_count:
        Total fragmentations observed so far.
    """

    # Frame-level accumulators
    _total_gt: int = field(default=0, init=False, repr=False)
    _total_matches: int = field(default=0, init=False, repr=False)
    _total_misses: int = field(default=0, init=False, repr=False)
    _total_fp: int = field(default=0, init=False, repr=False)
    _total_iou_sum: float = field(default=0.0, init=False, repr=False)

    id_switch_count: int = field(default=0, init=False)
    fragmentation_count: int = field(default=0, init=False)

    # Per-GT mapping: gt_id → last matched track_id
    _prev_mapping: dict[int, int] = field(default_factory=dict, init=False, repr=False)

    # Track lifetime bookkeeping: track_id → list of frame indices
    _track_frames: dict[int, list[int]] = field(
        default_factory=lambda: defaultdict(list), init=False, repr=False
    )

    # Per-class tracking
    _per_class: dict[str, _PerClassAccumulator] = field(
        default_factory=lambda: defaultdict(_PerClassAccumulator),
        init=False,
        repr=False,
    )

    _frame_idx: int = field(default=0, init=False, repr=False)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(
        self,
        gt_ids: list[int],
        gt_boxes: np.ndarray,
        pred_ids: list[int],
        pred_boxes: np.ndarray,
        gt_classes: list[str] | None = None,
        pred_classes: list[str] | None = None,
        iou_threshold: float = 0.5,
    ) -> None:
        """Accumulate metrics for one frame.

        Parameters
        ----------
        gt_ids:
            Ground-truth object identifiers.
        gt_boxes:
            ``(G, 4)`` ground-truth boxes ``[x1, y1, x2, y2]``.
        pred_ids:
            Predicted track identifiers (anonymous integers).
        pred_boxes:
            ``(P, 4)`` predicted boxes ``[x1, y1, x2, y2]``.
        gt_classes:
            Optional per-GT class labels for per-class breakdown.
        pred_classes:
            Optional per-prediction class labels.
        iou_threshold:
            Minimum IoU to consider a match.
        """
        self._frame_idx += 1

        n_gt = len(gt_ids)
        n_pred = len(pred_ids)

        if gt_classes is None:
            gt_classes = ["_all"] * n_gt
        if pred_classes is None:
            pred_classes = ["_all"] * n_pred

        self._total_gt += n_gt

        # Record track lifetimes
        for pid in pred_ids:
            self._track_frames[pid].append(self._frame_idx)

        # ---- Build IoU matrix -----------------------------------------
        if n_gt == 0 or n_pred == 0:
            self._total_fp += n_pred
            self._total_misses += n_gt
            if n_pred == 0:
                for gid in gt_ids:
                    if gid in self._prev_mapping:
                        self.fragmentation_count += 1
                self._prev_mapping = {}
            for cls in gt_classes:
                acc = self._per_class[cls]
                acc.gt_count += 1
                acc.misses += 1
            for cls in pred_classes:
                self._per_class[cls].false_positives += 1
            return

        iou_matrix = np.zeros((n_gt, n_pred), dtype=np.float64)
        for i in range(n_gt):
            for j in range(n_pred):
                iou_matrix[i, j] = _iou(gt_boxes[i], pred_boxes[j])

        # ---- Greedy matching (Hungarian could be used too) ------------
        from scipy.optimize import linear_sum_assignment

        cost = 1.0 - iou_matrix
        row_idx, col_idx = linear_sum_assignment(cost)

        matched_gt: set[int] = set()
        matched_pred: set[int] = set()
        mapping: dict[int, int] = {}

        for r, c in zip(row_idx, col_idx):
            if iou_matrix[r, c] < iou_threshold:
                continue
            matched_gt.add(r)
            matched_pred.add(c)
            self._total_matches += 1
            self._total_iou_sum += iou_matrix[r, c]

            gt_id = gt_ids[r]
            pred_id = pred_ids[c]
            mapping[gt_id] = pred_id

            cls = gt_classes[r]
            acc = self._per_class[cls]
            acc.gt_count += 1
            acc.matches += 1
            acc.total_iou += iou_matrix[r, c]

            # ID switch detection
            if gt_id in self._prev_mapping and self._prev_mapping[gt_id] != pred_id:
                self.id_switch_count += 1
                acc.id_switches += 1

        # Misses (unmatched GT)
        for i in range(n_gt):
            if i not in matched_gt:
                self._total_misses += 1
                cls = gt_classes[i]
                acc = self._per_class[cls]
                acc.gt_count += 1
                acc.misses += 1

                # Fragmentation: GT was matched last frame but not this one
                gt_id = gt_ids[i]
                if gt_id in self._prev_mapping:
                    self.fragmentation_count += 1

        # False positives (unmatched predictions)
        fp = n_pred - len(matched_pred)
        self._total_fp += fp
        for j in range(n_pred):
            if j not in matched_pred:
                cls = pred_classes[j]
                self._per_class[cls].false_positives += 1

        self._prev_mapping = mapping

    # ------------------------------------------------------------------
    # MOTA / MOTP
    # ------------------------------------------------------------------

    @property
    def mota(self) -> float:
        """Multi-Object Tracking Accuracy.

        ``MOTA = 1 - (misses + false_positives + id_switches) / total_gt``

        Returns 0.0 when no ground-truth objects have been seen.
        """
        if self._total_gt == 0:
            return 0.0
        return 1.0 - (
            (self._total_misses + self._total_fp + self.id_switch_count)
            / self._total_gt
        )

    @property
    def motp(self) -> float:
        """Multi-Object Tracking Precision.

        Average IoU of all matched pairs.  Returns 0.0 when no matches.
        """
        if self._total_matches == 0:
            return 0.0
        return self._total_iou_sum / self._total_matches

    # ------------------------------------------------------------------
    # Track lifetime statistics
    # ------------------------------------------------------------------

    @property
    def track_lifetimes(self) -> dict[str, float]:
        """Return track lifetime stats: avg, min, max duration in frames.

        Returns
        -------
        dict
            ``{"avg": float, "min": int, "max": int, "count": int}``
        """
        if not self._track_frames:
            return {"avg": 0.0, "min": 0, "max": 0, "count": 0}

        durations = []
        for frames in self._track_frames.values():
            if frames:
                durations.append(max(frames) - min(frames) + 1)

        if not durations:
            return {"avg": 0.0, "min": 0, "max": 0, "count": 0}

        return {
            "avg": float(np.mean(durations)),
            "min": int(np.min(durations)),
            "max": int(np.max(durations)),
            "count": len(durations),
        }

    # ------------------------------------------------------------------
    # Per-class accuracy
    # ------------------------------------------------------------------

    def per_class_accuracy(self) -> dict[str, dict[str, Any]]:
        """Return per-class tracking accuracy breakdown.

        Returns
        -------
        dict
            Mapping from class name to a dict with keys:
            ``gt_count, matches, misses, false_positives, id_switches,
            accuracy, precision``.
        """
        result: dict[str, dict[str, Any]] = {}
        for cls, acc in self._per_class.items():
            accuracy = acc.matches / max(acc.gt_count, 1)
            precision = acc.total_iou / max(acc.matches, 1)
            result[cls] = {
                "gt_count": acc.gt_count,
                "matches": acc.matches,
                "misses": acc.misses,
                "false_positives": acc.false_positives,
                "id_switches": acc.id_switches,
                "accuracy": accuracy,
                "precision": precision,
            }
        return result

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Return a comprehensive metrics summary dict.

        Returns
        -------
        dict
            All top-level metrics plus per-class and lifetime breakdowns.
        """
        return {
            "mota": self.mota,
            "motp": self.motp,
            "id_switches": self.id_switch_count,
            "fragmentations": self.fragmentation_count,
            "total_gt": self._total_gt,
            "total_matches": self._total_matches,
            "total_misses": self._total_misses,
            "total_fp": self._total_fp,
            "frames_processed": self._frame_idx,
            "track_lifetimes": self.track_lifetimes,
            "per_class": self.per_class_accuracy(),
        }

    def reset(self) -> None:
        """Reset all accumulated metrics."""
        self._total_gt = 0
        self._total_matches = 0
        self._total_misses = 0
        self._total_fp = 0
        self._total_iou_sum = 0.0
        self.id_switch_count = 0
        self.fragmentation_count = 0
        self._prev_mapping.clear()
        self._track_frames.clear()
        self._per_class.clear()
        self._frame_idx = 0
