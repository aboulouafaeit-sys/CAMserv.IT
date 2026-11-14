"""
tests/test_image_enhancement.py
===============================

Unit and validation tests for Phase 2E:
- Non-destructive image enhancement pipeline execution.
- LAB CLAHE Luminance Equalization.
- Dynamic Contrast Stretching.
- Bilateral Denoising.
- Pristine evidence immutability guarantee.
- Side-by-side comparison rendering.
"""

from __future__ import annotations

import numpy as np
import pytest

from camserv.acquisition.enhancement import (
    EnhancementManifest,
    ForensicEnhancementPipeline,
)


@pytest.fixture
def low_light_frame():
    """Create a synthetic low-contrast, underexposed frame (intensities between 20 and 60)."""
    np.random.seed(42)
    # 240x320x3 frame with low illumination
    base = np.random.randint(20, 60, (240, 320, 3), dtype=np.uint8)
    # Add a slightly brighter subject
    base[80:160, 100:180] = np.random.randint(45, 75, (80, 80, 3), dtype=np.uint8)
    return base


def test_enhancement_pipeline_increases_contrast_and_preserves_original(low_light_frame):
    """Verify that enhancement increases contrast while preserving original evidence untouched."""
    pipeline = ForensicEnhancementPipeline()

    enhanced, manifest, pristine_orig = pipeline.enhance(
        raw_frame=low_light_frame,
        camera_id="cam-01",
        frame_id=10,
        apply_clahe=True,
        apply_stretch=True,
    )

    # 1. Non-destructive guarantee: pristine_orig must match low_light_frame exactly
    assert np.array_equal(pristine_orig, low_light_frame)

    # 2. Enhanced frame must differ from original
    assert not np.array_equal(enhanced, low_light_frame)

    # 3. Contrast gain must be positive (> 1.0) on underexposed frame
    assert manifest.contrast_gain > 1.0
    assert manifest.contrast_after > manifest.contrast_before
    assert manifest.is_original_preserved is True
    assert "LAB_CLAHE" in manifest.applied_methods
    assert "CONTRAST_STRETCH" in manifest.applied_methods


def test_enhancement_with_bilateral_denoise(low_light_frame):
    """Verify that bilateral denoising executes and records parameters into manifest."""
    pipeline = ForensicEnhancementPipeline()

    enhanced, manifest, pristine_orig = pipeline.enhance(
        raw_frame=low_light_frame,
        apply_clahe=True,
        apply_stretch=False,
        apply_denoise=True,
    )

    assert "BILATERAL_DENOISE" in manifest.applied_methods
    assert "denoise" in manifest.parameters
    assert np.array_equal(pristine_orig, low_light_frame)


def test_side_by_side_comparison_rendering(low_light_frame):
    """Verify side-by-side composite frame geometry and separation."""
    pipeline = ForensicEnhancementPipeline()
    enhanced, manifest, pristine_orig = pipeline.enhance(raw_frame=low_light_frame)

    comparison = pipeline.create_side_by_side_comparison(
        original_frame=pristine_orig,
        enhanced_frame=enhanced,
        manifest=manifest,
    )

    h, w, c = low_light_frame.shape
    # Comparison should be side-by-side with 4px divider: w*2 + 4
    assert comparison.shape == (h, w * 2 + 4, c)
    assert comparison.dtype == np.uint8
