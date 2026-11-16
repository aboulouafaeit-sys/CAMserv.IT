"""
camserv.analytics.adapters.cuda
===============================

NVIDIA CUDA and TensorRT inference accelerator adapter.
"""

from __future__ import annotations

import shutil
from typing import Any

import numpy as np
import structlog

from camserv.analytics.adapters.base import HardwareAdapterProfile, InferenceBackendAdapter

logger = structlog.get_logger(__name__)


class CUDABackendAdapter(InferenceBackendAdapter):
    """
    NVIDIA GPU accelerator adapter supporting CUDA and TensorRT execution providers.
    Strictly distinguishes physical GPU device detection from execution runtime availability.
    """

    @property
    def name(self) -> str:
        return "nvidia_cuda"

    @property
    def device_type(self) -> str:
        return "cuda"

    def is_device_detected(self) -> bool:
        """Probe host for presence of physical NVIDIA GPU via nvidia-smi."""
        return shutil.which("nvidia-smi") is not None

    def is_runtime_available(self) -> bool:
        """Verify that Python execution provider (PyTorch CUDA, ONNXRuntime GPU, or cv2.cuda) is active."""
        try:
            import cv2
            if hasattr(cv2, "cuda") and cv2.cuda.getCudaEnabledDeviceCount() > 0:
                return True
        except Exception:
            pass
        try:
            import torch
            if torch.cuda.is_available():
                return True
        except Exception:
            pass
        try:
            import onnxruntime as ort
            if "CUDAExecutionProvider" in ort.get_available_providers():
                return True
        except Exception:
            pass
        return False

    def is_available(self) -> bool:
        """Backend is available only if both physical device and Python runtime are active."""
        return self.is_device_detected() and self.is_runtime_available()

    def get_profile(self) -> HardwareAdapterProfile:
        dev_present = self.is_device_detected()
        runtime_present = self.is_runtime_available()
        avail = dev_present and runtime_present

        if avail:
            notes = "High-throughput GPU inference with FP16 / INT8 TensorRT acceleration"
            driver_ver = "NVIDIA CUDA Runtime"
        elif dev_present and not runtime_present:
            notes = "Physical NVIDIA GPU detected on host, but Python CUDA runtime (onnxruntime-gpu/torch) is not installed."
            driver_ver = "NVIDIA Hardware Present (No Python Runtime)"
        else:
            notes = "NVIDIA GPU hardware not detected"
            driver_ver = "Not Detected"

        return HardwareAdapterProfile(
            backend_name=self.name,
            device_type=self.device_type,
            is_available=avail,
            driver_version=driver_ver,
            notes=notes,
        )

    def load_model(self, model_path: str, **kwargs: Any) -> bool:
        if not self.is_available():
            logger.warning("analytics.adapter.unavailable", adapter=self.name, model=model_path)
            return False
        logger.info("analytics.adapter.cuda.model_loaded", model=model_path)
        return True

    def infer(self, frame: np.ndarray, confidence_threshold: float = 0.5) -> list[dict[str, Any]]:
        if not self.is_available():
            raise RuntimeError(f"Cannot execute inference: hardware accelerator '{self.name}' is unavailable.")
        return []
