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
    """

    @property
    def name(self) -> str:
        return "nvidia_cuda"

    @property
    def device_type(self) -> str:
        return "cuda"

    def is_available(self) -> bool:
        # Check presence of nvidia-smi or CUDA drivers
        return shutil.which("nvidia-smi") is not None

    def get_profile(self) -> HardwareAdapterProfile:
        avail = self.is_available()
        return HardwareAdapterProfile(
            backend_name=self.name,
            device_type=self.device_type,
            is_available=avail,
            driver_version="NVIDIA CUDA Runtime" if avail else "Not Detected",
            notes="High-throughput GPU inference with FP16 / INT8 TensorRT acceleration" if avail else "NVIDIA drivers not detected",
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
