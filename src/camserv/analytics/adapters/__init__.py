"""
camserv.analytics.adapters
==========================

Pluggable hardware accelerator adapters for CPU, CUDA/TensorRT, OpenVINO,
Google Coral Edge TPU, and Hailo-8 AI processors.
"""

from __future__ import annotations

from camserv.analytics.adapters.base import HardwareAdapterProfile, InferenceBackendAdapter
from camserv.analytics.adapters.coral import CoralEdgeTPUAdapter
from camserv.analytics.adapters.cpu import CPUBackendAdapter
from camserv.analytics.adapters.cuda import CUDABackendAdapter
from camserv.analytics.adapters.hailo import HailoNPUAdapter
from camserv.analytics.adapters.openvino import OpenVINOBackendAdapter


def get_available_adapters() -> list[InferenceBackendAdapter]:
    """Discover and return all supported inference backend adapters on the host."""
    adapters: list[InferenceBackendAdapter] = [
        CPUBackendAdapter(),
        CUDABackendAdapter(),
        OpenVINOBackendAdapter(),
        CoralEdgeTPUAdapter(),
        HailoNPUAdapter(),
    ]
    return adapters


def get_best_available_adapter() -> InferenceBackendAdapter:
    """Return the highest-performance available accelerator, falling back to CPU."""
    adapters = get_available_adapters()
    # Preference: CUDA -> Hailo -> OpenVINO -> Coral -> CPU
    priority = ["nvidia_cuda", "hailo_npu", "intel_openvino", "coral_edgetpu", "onnx_cpu"]
    for pref in priority:
        for ad in adapters:
            if ad.name == pref and ad.is_available():
                return ad
    return CPUBackendAdapter()
