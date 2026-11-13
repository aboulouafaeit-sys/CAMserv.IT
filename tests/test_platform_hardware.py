"""Tests for camserv.platform.hardware."""
from __future__ import annotations

import platform
import pytest

from camserv.platform.hardware import GPUCapability, HardwareDetector, HardwareProfile


@pytest.mark.unit
def test_hardware_detector_probe_host() -> None:
    """Test that hardware probing returns a valid HardwareProfile."""
    profile = HardwareDetector.probe_host()
    assert isinstance(profile, HardwareProfile)
    assert profile.os_name == platform.system()
    assert profile.cpu_cores_logical >= 1
    assert profile.cpu_cores_physical >= 1
    assert profile.ram_total_mb > 0
    assert profile.recommended_backend in ("onnx_gpu", "onnx_cpu", "tensorrt")
    assert profile.max_recommended_concurrent_streams >= 1


@pytest.mark.unit
def test_hardware_profile_summary() -> None:
    """Test summary generation from HardwareProfile."""
    profile = HardwareProfile(
        os_name="Linux",
        os_release="6.1.0",
        os_version="#1 SMP",
        cpu_architecture="x86_64",
        cpu_cores_physical=8,
        cpu_cores_logical=16,
        ram_total_mb=32768,
        ram_available_mb=24576,
        gpus=[
            GPUCapability(
                index=0,
                name="NVIDIA RTX A5000",
                memory_total_mb=24576,
                memory_free_mb=20480,
                compute_capability=(8, 6),
                cuda_driver_version="535.129.03",
                is_supported=True,
                recommended_fp16=True,
            )
        ],
        has_cuda=True,
        has_tensorrt=False,
        recommended_backend="onnx_gpu",
        max_recommended_concurrent_streams=16,
    )
    summary = profile.summary()
    assert "Linux" in summary["os"]
    assert "RTX A5000" in summary["primary_gpu"]
    assert summary["recommended_backend"] == "onnx_gpu"
    assert summary["recommended_max_streams"] == 16
