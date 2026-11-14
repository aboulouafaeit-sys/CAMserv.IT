"""Tests for Cinematic Visual HUD & Contouring (Instance Segmentation & Pose)."""

import numpy as np
import pytest

from camserv.inference.hud_renderer import CinematicHUDRenderer, ThreatVisualState
from camserv.inference.segmentation import (
    COCO_KEYPOINT_NAMES,
    COCO_SKELETON_PAIRS,
    SegmentationEngine,
    SegmentedContour,
    SkeletalPose,
)
from camserv.pipeline.interfaces import BoundingBox, Track, TrackState


@pytest.fixture
def dummy_frame() -> np.ndarray:
    return np.zeros((480, 640, 3), dtype=np.uint8)


@pytest.fixture
def sample_track() -> Track:
    return Track(
        track_id=101,
        bbox=BoundingBox(100.0, 100.0, 200.0, 350.0),
        class_name="person",
        class_id=0,
        confidence=0.92,
        age=30,
        state=TrackState.CONFIRMED,
        camera_id="cam-front",
        velocity=(1.2, 0.4),
        trajectory=[(120.0, 220.0), (130.0, 225.0), (150.0, 225.0)],
    )


def test_synthetic_contour_generation():
    engine = SegmentationEngine()
    bbox = (50.0, 50.0, 150.0, 300.0)
    contour = engine.generate_synthetic_contour(bbox, class_name="person", num_vertices=16)
    assert len(contour) == 16
    for pt in contour:
        assert isinstance(pt, tuple)
        assert len(pt) == 2
        assert 30.0 <= pt[0] <= 170.0
        assert 40.0 <= pt[1] <= 310.0


def test_synthetic_vehicle_contour():
    engine = SegmentationEngine()
    bbox = (100.0, 200.0, 300.0, 300.0)
    contour = engine.generate_synthetic_contour(bbox, class_name="car", num_vertices=16)
    assert len(contour) == 16


def test_segmented_contour_from_mask():
    mask = np.zeros((200, 200), dtype=np.uint8)
    # Draw solid circle in mask
    import cv2
    cv2.circle(mask, (100, 100), 40, 255, -1)
    seg = SegmentedContour.from_mask(mask)
    assert seg is not None
    assert seg.area > 1000.0
    assert 95.0 <= seg.center[0] <= 105.0
    assert 95.0 <= seg.center[1] <= 105.0


def test_skeletal_pose_angles():
    engine = SegmentationEngine()
    bbox = (100.0, 100.0, 200.0, 350.0)
    pose = engine.generate_synthetic_pose(bbox, posture="bending")
    assert pose.valid_count == 17
    # Angle at left hip (5: left_shoulder, 11: left_hip, 13: left_knee)
    angle = pose.calculate_angle(5, 11, 13)
    assert angle is not None
    assert 0.0 < angle < 180.0


def test_hud_threat_styles():
    renderer = CinematicHUDRenderer()

    # Normal State
    style_normal = renderer.get_threat_style(20.0, "normal")
    assert style_normal.ground_ring is True
    assert style_normal.reticle is False
    assert style_normal.skeleton is False
    assert style_normal.color_bgr == renderer.COLOR_CYAN

    # Suspicious State
    style_suspicious = renderer.get_threat_style(55.0, "suspicious")
    assert style_suspicious.ground_ring is False
    assert style_suspicious.skeleton is True
    assert style_suspicious.color_bgr == renderer.COLOR_AMBER

    # Critical State
    style_critical = renderer.get_threat_style(90.0, "critical")
    assert style_critical.reticle is True
    assert style_critical.skeleton is True
    assert style_critical.color_bgr == renderer.COLOR_CRIMSON


def test_render_hud_execution(dummy_frame: np.ndarray, sample_track: Track):
    engine = SegmentationEngine()
    renderer = CinematicHUDRenderer(enable_motion_trails=True)

    # Attach polygon and keypoints to track
    sample_track.polygon = engine.generate_synthetic_contour(sample_track.bbox, "person")
    pose = engine.generate_synthetic_pose(sample_track.bbox, "bending")
    sample_track.keypoints = pose.keypoints
    sample_track.threat_score = 85.0
    sample_track.threat_state = "critical"
    sample_track.metadata["behavior"] = "Fence Intrusion"

    rendered = renderer.render_hud(dummy_frame, [sample_track])
    assert rendered is not None
    assert rendered.shape == dummy_frame.shape
    # Ensure drawing operations modified the black canvas
    assert np.any(rendered > 0)


def test_render_stream_telemetry_hud(dummy_frame: np.ndarray):
    renderer = CinematicHUDRenderer()
    telemetry_canvas = renderer.render_stream_telemetry_hud(
        frame=dummy_frame,
        camera_id="cam-01",
        fps=29.8,
        latency_p50=18.4,
        latency_p95=28.1,
        provider="TensorrtExecutionProvider",
        active_tracks=4,
        health_status="HEALTHY",
    )
    assert telemetry_canvas is not None
    assert telemetry_canvas.shape == dummy_frame.shape
    # Telemetry badge drawn on top-left
    assert np.any(telemetry_canvas[16:90, 16:350] > 0)

