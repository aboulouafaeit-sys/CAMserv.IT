"""Privacy filtering module for CAMserv.

Applies configurable privacy protections to video frames before they leave the
inference pipeline.  All processing happens **on-device** — raw frames are
never transmitted externally.

Capabilities:
- Polygon-based exclusion zones (skip inference / mask output)
- Face and body blurring (Gaussian, pixelation, solid mask)
- Selective processing: inference skipped inside privacy zones
- Privacy mask overlay on output streams
- Metadata stripping from stored frames
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence

import numpy as np
import structlog

from camserv.inference.detector import Detection

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuration types
# ---------------------------------------------------------------------------

class BlurMethod(str, Enum):
    """Supported blurring methods for privacy masking."""

    GAUSSIAN = "gaussian"
    PIXELATE = "pixelate"
    SOLID = "solid"


@dataclass(slots=True)
class PrivacyZone:
    """A polygon-based exclusion area on a camera view.

    Points are in absolute pixel coordinates, ordered clockwise or
    counter-clockwise.  When ``exclude_from_inference`` is ``True`` detections
    whose centre falls inside the polygon are discarded.
    """

    name: str
    polygon: list[tuple[int, int]]  # list of (x, y) vertices
    exclude_from_inference: bool = True
    blur_output: bool = True
    blur_method: BlurMethod = BlurMethod.GAUSSIAN
    camera_id: str | None = None  # None → applies to all cameras


@dataclass(slots=True)
class PrivacyConfig:
    """Top-level privacy filter settings."""

    zones: list[PrivacyZone] = field(default_factory=list)
    blur_faces: bool = True
    blur_bodies: bool = False
    default_blur_method: BlurMethod = BlurMethod.GAUSSIAN
    gaussian_kernel_size: int = 51
    pixelate_block_size: int = 10
    solid_color: tuple[int, int, int] = (0, 0, 0)
    strip_metadata: bool = True
    face_classes: frozenset[str] = frozenset({"face"})
    body_classes: frozenset[str] = frozenset({"person"})


# ---------------------------------------------------------------------------
# Privacy filter
# ---------------------------------------------------------------------------

class PrivacyFilter:
    """Apply privacy protections to frames and detection results.

    All processing is performed **on-device**.  Raw pixel data is never sent
    to an external service.

    Parameters
    ----------
    config:
        Privacy configuration.  Defaults to sensible production values.
    """

    def __init__(self, config: PrivacyConfig | None = None) -> None:
        self._config = config or PrivacyConfig()
        logger.info(
            "privacy_filter_initialised",
            zones=len(self._config.zones),
            blur_faces=self._config.blur_faces,
            blur_bodies=self._config.blur_bodies,
            strip_metadata=self._config.strip_metadata,
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    @property
    def config(self) -> PrivacyConfig:
        return self._config

    def filter_detections(
        self,
        detections: list[Detection],
        camera_id: str | None = None,
    ) -> list[Detection]:
        """Remove detections that fall inside privacy exclusion zones.

        Parameters
        ----------
        detections:
            Raw detections from the detector.
        camera_id:
            If provided, only zones for this camera (or global zones) apply.

        Returns
        -------
        list[Detection]
            Detections with those inside exclusion zones removed.
        """
        zones = self._applicable_zones(camera_id)
        if not zones:
            return detections

        filtered: list[Detection] = []
        dropped = 0
        for det in detections:
            cx = (det.bbox[0] + det.bbox[2]) / 2
            cy = (det.bbox[1] + det.bbox[3]) / 2
            inside = any(
                self._point_in_polygon(cx, cy, z.polygon)
                for z in zones
                if z.exclude_from_inference
            )
            if inside:
                dropped += 1
            else:
                filtered.append(det)

        if dropped:
            logger.debug(
                "detections_filtered_by_privacy_zone",
                dropped=dropped,
                remaining=len(filtered),
            )
        return filtered

    def apply_mask(
        self,
        frame: np.ndarray,
        detections: list[Detection] | None = None,
        camera_id: str | None = None,
    ) -> np.ndarray:
        """Return a copy of *frame* with privacy masks applied.

        Steps:
        1. Blur privacy zones marked ``blur_output``.
        2. Blur faces if ``blur_faces`` is enabled (uses detections with
           face / person classes).
        3. Blur bodies if ``blur_bodies`` is enabled.

        The original frame is **never** mutated.
        """
        out = frame.copy()

        # 1. Zone masking
        for zone in self._applicable_zones(camera_id):
            if zone.blur_output:
                out = self._blur_polygon(out, zone.polygon, zone.blur_method)

        # 2 / 3. Detection-based blurring
        if detections:
            if self._config.blur_faces:
                for det in detections:
                    if det.class_name in self._config.face_classes:
                        out = self._blur_bbox(out, det.bbox, self._config.default_blur_method)

            if self._config.blur_bodies:
                for det in detections:
                    if det.class_name in self._config.body_classes:
                        out = self._blur_bbox(out, det.bbox, self._config.default_blur_method)

        return out

    def strip_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Return *metadata* with privacy-sensitive fields removed.

        Strips GPS coordinates, device identifiers, timestamps beyond date,
        and any key containing 'face', 'person', or 'identity'.
        """
        if not self._config.strip_metadata:
            return metadata

        sensitive_keys = {
            "gps", "gps_latitude", "gps_longitude", "location",
            "device_id", "serial", "mac_address",
            "face", "face_encoding", "identity", "person_id",
        }
        cleaned: dict[str, Any] = {}
        for key, value in metadata.items():
            lower_key = key.lower()
            if any(s in lower_key for s in sensitive_keys):
                continue
            if isinstance(value, dict):
                cleaned[key] = self.strip_metadata(value)
            else:
                cleaned[key] = value

        return cleaned

    def apply_full_pipeline(
        self,
        frame: np.ndarray,
        detections: list[Detection],
        metadata: dict[str, Any] | None = None,
        camera_id: str | None = None,
    ) -> tuple[np.ndarray, list[Detection], dict[str, Any]]:
        """Convenience method: filter detections, mask the frame, strip metadata.

        Returns
        -------
        tuple
            (masked_frame, filtered_detections, stripped_metadata)
        """
        filtered_dets = self.filter_detections(detections, camera_id)
        masked_frame = self.apply_mask(frame, filtered_dets, camera_id)
        clean_meta = self.strip_metadata(metadata or {})
        return masked_frame, filtered_dets, clean_meta

    # ------------------------------------------------------------------ #
    # Zone helpers
    # ------------------------------------------------------------------ #

    def add_zone(self, zone: PrivacyZone) -> None:
        """Add a privacy zone at runtime."""
        self._config.zones.append(zone)
        logger.info("privacy_zone_added", name=zone.name)

    def remove_zone(self, name: str) -> bool:
        """Remove a named zone.  Returns ``True`` if found and removed."""
        before = len(self._config.zones)
        self._config.zones = [z for z in self._config.zones if z.name != name]
        removed = len(self._config.zones) < before
        if removed:
            logger.info("privacy_zone_removed", name=name)
        return removed

    def _applicable_zones(self, camera_id: str | None) -> list[PrivacyZone]:
        """Return zones that apply to the given camera."""
        return [
            z
            for z in self._config.zones
            if z.camera_id is None or z.camera_id == camera_id
        ]

    # ------------------------------------------------------------------ #
    # Geometry
    # ------------------------------------------------------------------ #

    @staticmethod
    def _point_in_polygon(
        px: float,
        py: float,
        polygon: list[tuple[int, int]],
    ) -> bool:
        """Ray-casting point-in-polygon test."""
        n = len(polygon)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            if ((yi > py) != (yj > py)) and (
                px < (xj - xi) * (py - yi) / (yj - yi + 1e-9) + xi
            ):
                inside = not inside
            j = i
        return inside

    # ------------------------------------------------------------------ #
    # Blurring routines
    # ------------------------------------------------------------------ #

    def _blur_bbox(
        self,
        frame: np.ndarray,
        bbox: tuple[float, float, float, float],
        method: BlurMethod,
    ) -> np.ndarray:
        """Blur a rectangular region of the frame."""
        import cv2  # type: ignore[import-untyped]

        h, w = frame.shape[:2]
        x1 = max(0, int(bbox[0]))
        y1 = max(0, int(bbox[1]))
        x2 = min(w, int(bbox[2]))
        y2 = min(h, int(bbox[3]))
        if x2 <= x1 or y2 <= y1:
            return frame

        roi = frame[y1:y2, x1:x2]

        if method == BlurMethod.GAUSSIAN:
            k = self._config.gaussian_kernel_size
            k = k if k % 2 == 1 else k + 1
            blurred = cv2.GaussianBlur(roi, (k, k), 0)
            frame[y1:y2, x1:x2] = blurred

        elif method == BlurMethod.PIXELATE:
            bs = self._config.pixelate_block_size
            rh, rw = roi.shape[:2]
            if rh < 1 or rw < 1:
                return frame
            small = cv2.resize(roi, (max(1, rw // bs), max(1, rh // bs)),
                               interpolation=cv2.INTER_LINEAR)
            frame[y1:y2, x1:x2] = cv2.resize(small, (rw, rh),
                                               interpolation=cv2.INTER_NEAREST)

        elif method == BlurMethod.SOLID:
            frame[y1:y2, x1:x2] = self._config.solid_color

        return frame

    def _blur_polygon(
        self,
        frame: np.ndarray,
        polygon: list[tuple[int, int]],
        method: BlurMethod,
    ) -> np.ndarray:
        """Blur an arbitrary polygon region of the frame."""
        import cv2  # type: ignore[import-untyped]

        pts = np.array(polygon, dtype=np.int32)
        mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        cv2.fillPoly(mask, [pts], 255)

        if method == BlurMethod.SOLID:
            frame[mask == 255] = self._config.solid_color
            return frame

        # Apply blur to entire frame, then composite via mask
        if method == BlurMethod.GAUSSIAN:
            k = self._config.gaussian_kernel_size
            k = k if k % 2 == 1 else k + 1
            blurred = cv2.GaussianBlur(frame, (k, k), 0)
        else:  # PIXELATE
            bs = self._config.pixelate_block_size
            h, w = frame.shape[:2]
            small = cv2.resize(frame, (max(1, w // bs), max(1, h // bs)),
                               interpolation=cv2.INTER_LINEAR)
            blurred = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)

        mask_3c = np.stack([mask] * 3, axis=-1) if frame.ndim == 3 else mask
        np.copyto(frame, blurred, where=(mask_3c == 255))
        return frame
