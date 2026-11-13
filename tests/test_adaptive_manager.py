"""Tests for camserv.platform.tiers and camserv.platform.adaptive_manager."""
from __future__ import annotations

import pytest

from camserv.platform.adaptive_manager import (
    AdaptationAction,
    AdaptiveResourceManager,
    ResourceSnapshot,
)
from camserv.platform.hardware import GPUCapability, HardwareProfile
from camserv.platform.tiers import HardwareTier, TierConfiguration, TierPolicyEngine


@pytest.fixture
def low_end_profile() -> HardwareProfile:
    """Simulate an entry-level CPU-only computer (Tier 1)."""
    return HardwareProfile(
        os_name="Windows",
        os_release="10",
        os_version="10.0.19045",
        cpu_architecture="AMD64",
        cpu_cores_physical=2,
        cpu_cores_logical=4,
        ram_total_mb=4096,
        ram_available_mb=1800,
        gpus=[],
        has_cuda=False,
        has_tensorrt=False,
        recommended_backend="onnx_cpu",
        max_recommended_concurrent_streams=2,
    )


@pytest.fixture
def workstation_profile() -> HardwareProfile:
    """Simulate a GPU workstation with dedicated CUDA (Tier 3)."""
    return HardwareProfile(
        os_name="Windows",
        os_release="11",
        os_version="10.0.22631",
        cpu_architecture="AMD64",
        cpu_cores_physical=8,
        cpu_cores_logical=16,
        ram_total_mb=32768,
        ram_available_mb=24000,
        gpus=[
            GPUCapability(
                index=0,
                name="NVIDIA RTX 3060 Laptop GPU",
                memory_total_mb=6144,
                memory_free_mb=5200,
                compute_capability=(8, 6),
                cuda_driver_version="535.100",
                is_supported=True,
                recommended_fp16=True,
            )
        ],
        has_cuda=True,
        has_tensorrt=False,
        recommended_backend="onnx_gpu",
        max_recommended_concurrent_streams=8,
    )


@pytest.mark.unit
def test_tier_resolution_low_end(low_end_profile: HardwareProfile) -> None:
    """Verify that a 4GB RAM CPU machine resolves to Tier 1 Low-End with safe limits."""
    config = TierPolicyEngine.resolve_tier(low_end_profile)
    assert config.tier == HardwareTier.TIER_1_LOW_END
    assert config.target_fps <= 10
    assert config.max_concurrent_streams <= 2
    assert config.inference_backend == "onnx_cpu"
    assert config.enable_int8_quantization is True
    assert config.enable_reid_features is False
    # Privacy safeguard is non-negotiable across every tier
    assert config.enable_privacy_masking is True


@pytest.mark.unit
def test_tier_resolution_workstation(workstation_profile: HardwareProfile) -> None:
    """Verify that a CUDA 6GB GPU machine resolves to Tier 3 Workstation."""
    config = TierPolicyEngine.resolve_tier(workstation_profile)
    assert config.tier == HardwareTier.TIER_3_WORKSTATION
    assert config.target_fps >= 20
    assert config.inference_backend == "onnx_gpu"
    assert config.enable_half_precision is True
    assert config.enable_privacy_masking is True


@pytest.mark.unit
def test_adaptive_resource_manager_throttling_and_recovery() -> None:
    """Test dynamic shedding under memory emergency and subsequent automatic restoration."""
    preset = TierPolicyEngine.get_preset(HardwareTier.TIER_2_STANDARD)
    manager = AdaptiveResourceManager(base_tier_config=preset, cooldown_period_sec=0.0)

    # 1. Normal state
    norm_snap = ResourceSnapshot(
        timestamp=100.0,
        cpu_percent=30.0,
        ram_percent=50.0,
        ram_used_mb=4000,
        ram_available_mb=4000,
    )
    acts_norm = manager.evaluate_pressure(norm_snap)
    assert len(acts_norm) == 0
    assert manager.is_degraded is False

    # 2. Severe memory emergency (>92% RAM)
    emerg_snap = ResourceSnapshot(
        timestamp=105.0,
        cpu_percent=85.0,
        ram_percent=94.0,
        ram_used_mb=7500,
        ram_available_mb=400,
        is_emergency=True,
    )
    acts_emerg = manager.evaluate_pressure(emerg_snap)
    assert len(acts_emerg) == 2
    assert manager.is_degraded is True
    assert manager.current_fps < preset.target_fps
    assert manager.current_resolution == (480, 480)

    # 3. Load subsides (<70% RAM, <65% CPU)
    relief_snap = ResourceSnapshot(
        timestamp=120.0,
        cpu_percent=40.0,
        ram_percent=60.0,
        ram_used_mb=4800,
        ram_available_mb=3200,
        is_emergency=False,
    )
    acts_relief = manager.evaluate_pressure(relief_snap)
    assert len(acts_relief) == 1
    assert acts_relief[0].action_type == "RESTORE_NORMAL"
    assert manager.is_degraded is False
    assert manager.current_fps == preset.target_fps
    assert manager.current_resolution == preset.target_resolution
