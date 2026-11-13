"""Tests for Camera-Adaptive Software ISP & Resilient RTSP Ingestion."""

import time
import numpy as np
import pytest

from camserv.acquisition.isp import (
    CameraProcessingTier,
    CameraSoftwareISP,
    ResilientRTSPRingBuffer,
    StreamDiagnostics,
)


@pytest.fixture
def isp() -> CameraSoftwareISP:
    return CameraSoftwareISP()


def test_stream_profiling_tier_classification(isp: CameraSoftwareISP):
    # Tier 3: Low-res, low-fps, low contrast frames
    low_res_frames = [np.full((360, 480, 3), 40, dtype=np.uint8) for _ in range(5)]
    timestamps = [0.0, 0.2, 0.4, 0.6, 0.8]  # ~5 FPS
    diag_tier3 = isp.profile_stream(low_res_frames, timestamps, "cam-cheap-01")
    assert diag_tier3.assigned_tier == CameraProcessingTier.TIER_3_LOW_QUALITY
    assert diag_tier3.requires_clahe is True

    # Tier 1: 4K frames with high contrast and smooth FPS
    hi_res_frames = []
    for i in range(5):
        frame = np.zeros((2160, 3840, 3), dtype=np.uint8)
        frame[500:1600, 500:3000] = 220
        frame[800:1200, 1000:2000] = 40
        hi_res_frames.append(frame)
    timestamps_4k = [0.0, 0.04, 0.08, 0.12, 0.16]  # 25 FPS
    diag_tier1 = isp.profile_stream(hi_res_frames, timestamps_4k, "cam-axis-4k")
    assert diag_tier1.assigned_tier == CameraProcessingTier.TIER_1_PRO
    assert diag_tier1.requires_clahe is False


def test_clahe_enhancement(isp: CameraSoftwareISP):
    # Create dark frame
    dark_frame = np.full((200, 200, 3), 25, dtype=np.uint8)
    # Add subtle pattern
    dark_frame[50:150, 50:150] = 35
    enhanced = isp.apply_clahe_lab(dark_frame)
    assert enhanced.shape == dark_frame.shape
    # CLAHE should expand luminance contrast
    assert np.mean(enhanced) > np.mean(dark_frame)


def test_roi_bilateral_enhancement(isp: CameraSoftwareISP):
    # Noisy frame
    frame = np.random.randint(50, 150, (300, 300, 3), dtype=np.uint8)
    roi_box = (50, 50, 150, 150)
    original_variance = np.var(frame[50:150, 50:150])
    enhanced = isp.enhance_roi(frame.copy(), roi_box)
    filtered_variance = np.var(enhanced[50:150, 50:150])
    # Bilateral smoothing reduces pixel variance while preserving edges
    assert filtered_variance < original_variance


def test_resilient_rtsp_ring_buffer():
    buf = ResilientRTSPRingBuffer(capacity=10)
    valid_frame = np.ones((100, 100, 3), dtype=np.uint8) * 100

    # Push valid frame
    assert buf.push(1, 10.0, valid_frame) is True
    # Push corrupted None frame (packet drop)
    assert buf.push(2, 10.04, None) is True
    # Recovered packet count should increment
    stats = buf.stats
    assert stats["buffered_frames"] == 2
    assert stats["dropped_packets"] == 1
    assert stats["recovered_packets"] == 1

    # Check window query
    window = buf.get_recent_window(seconds=1.0)
    assert len(window) == 2
