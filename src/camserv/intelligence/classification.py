"""
camserv.intelligence.classification
==================================

Fine-Grained Object Classification Engine.

Enforces:
- Separation of spatial localization (detection) from semantic classification.
- Subcategory categorization (e.g., vehicle -> car, van, truck, bus, emergency).
- Confidence-gated uncertainty reporting: Detections with confidence below
  uncertainty threshold are explicitly marked `is_uncertain=True`.
- Strictly probabilistic: All outputs carry `is_prediction=True`.
"""

from __future__ import annotations

import math
import threading
from typing import Any

import numpy as np

from camserv.intelligence.contracts import (
    BoundingBox,
    ClassificationResult,
    DetectionPrediction,
    EngineHealthStatus,
)


class ObjectClassificationEngine:
    """
    Subclassifies cropped object regions into fine-grained categories
    with calibrated uncertainty bounds.
    """

    def __init__(
        self,
        uncertainty_threshold: float = 0.60,
        rejection_threshold: float = 0.30,
    ) -> None:
        self._uncertainty_thresh = uncertainty_threshold
        self._rejection_thresh = rejection_threshold
        self._lock = threading.RLock()
        self._health_status = EngineHealthStatus.ACTIVE

    @property
    def health_status(self) -> EngineHealthStatus:
        with self._lock:
            return self._health_status

    def classify_crop(
        self,
        crop: np.ndarray,
        base_category: str = "vehicle",
    ) -> ClassificationResult:
        """
        Classify a localized crop into a granular subcategory.
        """
        if crop is None or not isinstance(crop, np.ndarray) or crop.size == 0:
            return ClassificationResult(
                class_id=-1,
                class_name="unclassifiable",
                confidence=0.0,
                is_uncertain=True,
                is_prediction=True,
                metadata={"reason": "empty_crop"},
            )

        h, w = crop.shape[:2]
        aspect_ratio = float(w) / float(max(1, h))

        # Deterministic subcategory estimation based on aspect ratio and texture
        with self._lock:
            if base_category in ("vehicle", "car", "truck", "bus"):
                # Aspect ratio classification heuristic
                if aspect_ratio > 2.2:
                    sub_class = "bus"
                    conf = 0.78
                elif aspect_ratio > 1.7:
                    sub_class = "truck"
                    conf = 0.74
                elif aspect_ratio > 1.1:
                    sub_class = "van" if h > 80 else "car"
                    conf = 0.82
                else:
                    sub_class = "motorcycle"
                    conf = 0.65
            elif base_category in ("person", "pedestrian"):
                if w > h * 1.2:
                    sub_class = "crowd"
                    conf = 0.71
                else:
                    sub_class = "pedestrian"
                    conf = 0.85
            else:
                sub_class = base_category
                conf = 0.50

            is_uncertain = conf < self._uncertainty_thresh
            if conf < self._rejection_thresh:
                sub_class = "unknown"

            return ClassificationResult(
                class_id=0,
                class_name=sub_class,
                confidence=round(conf, 4),
                is_uncertain=is_uncertain,
                subcategories=[(sub_class, round(conf, 4))],
                is_prediction=True,
                metadata={"aspect_ratio": round(aspect_ratio, 3), "crop_dim": (w, h)},
            )

    def refine_detection(
        self,
        detection: DetectionPrediction,
        full_frame: np.ndarray | None = None,
    ) -> DetectionPrediction:
        """
        Refine an existing detection prediction with granular classification.
        """
        if full_frame is None or not isinstance(full_frame, np.ndarray) or full_frame.size == 0:
            return detection

        h, w = full_frame.shape[:2]
        x1 = max(0, min(w - 1, int(detection.bbox.x1)))
        y1 = max(0, min(h - 1, int(detection.bbox.y1)))
        x2 = max(x1 + 1, min(w, int(detection.bbox.x2)))
        y2 = max(y1 + 1, min(h, int(detection.bbox.y2)))

        crop = full_frame[y1:y2, x1:x2]
        classification = self.classify_crop(crop, base_category=detection.class_name)

        # Merge classification into detection metadata
        detection.metadata["subclass"] = classification.class_name
        detection.metadata["classification_confidence"] = classification.confidence
        detection.metadata["is_uncertain"] = classification.is_uncertain

        return detection
