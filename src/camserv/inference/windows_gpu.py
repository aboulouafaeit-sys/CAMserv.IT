"""
camserv.inference.windows_gpu
=============================

Microsoft Windows GPU AI inference acceleration and fallback engine.
Negotiates optimal execution providers (NVIDIA CUDA, Microsoft DirectML, OpenVINO, CPU)
based on hardware discovery and runtime availability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

from camserv.platform.windows.hardware import WindowsHardwareProber

logger = structlog.get_logger(__name__)


class WindowsExecutionProvider(str, Enum):
    CUDA = "CUDAExecutionProvider"
    TENSORRT = "TensorrtExecutionProvider"
    DIRECTML = "DmlExecutionProvider"
    OPENVINO = "OpenVINOExecutionProvider"
    CPU = "CPUExecutionProvider"


@dataclass
class WindowsGpuConfig:
    """Evaluated GPU configuration for Windows 11 inference."""

    primary_provider: WindowsExecutionProvider
    fallback_chain: list[WindowsExecutionProvider]
    gpu_name: str | None
    vram_mb: int
    is_accelerated: bool
    device_id: int = 0
    directx12_supported: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class WindowsInferenceEvaluator:
    """Evaluates physical hardware and Python environment to determine optimal inference pipeline."""

    def __init__(self) -> None:
        self.prober = WindowsHardwareProber()

    def evaluate(self) -> WindowsGpuConfig:
        """Evaluate host platform to select optimal AI provider on Windows 11."""
        gpus = self.prober.probe_gpus()
        has_nvidia = len(gpus) > 0 and "nvidia" in gpus[0].get("name", "").lower()
        gpu_name = gpus[0].get("name") if gpus else None
        vram = gpus[0].get("memory_total_mb", 0) if gpus else 0

        # Query installed onnxruntime providers if present
        installed_providers: list[str] = []
        try:
            import onnxruntime as ort
            installed_providers = ort.get_available_providers()
        except ImportError:
            pass

        # Determine priority chain
        fallback_chain: list[WindowsExecutionProvider] = []

        if "TensorrtExecutionProvider" in installed_providers:
            fallback_chain.append(WindowsExecutionProvider.TENSORRT)
        if "CUDAExecutionProvider" in installed_providers:
            fallback_chain.append(WindowsExecutionProvider.CUDA)
        if "DmlExecutionProvider" in installed_providers:
            fallback_chain.append(WindowsExecutionProvider.DIRECTML)
        if "OpenVINOExecutionProvider" in installed_providers:
            fallback_chain.append(WindowsExecutionProvider.OPENVINO)

        # CPU is always the final resilient fallback
        fallback_chain.append(WindowsExecutionProvider.CPU)

        # Primary selection logic
        if has_nvidia and WindowsExecutionProvider.CUDA in fallback_chain:
            primary = WindowsExecutionProvider.CUDA
            is_accel = True
        elif WindowsExecutionProvider.DIRECTML in fallback_chain:
            primary = WindowsExecutionProvider.DIRECTML
            is_accel = True
        elif has_nvidia:
            # Dedicated GPU exists; DirectML or CUDA runtime recommended
            primary = WindowsExecutionProvider.CPU
            is_accel = False
            logger.info(
                "windows.gpu_available_but_ort_provider_missing",
                gpu=gpu_name,
                note="Install onnxruntime-gpu or onnxruntime-directml to activate acceleration",
            )
        else:
            primary = WindowsExecutionProvider.CPU
            is_accel = False

        return WindowsGpuConfig(
            primary_provider=primary,
            fallback_chain=fallback_chain,
            gpu_name=gpu_name,
            vram_mb=vram,
            is_accelerated=is_accel,
            metadata={
                "installed_providers": installed_providers,
                "gpu_count": len(gpus),
            },
        )
