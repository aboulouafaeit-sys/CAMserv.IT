"""
camserv.acquisition.enhancement
===============================

Non-Destructive Forensic Image Enhancement Pipeline and Evidence Preservation for CAMserv.

Features:
- Non-Destructive Invariant: Original raw frame is preserved untouched with SHA-256 digest.
- LAB CLAHE Equalization: Contrast Limited Adaptive Histogram Equalization on luminance only.
- Dynamic Contrast Stretching: Percentile-based normalization avoiding highlight clipping.
- Bilateral Filtering: Edge-preserving noise reduction preventing artifact introduction.
- Forensic Side-by-Side Verification: Generates dual-pane side-by-side comparison for court review.
- Cryptographic EnhancementManifest linking raw and enhanced representations.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import cv2
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
        def critical(self, event: str, **kwargs: Any) -> None:
            self._logger.critical(f"{event} {kwargs}" if kwargs else event)
    class _MockStructlog:
        @staticmethod
        def get_logger(name: str | None = None) -> _FallbackLogger:
            return _FallbackLogger(name or "camserv")
    structlog = _MockStructlog()  # type: ignore[assignment]

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class EnhancementManifest:
    """Cryptographic manifest detailing forensic image processing operations."""

    manifest_id: str
    camera_id: str
    frame_id: int
    timestamp_utc: str
    original_sha256: str
    enhanced_sha256: str
    applied_methods: list[str]
    parameters: dict[str, Any]
    contrast_before: float
    contrast_after: float
    contrast_gain: float
    is_original_preserved: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ForensicEnhancementPipeline:
    """Production non-destructive forensic enhancement pipeline."""

    def __init__(
        self,
        clahe_clip_limit: float = 2.5,
        clahe_tile_grid_size: tuple[int, int] = (8, 8),
        denoise_diameter: int = 7,
        denoise_sigma_color: float = 40.0,
        denoise_sigma_space: float = 40.0,
        stretch_low_percentile: float = 2.0,
        stretch_high_percentile: float = 98.0,
    ) -> None:
        self.clahe_clip_limit = clahe_clip_limit
        self.clahe_tile_grid_size = clahe_tile_grid_size
        self.denoise_diameter = denoise_diameter
        self.denoise_sigma_color = denoise_sigma_color
        self.denoise_sigma_space = denoise_sigma_space
        self.stretch_low_percentile = stretch_low_percentile
        self.stretch_high_percentile = stretch_high_percentile

        self._clahe = cv2.createCLAHE(
            clipLimit=self.clahe_clip_limit,
            tileGridSize=self.clahe_tile_grid_size,
        )
        self._log = logger.bind(component="forensic_enhancement")

    def enhance(
        self,
        raw_frame: np.ndarray,
        camera_id: str = "default",
        frame_id: int = 0,
        apply_clahe: bool = True,
        apply_stretch: bool = True,
        apply_denoise: bool = False,
    ) -> tuple[np.ndarray, EnhancementManifest, np.ndarray]:
        """Apply non-destructive enhancement to raw_frame.

        Returns:
            (enhanced_frame, manifest, pristine_original_frame)
        """
        if raw_frame is None or not isinstance(raw_frame, np.ndarray) or raw_frame.size == 0:
            raise ValueError("Invalid raw frame provided to enhancement pipeline.")

        # 1. Preserve pristine raw frame untouched
        pristine_orig = raw_frame.copy()
        orig_hash = hashlib.sha256(pristine_orig.tobytes()).hexdigest()

        # Measure baseline contrast (standard deviation of gray intensity)
        gray_orig = cv2.cvtColor(pristine_orig, cv2.COLOR_BGR2GRAY) if pristine_orig.ndim == 3 else pristine_orig
        contrast_before = float(np.std(gray_orig))

        # 2. Sequential modular processing
        enhanced = pristine_orig.copy()
        applied: list[str] = []
        params: dict[str, Any] = {}

        # A. Bilateral Denoising (if requested)
        if apply_denoise:
            enhanced = cv2.bilateralFilter(
                enhanced,
                d=self.denoise_diameter,
                sigmaColor=self.denoise_sigma_color,
                sigmaSpace=self.denoise_sigma_space,
            )
            applied.append("BILATERAL_DENOISE")
            params["denoise"] = {
                "d": self.denoise_diameter,
                "sigma_color": self.denoise_sigma_color,
                "sigma_space": self.denoise_sigma_space,
            }

        # B. LAB CLAHE Equalization
        if apply_clahe and enhanced.ndim == 3 and enhanced.shape[2] == 3:
            lab = cv2.cvtColor(enhanced, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            l_eq = self._clahe.apply(l)
            enhanced = cv2.cvtColor(cv2.merge((l_eq, a, b)), cv2.COLOR_LAB2BGR)
            applied.append("LAB_CLAHE")
            params["clahe"] = {
                "clip_limit": self.clahe_clip_limit,
                "tile_grid": self.clahe_tile_grid_size,
            }

        # C. Dynamic Contrast Stretching
        if apply_stretch:
            enhanced = self._stretch_contrast(enhanced)
            applied.append("CONTRAST_STRETCH")
            params["stretch"] = {
                "low_p": self.stretch_low_percentile,
                "high_p": self.stretch_high_percentile,
            }

        # 3. Compute enhanced metrics & manifest
        gray_enhanced = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY) if enhanced.ndim == 3 else enhanced
        contrast_after = float(np.std(gray_enhanced))
        gain = contrast_after / max(0.1, contrast_before)

        enh_hash = hashlib.sha256(enhanced.tobytes()).hexdigest()
        ts_utc = datetime.now(timezone.utc).isoformat()
        manifest_id = f"enh-{camera_id}-{frame_id}-{int(datetime.now(timezone.utc).timestamp()*1000)}"

        manifest = EnhancementManifest(
            manifest_id=manifest_id,
            camera_id=camera_id,
            frame_id=frame_id,
            timestamp_utc=ts_utc,
            original_sha256=orig_hash,
            enhanced_sha256=enh_hash,
            applied_methods=applied,
            parameters=params,
            contrast_before=round(contrast_before, 2),
            contrast_after=round(contrast_after, 2),
            contrast_gain=round(gain, 2),
            is_original_preserved=True,
        )

        return enhanced, manifest, pristine_orig

    def create_side_by_side_comparison(
        self,
        original_frame: np.ndarray,
        enhanced_frame: np.ndarray,
        manifest: EnhancementManifest | None = None,
    ) -> np.ndarray:
        """Render an aligned side-by-side comparison with divider and forensic telemetry."""
        h1, w1 = original_frame.shape[:2]
        h2, w2 = enhanced_frame.shape[:2]

        # Normalize dimensions if necessary
        target_h = max(h1, h2)
        target_w = max(w1, w2)

        f1 = cv2.resize(original_frame, (target_w, target_h)) if (h1, w1) != (target_h, target_w) else original_frame.copy()
        f2 = cv2.resize(enhanced_frame, (target_w, target_h)) if (h2, w2) != (target_h, target_w) else enhanced_frame.copy()

        # Add visual badges
        cv2.rectangle(f1, (10, 10), (220, 45), (20, 20, 20), -1)
        cv2.putText(f1, "ORIGINAL (EVIDENCE)", (15, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)

        gain_text = f"ENHANCED (+{int(manifest.contrast_gain*100 - 100)}% Contrast)" if manifest else "ENHANCED (CLAHE)"
        cv2.rectangle(f2, (10, 10), (280, 45), (20, 20, 20), -1)
        cv2.putText(f2, gain_text, (15, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 255), 2)

        # 4-pixel vertical separator
        divider = np.full((target_h, 4, 3), 100, dtype=np.uint8)

        # Concatenate horizontally
        comparison = np.hstack([f1, divider, f2])
        return comparison

    def _stretch_contrast(self, img: np.ndarray) -> np.ndarray:
        """Expand dynamic range by mapping low/high percentiles to [0, 255]."""
        p_low = np.percentile(img, self.stretch_low_percentile)
        p_high = np.percentile(img, self.stretch_high_percentile)

        if p_high <= p_low:
            return img

        # Linear normalization
        stretched = np.clip((img.astype(np.float32) - p_low) * (255.0 / (p_high - p_low)), 0, 255).astype(np.uint8)
        return stretched
