"""
camserv.storage.isep.bitrate_analyzer
=====================================

Stream Bitrate Analyzer and Scene Complexity Classification Engine.
Measures real-world bitrate, packet arrival rates, resolution, frame rate,
and visual scene complexity across camera streams.
Adheres to Rule 2.1: Never claims H.265 guarantees a fixed compression ratio,
and never fabricates bitrate or encoder control parameters.
"""

from __future__ import annotations

import collections
import time
from typing import Any, Deque

import numpy as np
import structlog

from camserv.storage.isep.models import RecordingCodec, SceneComplexity

logger = structlog.get_logger(__name__)


class StreamBitrateAnalyzer:
    """
    Monitors live video stream packet sizes, timestamps, and pixel variance
    to calculate empirical bitrate metrics and scene activity classifications.
    """

    def __init__(
        self,
        window_seconds: float = 30.0,
        max_samples: int = 600,
    ) -> None:
        self.window_seconds = window_seconds
        self.max_samples = max_samples

        # Per-camera rolling sample buffers: camera_id -> deque of (timestamp, byte_size)
        self._byte_samples: dict[str, Deque[tuple[float, int]]] = {}
        # Per-camera frame interval samples: camera_id -> deque of (timestamp, delta_sec)
        self._fps_samples: dict[str, Deque[tuple[float, float]]] = {}
        # Per-camera scene motion scores: camera_id -> deque of (timestamp, motion_score)
        self._motion_samples: dict[str, Deque[tuple[float, float]]] = {}

        # Last known frame per camera for optical difference analysis
        self._last_frames: dict[str, np.ndarray] = {}
        self._last_frame_times: dict[str, float] = {}

    def record_packet(self, camera_id: str, byte_count: int, timestamp: float | None = None) -> None:
        """Record an incoming compressed stream packet or frame byte chunk."""
        if byte_count <= 0:
            return
        now = timestamp if timestamp is not None else time.time()
        buf = self._byte_samples.setdefault(camera_id, collections.deque(maxlen=self.max_samples))
        buf.append((now, byte_count))

        # Record FPS delta
        last_t = self._last_frame_times.get(camera_id)
        if last_t is not None and now > last_t:
            fps_buf = self._fps_samples.setdefault(camera_id, collections.deque(maxlen=self.max_samples))
            fps_buf.append((now, now - last_t))
        self._last_frame_times[camera_id] = now

        # Prune expired samples
        cutoff = now - self.window_seconds
        while buf and buf[0][0] < cutoff:
            buf.popleft()

    def record_frame_for_scene_analysis(
        self,
        camera_id: str,
        frame: np.ndarray,
        timestamp: float | None = None,
    ) -> SceneComplexity:
        """
        Analyze pixel-level motion and spatial complexity.
        Uses downsampled luminance difference to compute motion metrics without heavy GPU compute.
        """
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            return SceneComplexity.STABLE

        now = timestamp if timestamp is not None else time.time()

        # Convert to grayscale / single channel if 3-channel
        if frame.ndim == 3:
            # Fast downsample and luminance extraction: (R+2G+B)/4
            small = frame[::8, ::8, :]
            gray = (
                small[:, :, 0].astype(np.float32) * 0.299
                + small[:, :, 1].astype(np.float32) * 0.587
                + small[:, :, 2].astype(np.float32) * 0.114
            )
        else:
            gray = frame[::8, ::8].astype(np.float32)

        prev_gray = self._last_frames.get(camera_id)
        motion_score = 0.0

        if prev_gray is not None and prev_gray.shape == gray.shape:
            # Absolute frame difference
            diff = np.abs(gray - prev_gray)
            # Normalized motion energy: average pixel change over range 0..255
            motion_score = float(np.mean(diff) / 255.0)

        self._last_frames[camera_id] = gray

        motion_buf = self._motion_samples.setdefault(camera_id, collections.deque(maxlen=self.max_samples))
        motion_buf.append((now, motion_score))

        cutoff = now - self.window_seconds
        while motion_buf and motion_buf[0][0] < cutoff:
            motion_buf.popleft()

        return self.classify_scene_complexity(camera_id)

    def classify_scene_complexity(self, camera_id: str) -> SceneComplexity:
        """
        Classify current visual activity and scene complexity for a camera.
        Categorized into STABLE, LOW_MOTION, MODERATE, HIGH_MOTION, COMPLEX, or NOISY.
        """
        samples = self._motion_samples.get(camera_id)
        if not samples or len(samples) < 3:
            return SceneComplexity.STABLE

        scores = [s[1] for s in samples]
        avg_motion = float(np.mean(scores))
        std_motion = float(np.std(scores))

        # Check for high-frequency low-amplitude noise (sensor noise / low light)
        if 0.03 <= avg_motion < 0.08 and std_motion < 0.01:
            return SceneComplexity.NOISY_LOW_LIGHT

        if avg_motion < 0.015:
            return SceneComplexity.STABLE
        elif avg_motion < 0.06:
            return SceneComplexity.LOW_MOTION
        elif avg_motion < 0.15:
            return SceneComplexity.MODERATE
        elif avg_motion < 0.35:
            return SceneComplexity.HIGH_MOTION
        else:
            return SceneComplexity.COMPLEX

    def get_stream_metrics(self, camera_id: str) -> dict[str, Any]:
        """
        Compute empirical stream bitrate, effective FPS, and complexity classification.
        Returns measured values strictly; never invents synthetic bitrates.
        """
        samples = self._byte_samples.get(camera_id)
        if not samples or len(samples) < 2:
            return {
                "camera_id": camera_id,
                "has_data": False,
                "measured_bitrate_kbps": 0.0,
                "effective_fps": 0.0,
                "scene_complexity": SceneComplexity.STABLE.value,
                "window_duration_seconds": 0.0,
                "total_bytes_observed": 0,
            }

        total_bytes = sum(s[1] for s in samples)
        time_span = samples[-1][0] - samples[0][0]

        if time_span <= 0.05:
            bitrate_kbps = 0.0
        else:
            # (total_bytes * 8 bits/byte) / (time_span * 1000 bits/kbit)
            bitrate_kbps = (total_bytes * 8.0) / (time_span * 1000.0)

        # Compute effective FPS from delta intervals
        fps_samples = self._fps_samples.get(camera_id)
        if fps_samples and len(fps_samples) > 2:
            avg_delta = float(np.mean([d[1] for d in fps_samples]))
            effective_fps = round(1.0 / avg_delta, 1) if avg_delta > 0.001 else 0.0
        else:
            effective_fps = 0.0

        complexity = self.classify_scene_complexity(camera_id)

        return {
            "camera_id": camera_id,
            "has_data": True,
            "measured_bitrate_kbps": round(bitrate_kbps, 1),
            "effective_fps": effective_fps,
            "scene_complexity": complexity.value,
            "window_duration_seconds": round(time_span, 2),
            "total_bytes_observed": total_bytes,
            "sample_count": len(samples),
        }

    def estimate_storage_growth(
        self,
        camera_id: str,
        hours: float = 24.0,
        codec: RecordingCodec = RecordingCodec.H264,
    ) -> dict[str, Any]:
        """
        Empirical storage growth calculation based on observed bitrate.
        Includes honest notation that codec efficiency varies by vendor and scene content.
        """
        metrics = self.get_stream_metrics(camera_id)
        bitrate_kbps = metrics["measured_bitrate_kbps"]

        # Fallback to standard 1080p profile if no stream data observed yet
        is_estimated = not metrics["has_data"]
        if is_estimated:
            bitrate_kbps = 4096.0  # Conservative 4 Mbps baseline estimate

        bytes_per_second = (bitrate_kbps * 1000.0) / 8.0
        projected_bytes = int(bytes_per_second * (hours * 3600.0))

        return {
            "camera_id": camera_id,
            "is_empirically_measured": not is_estimated,
            "bitrate_kbps": bitrate_kbps,
            "hours": hours,
            "projected_bytes": projected_bytes,
            "projected_mb": round(projected_bytes / (1024 * 1024), 2),
            "projected_gb": round(projected_bytes / (1024 ** 3), 3),
            "disclaimer": "Projection based on current observed motion and bitrate. Real-world consumption fluctuates with scene activity.",
        }
