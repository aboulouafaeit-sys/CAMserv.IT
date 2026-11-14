"""
tests.test_hardware_diagnostics
================================

Verification of Phase 1E hardware capability discovery, decoder probing,
and explicit diagnostic states (AVAILABLE, ACTIVE, UNAVAILABLE, DEGRADED, UNSUPPORTED).
"""

import pytest

from camserv.platform.hardware import (
    DecoderCapability,
    DiagnosticState,
    GPUCapability,
    HardwareDetector,
    HardwareDiagnostics,
    HardwareProfile,
)


@pytest.mark.unit
def test_diagnostic_states_enumeration() -> None:
    """Verify diagnostic state values conform to required state taxonomy."""
    states = {s.value for s in DiagnosticState}
    expected = {"available", "active", "unavailable", "degraded", "unsupported"}
    assert states == expected


@pytest.mark.unit
def test_hardware_profile_diagnostics_live_host() -> None:
    """Verify probe_host populates structured diagnostics on current machine."""
    profile = HardwareDetector.probe_host()
    diag = profile.diagnostics

    assert isinstance(diag, HardwareDiagnostics)
    assert diag.gpu_state in (
        DiagnosticState.AVAILABLE,
        DiagnosticState.DEGRADED,
        DiagnosticState.UNAVAILABLE,
        DiagnosticState.UNSUPPORTED,
    )
    assert len(diag.decoders) >= 1
    assert any(d.name == "software" and d.state == DiagnosticState.AVAILABLE for d in diag.decoders)
    assert diag.active_decoder in ("nvdec", "dxva2", "vaapi", "software")
    assert diag.active_inference_backend in ("onnx_gpu", "tensorrt", "onnx_cpu")

    summary = profile.summary()
    assert "gpu_diagnostic_state" in summary
    assert "active_decoder" in summary


@pytest.mark.unit
def test_simulated_degraded_gpu_state() -> None:
    """Verify GPU with VRAM < 4000 MB is flagged as DEGRADED."""
    gpu = GPUCapability(
        index=0,
        name="NVIDIA GTX 1050 Ti",
        memory_total_mb=3072,
        memory_free_mb=2500,
        compute_capability=(6, 1),
        cuda_driver_version="535.100",
        state=DiagnosticState.DEGRADED,
    )
    assert gpu.state == DiagnosticState.DEGRADED


@pytest.mark.unit
def test_simulated_unsupported_gpu_state() -> None:
    """Verify legacy GPU (compute capability < 6.0) is flagged as UNSUPPORTED."""
    gpu = GPUCapability(
        index=0,
        name="NVIDIA GeForce GT 730",
        memory_total_mb=2048,
        memory_free_mb=1800,
        compute_capability=(3, 5),
        cuda_driver_version="470.82",
        state=DiagnosticState.UNSUPPORTED,
    )
    assert gpu.state == DiagnosticState.UNSUPPORTED


@pytest.mark.unit
def test_decoder_capability_attributes() -> None:
    """Verify DecoderCapability structures and codecs."""
    dec = DecoderCapability(
        name="nvdec",
        state=DiagnosticState.AVAILABLE,
        supported_codecs=["h264", "hevc", "vp9"],
        details="NVIDIA NVDEC dedicated hardware block",
    )
    assert dec.name == "nvdec"
    assert dec.state == DiagnosticState.AVAILABLE
    assert "hevc" in dec.supported_codecs
