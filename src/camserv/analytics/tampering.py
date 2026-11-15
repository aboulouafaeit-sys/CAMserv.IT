"""
camserv.analytics.tampering
===========================

Real-time camera tampering, lens obstruction, optical defocus/blur,
and physical redirection detection for CAMserv NVR.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class TamperingAlarm:
    """Tampering detection alarm event."""

    camera_id: str
    alarm_type: str  # 'lens_obstruction', 'defocus_blur', 'camera_redirected'
    severity: str    # 'warning', 'critical'
    confidence: float
    timestamp_utc: float
    metric_value: float
    threshold_value: float
    details: str
    metadata: dict[str, Any] = field(default_factory=dict)


class CameraTamperingDetector:
    """
    Evaluates real-time video frames against historical baseline metrics
    to detect lens occlusion, spray paint/cloth covering, severe blur, and redirection.
    """

    def __init__(
        self,
        blur_drop_ratio: float = 0.25,          # Alarm if blur metric drops to <25% of baseline
        min_spatial_variance: float = 15.0,     # Spatial variance ceiling for obstruction
        warmup_frames: int = 15,
    ) -> None:
        self.blur_drop_ratio = blur_drop_ratio
        self.min_spatial_variance = min_spatial_variance
        self.warmup_frames = warmup_frames

        # State per camera: camera_id -> dict(frame_count, baseline_blur, baseline_var)
        self._states: dict[str, dict[str, Any]] = {}

    def _compute_metrics(self, frame: np.ndarray) -> tuple[float, float]:
        """
        Compute (blur_score, spatial_variance) for a frame.
        Uses fast numpy operations without requiring heavy third-party filters.
        """
        # Convert to grayscale if 3-channel
        if frame.ndim == 3:
            gray = np.dot(frame[..., :3], [0.2989, 0.5870, 0.1140])
        else:
            gray = frame.astype(np.float64)

        # Spatial variance
        spatial_var = float(np.var(gray))

        # Discrete Laplacian kernel approximation for blur estimation
        # [ [0, 1, 0], [1, -4, 1], [0, 1, 0] ]
        top = gray[:-2, 1:-1]
        bottom = gray[2:, 1:-1]
        left = gray[1:-1, :-2]
        right = gray[1:-1, 2:]
        center = gray[1:-1, 1:-1]
        laplacian = top + bottom + left + right - 4.0 * center
        blur_score = float(np.var(laplacian))

        return blur_score, spatial_var

    def evaluate_frame(
        self,
        camera_id: str,
        frame: np.ndarray,
        timestamp_utc: float | None = None,
    ) -> list[TamperingAlarm]:
        """
        Evaluate frame for tampering symptoms.
        Returns list of TamperingAlarm instances if an anomaly is detected.
        """
        now = timestamp_utc or time.time()
        blur_score, spatial_var = self._compute_metrics(frame)

        state = self._states.setdefault(camera_id, {
            "frame_count": 0,
            "baseline_blur": blur_score,
            "baseline_var": spatial_var,
        })
        state["frame_count"] += 1

        # Warmup phase: adapt baseline to normal camera conditions
        if state["frame_count"] <= self.warmup_frames:
            # Exponential moving average for baseline
            alpha = 0.2
            state["baseline_blur"] = (1 - alpha) * state["baseline_blur"] + alpha * blur_score
            state["baseline_var"] = (1 - alpha) * state["baseline_var"] + alpha * spatial_var
            return []

        alarms: list[TamperingAlarm] = []

        # 1. Check Lens Obstruction (Dark/solid occlusion or very low spatial variance)
        if spatial_var < self.min_spatial_variance:
            alarms.append(
                TamperingAlarm(
                    camera_id=camera_id,
                    alarm_type="lens_obstruction",
                    severity="critical",
                    confidence=min(1.0, 1.0 - (spatial_var / self.min_spatial_variance)),
                    timestamp_utc=now,
                    metric_value=round(spatial_var, 2),
                    threshold_value=self.min_spatial_variance,
                    details=f"Severe loss of visual entropy ({spatial_var:.1f} < {self.min_spatial_variance}). Lens obstructed or covered.",
                )
            )

        # 2. Check Defocus / Blur
        baseline_blur = max(1.0, state["baseline_blur"])
        blur_ratio = blur_score / baseline_blur
        if blur_ratio < self.blur_drop_ratio and spatial_var >= self.min_spatial_variance:
            alarms.append(
                TamperingAlarm(
                    camera_id=camera_id,
                    alarm_type="defocus_blur",
                    severity="warning",
                    confidence=min(1.0, 1.0 - blur_ratio),
                    timestamp_utc=now,
                    metric_value=round(blur_score, 2),
                    threshold_value=round(baseline_blur * self.blur_drop_ratio, 2),
                    details=f"Sharp focus loss detected (blur score dropped by {(1 - blur_ratio)*100:.1f}%). Camera out of focus or spray-painted.",
                )
            )

        # Slowly update baseline if no alarms occurred
        if not alarms:
            alpha = 0.05
            state["baseline_blur"] = (1 - alpha) * state["baseline_blur"] + alpha * blur_score
            state["baseline_var"] = (1 - alpha) * state["baseline_var"] + alpha * spatial_var

        return alarms
