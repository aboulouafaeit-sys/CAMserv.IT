"""Camera-Adaptive Software ISP & Resilient Stream Ingestion for CAMserv.

Provides:
1. Stream Diagnostics Profiler (Camera Fingerprinting into 3 Tiers).
2. Pre-enhancement for Tier 3 / low-quality cameras:
   - CLAHE (Contrast Limited Adaptive Histogram Equalization) on LAB Luminance.
   - ROI-based Bilateral Filtering for edge-preserving noise reduction without full-frame overhead.
   - Super-resolution / sharpness enhancement interface for forensic regions.
3. Resilient RTSP Ring Buffer with corrupt packet fault-tolerance and frame drop compensation.
"""

from __future__ import annotations

import collections
import enum
import time
from dataclasses import dataclass, field
from typing import Any, Deque, Sequence

import cv2
import numpy as np
import structlog

logger = structlog.get_logger(__name__)


class CameraProcessingTier(enum.Enum):
    """Camera processing tier assigned by the Stream Diagnostics Profiler."""
    TIER_1_PRO = "tier_1_professional"         # 4K / High-Bitrate clean stream
    TIER_2_STANDARD = "tier_2_standard"        # 1080p standard commercial stream
    TIER_3_LOW_QUALITY = "tier_3_low_quality"  # Low-light, noisy, high-compression, or unstable


@dataclass(slots=True)
class StreamDiagnostics:
    """Stream metric profiling results over initial diagnostic window."""
    camera_id: str
    width: int
    height: int
    measured_fps: float
    noise_ratio: float
    contrast_score: float
    assigned_tier: CameraProcessingTier
    diagnostic_duration_sec: float
    requires_clahe: bool
    requires_denoise: bool


class CameraSoftwareISP:
    """Software-based Image Signal Processor (ISP) adapting dynamically to camera quality."""

    def __init__(
        self,
        clahe_clip_limit: float = 2.5,
        clahe_tile_grid_size: tuple[int, int] = (8, 8),
        bilateral_diameter: int = 7,
        bilateral_sigma_color: float = 50.0,
        bilateral_sigma_space: float = 50.0,
    ) -> None:
        self.clahe_clip_limit = clahe_clip_limit
        self.clahe_tile_grid_size = clahe_tile_grid_size
        self.bilateral_diameter = bilateral_diameter
        self.bilateral_sigma_color = bilateral_sigma_color
        self.bilateral_sigma_space = bilateral_sigma_space
        self._clahe = cv2.createCLAHE(
            clipLimit=self.clahe_clip_limit,
            tileGridSize=self.clahe_tile_grid_size
        )

    def profile_stream(
        self,
        frames: Sequence[np.ndarray],
        timestamps: Sequence[float],
        camera_id: str = "cam-01"
    ) -> StreamDiagnostics:
        """Analyze initial batch of stream frames to fingerprint camera characteristics."""
        if not frames:
            return StreamDiagnostics(
                camera_id=camera_id,
                width=1920,
                height=1080,
                measured_fps=25.0,
                noise_ratio=0.05,
                contrast_score=60.0,
                assigned_tier=CameraProcessingTier.TIER_2_STANDARD,
                diagnostic_duration_sec=0.0,
                requires_clahe=False,
                requires_denoise=False,
            )

        h, w = frames[0].shape[:2]
        n_frames = len(frames)

        # 1. Measured FPS calculation
        if len(timestamps) > 1:
            duration = max(0.001, timestamps[-1] - timestamps[0])
            fps = float((len(timestamps) - 1) / duration)
        else:
            fps = 25.0
            duration = 1.0

        # 2. Noise & Contrast Profiling across sample frames
        noise_samples = []
        contrast_samples = []
        for img in frames[:min(10, n_frames)]:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
            # Laplacian variance measures high-frequency sharpness / grain
            lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            noise_samples.append(lap_var)
            # Contrast is dynamic standard deviation of pixel intensities
            contrast_samples.append(float(np.std(gray)))

        avg_noise = float(np.mean(noise_samples)) if noise_samples else 0.0
        avg_contrast = float(np.mean(contrast_samples)) if contrast_samples else 50.0

        # 3. Tier Classification Decision Matrix
        # Low resolution (<= 720p), low FPS (<= 15), low contrast (< 35) or heavy noise -> Tier 3
        if w < 1280 or fps < 14.0 or avg_contrast < 38.0 or avg_noise > 450.0:
            tier = CameraProcessingTier.TIER_3_LOW_QUALITY
            requires_clahe = avg_contrast < 45.0
            requires_denoise = avg_noise > 250.0
        elif w >= 2560 and fps >= 24.0 and avg_contrast >= 50.0:
            tier = CameraProcessingTier.TIER_1_PRO
            requires_clahe = False
            requires_denoise = False
        else:
            tier = CameraProcessingTier.TIER_2_STANDARD
            requires_clahe = avg_contrast < 30.0
            requires_denoise = avg_noise > 400.0

        logger.info(
            "camera_isp.stream_profiled",
            camera_id=camera_id,
            tier=tier.value,
            resolution=f"{w}x{h}",
            fps=round(fps, 1),
            contrast=round(avg_contrast, 1),
            noise=round(avg_noise, 1),
        )

        return StreamDiagnostics(
            camera_id=camera_id,
            width=w,
            height=h,
            measured_fps=fps,
            noise_ratio=avg_noise,
            contrast_score=avg_contrast,
            assigned_tier=tier,
            diagnostic_duration_sec=duration,
            requires_clahe=requires_clahe,
            requires_denoise=requires_denoise,
        )

    def enhance_frame(
        self,
        frame: np.ndarray,
        diagnostics: StreamDiagnostics | None = None
    ) -> np.ndarray:
        """Apply pre-inference software enhancement for low-light or degraded streams."""
        if frame is None or frame.size == 0:
            return frame

        # If diagnostics say Tier 1 or no CLAHE required, pass through to save CPU
        if diagnostics and diagnostics.assigned_tier == CameraProcessingTier.TIER_1_PRO:
            return frame

        # Apply CLAHE to Luminance channel in LAB color space
        if diagnostics is None or diagnostics.requires_clahe:
            frame = self.apply_clahe_lab(frame)

        return frame

    def apply_clahe_lab(self, frame: np.ndarray) -> np.ndarray:
        """Enhance local contrast in LAB color space without color distortion."""
        if frame.ndim != 3 or frame.shape[2] != 3:
            return frame
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l_clahe = self._clahe.apply(l)
        enhanced_lab = cv2.merge((l_clahe, a, b))
        return cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)

    def enhance_roi(
        self,
        frame: np.ndarray,
        roi_box: tuple[int, int, int, int]
    ) -> np.ndarray:
        """Apply edge-preserving bilateral filtering strictly to ROI crop to conserve CPU."""
        x1, y1, x2, y2 = roi_box
        h, w = frame.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return frame

        roi = frame[y1:y2, x1:x2]
        filtered_roi = cv2.bilateralFilter(
            roi,
            d=self.bilateral_diameter,
            sigmaColor=self.bilateral_sigma_color,
            sigmaSpace=self.bilateral_sigma_space
        )
        frame[y1:y2, x1:x2] = filtered_roi
        return frame


class ResilientRTSPRingBuffer:
    """In-memory circular ring buffer ensuring stream resilience against corrupted packets."""

    def __init__(self, capacity: int = 150) -> None:
        self.capacity = capacity
        self._buffer: Deque[tuple[int, float, np.ndarray]] = collections.deque(maxlen=capacity)
        self._last_valid_frame: np.ndarray | None = None
        self._dropped_frames_count: int = 0
        self._recovered_frames_count: int = 0

    def push(self, frame_id: int, timestamp: float, frame: np.ndarray | None) -> bool:
        """Push a newly decoded frame into the buffer. Handles corrupted/None frames gracefully."""
        if frame is None or frame.size == 0 or np.all(frame == 0):
            # Corrupted packet or decoder failure
            self._dropped_frames_count += 1
            if self._last_valid_frame is not None:
                # Fill with last known valid frame to prevent downstream pipeline disruption
                self._buffer.append((frame_id, timestamp, self._last_valid_frame.copy()))
                self._recovered_frames_count += 1
                return True
            return False

        self._last_valid_frame = frame
        self._buffer.append((frame_id, timestamp, frame))
        return True

    def get_latest(self) -> tuple[int, float, np.ndarray] | None:
        """Retrieve most recent frame without removing it."""
        if not self._buffer:
            return None
        return self._buffer[-1]

    def get_recent_window(self, seconds: float = 5.0) -> list[tuple[int, float, np.ndarray]]:
        """Retrieve frames spanning the most recent N seconds."""
        if not self._buffer:
            return []
        now = self._buffer[-1][1]
        cutoff = now - seconds
        return [item for item in self._buffer if item[1] >= cutoff]

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "buffered_frames": len(self._buffer),
            "capacity": self.capacity,
            "dropped_packets": self._dropped_frames_count,
            "recovered_packets": self._recovered_frames_count,
        }
