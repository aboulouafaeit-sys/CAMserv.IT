"""
tests.test_appliance_hardware
=============================

Comprehensive verification of CAMserv AI Appliance hardware specifications,
profile mapping, capability discovery, workload allocation, and degradation governors.
"""

import pytest

from camserv.platform.appliance import (
    ApplianceCatalog,
    ApplianceCapabilityProfile,
    ApplianceHardwareManager,
    ApplianceProfileType,
    ThermalState,
    ThermalStatus,
)
from camserv.platform.hardware import (
    DiagnosticState,
    GPUCapability,
    HardwareProfile,
)


def test_appliance_catalog_specifications():
    """Verify that all three standard appliance profiles are fully specified."""
    specs = ApplianceCatalog.SPECIFICATIONS
    assert ApplianceProfileType.PROFILE_A_EDGE in specs
    assert ApplianceProfileType.PROFILE_B_PROFESSIONAL in specs
    assert ApplianceProfileType.PROFILE_C_ENTERPRISE in specs

    edge_spec = specs[ApplianceProfileType.PROFILE_A_EDGE]
    assert edge_spec.recommended_stream_range == (1, 4)
    assert edge_spec.power_budget_watts <= 25.0
    assert "software" in edge_spec.video_decoders

    pro_spec = specs[ApplianceProfileType.PROFILE_B_PROFESSIONAL]
    assert pro_spec.recommended_stream_range == (4, 16)
    assert pro_spec.min_ram_gb >= 16

    ent_spec = specs[ApplianceProfileType.PROFILE_C_ENTERPRISE]
    assert ent_spec.recommended_stream_range == (16, 64)
    assert ent_spec.max_stream_ceiling >= 64


def test_appliance_manager_host_probe():
    """Verify that ApplianceHardwareManager correctly discovers and maps host hardware."""
    mgr = ApplianceHardwareManager()
    profile = mgr.profile

    assert isinstance(profile, ApplianceCapabilityProfile)
    assert profile.profile_type in ApplianceProfileType
    assert profile.storage.total_gb > 0
    assert profile.storage.free_gb > 0
    assert profile.thermal.state in (ThermalState.NOMINAL, ThermalState.ELEVATED)

    summary = profile.to_dict()
    assert "profile_type" in summary
    assert "storage_free_gb" in summary
    assert "allocated_streams" in summary


def test_simulated_edge_appliance():
    """Verify classification of a low-power edge host (Profile A)."""
    sim_hw = HardwareProfile(
        os_name="Linux",
        os_release="6.1.0-arm64",
        os_version="Debian 12",
        cpu_architecture="aarch64",
        cpu_cores_physical=4,
        cpu_cores_logical=4,
        ram_total_mb=8192,
        ram_available_mb=6000,
        gpus=[],
        has_cuda=False,
        has_tensorrt=False,
    )
    mgr = ApplianceHardwareManager(hardware_profile=sim_hw)
    assert mgr.profile.profile_type == ApplianceProfileType.PROFILE_A_EDGE

    # Check workload allocation: 3 streams allowed, 8 streams rejected
    admissible, ceiling, msg = mgr.evaluate_workload_allocation(3)
    assert admissible is True
    assert ceiling == 6
    assert mgr.profile.allocated_streams == 3

    admissible_fail, ceiling_fail, msg_fail = mgr.evaluate_workload_allocation(8)
    assert admissible_fail is False
    assert ceiling_fail == 6


def test_simulated_enterprise_appliance():
    """Verify classification of an enterprise multi-GPU server (Profile C)."""
    sim_gpu1 = GPUCapability(
        index=0,
        name="NVIDIA RTX 4090",
        memory_total_mb=24576,
        memory_free_mb=23000,
        compute_capability=(8, 9),
        state=DiagnosticState.AVAILABLE,
    )
    sim_gpu2 = GPUCapability(
        index=1,
        name="NVIDIA RTX 4090",
        memory_total_mb=24576,
        memory_free_mb=23000,
        compute_capability=(8, 9),
        state=DiagnosticState.AVAILABLE,
    )
    sim_hw = HardwareProfile(
        os_name="Linux",
        os_release="6.8.0-amd64",
        os_version="Ubuntu 24.04",
        cpu_architecture="x86_64",
        cpu_cores_physical=32,
        cpu_cores_logical=64,
        ram_total_mb=131072,
        ram_available_mb=120000,
        gpus=[sim_gpu1, sim_gpu2],
        has_cuda=True,
        has_tensorrt=True,
    )
    mgr = ApplianceHardwareManager(hardware_profile=sim_hw)
    assert mgr.profile.profile_type == ApplianceProfileType.PROFILE_C_ENTERPRISE

    admissible, ceiling, msg = mgr.evaluate_workload_allocation(48)
    assert admissible is True
    assert ceiling == 80


def test_thermal_throttling_and_graceful_degradation():
    """Verify workload shedding under elevated thermal pressure."""
    mgr = ApplianceHardwareManager()

    # Test explicit degradation policies (Levels 0 through 3)
    p0 = mgr.apply_graceful_degradation(0)
    assert p0["inference_fps"] == 15
    assert p0["roi_scaling"] == 1.0

    p1 = mgr.apply_graceful_degradation(1)
    assert p1["inference_fps"] == 10

    p2 = mgr.apply_graceful_degradation(2)
    assert p2["inference_fps"] == 5
    assert p2["roi_scaling"] == 0.75

    p3 = mgr.apply_graceful_degradation(3)
    assert p3["inference_fps"] == 0  # Inference suspended, raw preservation only
    assert p3["state"] == "critical_safe"

    # Simulate thermal throttling impact on max admissible streams
    mgr.profile.thermal = ThermalStatus(
        cpu_temp_celsius=88.0,
        gpu_temp_celsius=86.0,
        state=ThermalState.THROTTLED,
    )
    admissible, ceiling, msg = mgr.evaluate_workload_allocation(15)
    # Under throttled state, ceiling is reduced by 40%
    assert ceiling < 20
