"""Cinematic Visual HUD & Contouring Renderer for CAMserv.

Replaces traditional rigid bounding boxes with a three-layer visual rendering system:
1. Precise instance segmentation polygon contours with 15% alpha tint.
2. Dynamic security state threat auras:
   - Normal (Safe): Subtle cyan aura + 3D Ground Elliptical Ring under feet.
   - Suspicious (Warning): Pulsing amber aura + fading motion trail.
   - Critical Threat: Glowing crimson aura + target lock-on reticle + glassmorphic card.
3. Skeletal Pose Overlay connecting 17 body keypoints for behavioral inspection.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import cv2
import numpy as np

from camserv.inference.segmentation import (
    COCO_KEYPOINT_NAMES,
    COCO_SKELETON_PAIRS,
    SkeletalPose,
)
from camserv.pipeline.interfaces import Track


@dataclass(slots=True)
class ThreatVisualState:
    """Styling parameters corresponding to the object's security threat level."""
    color_bgr: tuple[int, int, int]
    glow_bgr: tuple[int, int, int]
    fill_alpha: float = 0.15
    reticle: bool = False
    ground_ring: bool = True
    skeleton: bool = False


class CinematicHUDRenderer:
    """Zero-API, 100% local OpenCV-based HUD and Contouring rendering pipeline."""

    # Colors in BGR order
    COLOR_CYAN = (255, 229, 0)      # #00E5FF (Normal / Safe)
    COLOR_AMBER = (11, 158, 245)    # #F59E0B (Suspicious / Warning)
    COLOR_CRIMSON = (68, 68, 239)   # #EF4444 (Critical Threat)
    COLOR_OBSIDIAN = (29, 15, 10)   # #0A0F1D (Glassmorphic card backdrop)

    def __init__(self, enable_motion_trails: bool = True) -> None:
        self.enable_motion_trails = enable_motion_trails

    def get_threat_style(self, threat_score: float, threat_state: str = "normal") -> ThreatVisualState:
        """Map threat score (0-100) and state to visual styling."""
        if threat_score >= 80.0 or threat_state.lower() in ("critical", "breach", "alarm"):
            return ThreatVisualState(
                color_bgr=self.COLOR_CRIMSON,
                glow_bgr=(100, 100, 255),
                fill_alpha=0.22,
                reticle=True,
                ground_ring=False,
                skeleton=True,
            )
        elif threat_score >= 45.0 or threat_state.lower() in ("suspicious", "warning"):
            return ThreatVisualState(
                color_bgr=self.COLOR_AMBER,
                glow_bgr=(30, 200, 255),
                fill_alpha=0.18,
                reticle=False,
                ground_ring=False,
                skeleton=True,
            )
        else:
            return ThreatVisualState(
                color_bgr=self.COLOR_CYAN,
                glow_bgr=(255, 255, 128),
                fill_alpha=0.12,
                reticle=False,
                ground_ring=True,
                skeleton=False,
            )

    def render_hud(
        self,
        frame: np.ndarray,
        tracks: Sequence[Track],
        timestamp_str: str | None = None
    ) -> np.ndarray:
        """Render complete cinematic visual HUD onto input frame (non-destructive copy)."""
        if frame is None or frame.size == 0:
            return frame

        canvas = frame.copy()
        overlay = canvas.copy()
        h, w = canvas.shape[:2]

        for track in tracks:
            # Determine threat styling
            threat_score = getattr(track, "threat_score", 0.0)
            threat_state = getattr(track, "threat_state", "normal")
            style = self.get_threat_style(threat_score, threat_state)

            bbox = track.bbox
            x1, y1, x2, y2 = int(bbox.x1), int(bbox.y1), int(bbox.x2), int(bbox.y2)

            # 1. Motion Trail (Suspicious / Warning & Critical)
            if self.enable_motion_trails and track.trajectory and len(track.trajectory) > 1:
                self._draw_motion_trail(canvas, track.trajectory, style.color_bgr)

            # 2. Polygon Contour & Soft Glowing Aura
            polygon = getattr(track, "polygon", None)
            if polygon and len(polygon) >= 3:
                pts = np.array(polygon, dtype=np.int32).reshape((-1, 1, 2))
                # Fill transparent tint (~15%)
                cv2.fillPoly(overlay, [pts], style.color_bgr)
                # Outer glow outline
                cv2.polylines(canvas, [pts], True, style.glow_bgr, 3, cv2.LINE_AA)
                cv2.polylines(canvas, [pts], True, style.color_bgr, 1, cv2.LINE_AA)
            else:
                # Rounded fallback box if polygon not provided
                cv2.rectangle(canvas, (x1, y1), (x2, y2), style.color_bgr, 2, cv2.LINE_AA)

            # 3. 3D Ground Elliptical Ring (Normal State)
            if style.ground_ring:
                self._draw_3d_ground_ring(canvas, (x1 + x2) // 2, y2, (x2 - x1) // 2, style.color_bgr)

            # 4. Target Lock-On Reticle (Critical Threat)
            if style.reticle:
                self._draw_lock_reticle(canvas, x1, y1, x2, y2, style.color_bgr)

            # 5. Skeletal Pose Overlay
            keypoints = getattr(track, "keypoints", None)
            if keypoints and style.skeleton:
                self._draw_skeletal_pose(canvas, keypoints, style.color_bgr)

            # 6. Floating Glassmorphic Information Card
            self._draw_glassmorphic_card(canvas, track, style, x1, y1, x2, y2, w, h)

        # Blend the polygon fills with canvas
        cv2.addWeighted(overlay, 0.18, canvas, 0.82, 0, canvas)
        return canvas

    def _draw_3d_ground_ring(
        self,
        img: np.ndarray,
        cx: int,
        cy: int,
        radius_x: int,
        color: tuple[int, int, int]
    ) -> None:
        """Render 3D perspective ellipse at feet ground level."""
        rx = max(12, radius_x)
        ry = max(4, int(rx * 0.35))  # Perspective vertical foreshortening
        cv2.ellipse(img, (cx, cy), (rx, ry), 0, 0, 360, color, 2, cv2.LINE_AA)
        # Inner accent dot
        cv2.circle(img, (cx, cy), 3, color, -1, cv2.LINE_AA)

    def _draw_motion_trail(
        self,
        img: np.ndarray,
        trajectory: list[tuple[float, float]],
        color: tuple[int, int, int]
    ) -> None:
        """Render decaying breadcrumb path behind moving object."""
        n = len(trajectory)
        if n < 2:
            return
        # Draw last 12 points with decaying thickness and alpha
        recent = trajectory[-12:]
        for i in range(1, len(recent)):
            p1 = (int(recent[i - 1][0]), int(recent[i - 1][1]))
            p2 = (int(recent[i][0]), int(recent[i][1]))
            alpha_ratio = i / float(len(recent))
            thickness = max(1, int(3 * alpha_ratio))
            cv2.line(img, p1, p2, color, thickness, cv2.LINE_AA)

    def _draw_lock_reticle(
        self,
        img: np.ndarray,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        color: tuple[int, int, int]
    ) -> None:
        """Render tactical military corner brackets on confirmed threat."""
        arm = max(12, int(min(x2 - x1, y2 - y1) * 0.22))
        t = 2
        # Top-left
        cv2.line(img, (x1, y1), (x1 + arm, y1), color, t, cv2.LINE_AA)
        cv2.line(img, (x1, y1), (x1, y1 + arm), color, t, cv2.LINE_AA)
        # Top-right
        cv2.line(img, (x2, y1), (x2 - arm, y1), color, t, cv2.LINE_AA)
        cv2.line(img, (x2, y1), (x2, y1 + arm), color, t, cv2.LINE_AA)
        # Bottom-left
        cv2.line(img, (x1, y2), (x1 + arm, y2), color, t, cv2.LINE_AA)
        cv2.line(img, (x1, y2), (x1, y2 - arm), color, t, cv2.LINE_AA)
        # Bottom-right
        cv2.line(img, (x2, y2), (x2 - arm, y2), color, t, cv2.LINE_AA)
        cv2.line(img, (x2, y2), (x2, y2 - arm), color, t, cv2.LINE_AA)

    def _draw_skeletal_pose(
        self,
        img: np.ndarray,
        keypoints: list[tuple[float, float, float]],
        color: tuple[int, int, int]
    ) -> None:
        """Draw 17-keypoint skeleton lines and joint dots."""
        # Draw connections
        for idx1, idx2 in COCO_SKELETON_PAIRS:
            if idx1 < len(keypoints) and idx2 < len(keypoints):
                p1, p2 = keypoints[idx1], keypoints[idx2]
                if p1[2] > 0.2 and p2[2] > 0.2:
                    pt1 = (int(p1[0]), int(p1[1]))
                    pt2 = (int(p2[0]), int(p2[1]))
                    cv2.line(img, pt1, pt2, (255, 255, 255), 2, cv2.LINE_AA)

        # Draw joints
        for pt in keypoints:
            if pt[2] > 0.2:
                cv2.circle(img, (int(pt[0]), int(pt[1])), 3, color, -1, cv2.LINE_AA)

    def _draw_glassmorphic_card(
        self,
        img: np.ndarray,
        track: Track,
        style: ThreatVisualState,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        w: int,
        h: int
    ) -> None:
        """Draw floating glassmorphic information card displaying live telemetry."""
        # Compute kinematic speed
        vx, vy = track.velocity
        speed = math.hypot(vx, vy)
        threat_score = getattr(track, "threat_score", 0.0)
        behavior = track.metadata.get("behavior", track.class_name.capitalize())

        label = f"[Threat: {threat_score:.0f}% | {behavior} | Speed: {speed:.1f} m/s]"
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.42
        thickness = 1
        (txt_w, txt_h), _ = cv2.getTextSize(label, font, font_scale, thickness)

        card_x1 = max(10, min(x1, w - txt_w - 24))
        card_y1 = max(txt_h + 16, y1 - 12)
        card_x2 = card_x1 + txt_w + 16
        card_y2 = card_y1 + txt_h + 8

        # Draw dark translucent card background
        card_bg = img[card_y1 - txt_h - 6:card_y2, card_x1:card_x2]
        if card_bg.shape[0] > 0 and card_bg.shape[1] > 0:
            dark_overlay = np.zeros_like(card_bg)
            cv2.addWeighted(card_bg, 0.25, dark_overlay, 0.75, 0, card_bg)
            img[card_y1 - txt_h - 6:card_y2, card_x1:card_x2] = card_bg

        # Card border and text
        cv2.rectangle(img, (card_x1, card_y1 - txt_h - 6), (card_x2, card_y2), style.color_bgr, 1, cv2.LINE_AA)
        cv2.putText(img, label, (card_x1 + 8, card_y1), font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
