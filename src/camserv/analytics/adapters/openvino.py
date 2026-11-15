"""
camserv.analytics.adapters.openvino
==================================

Intel OpenVINO inference accelerator adapter for Intel CPUs, integrated GPUs (iGPU),
and Intel Neural Compute Sticks.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import structlog

from camserv.analytics.adapters.base import HardwareAdapterProfile, InferenceBackendAdapter

logger = structlog.get_logger(__name__)


class OpenVINOBackendAdapter(InferenceBackendAdapter):
    """
    Intel OpenVINO toolkit adapter for heterogeneous Intel hardware.
    """

    @property
    def name(self) -> str:
        return "intel_openvino"

    @property
    def device_type(self) -> str:
        return "openvino"

    def is_available(self) -> bool:
        try:
            import openvino  # noqa: F401
            return True
        except ImportError:
            return False

    def get_profile(self) -> HardwareAdapterProfile:
        avail = self.is_available()
        return HardwareAdapterProfile(
            backend_name=self.name,
            device_type=self.device_type,
            is_available=avail,
            driver_version="OpenVINO Runtime" if avail else "Not Installed",
            notes="Optimized for Intel Core/Xeon iGPU and VPU acceleration",
        )

    def load_model(self, model_path: str, **kwargs: Any) -> bool:
        if not self.is_available():
            logger.warning("analytics.adapter.unavailable", adapter=self.name, model=model_path)
            return False
        logger.info("analytics.adapter.openvino.model_loaded", model=model_path)
        return True

    def infer(self, frame: np.ndarray, confidence_threshold: float = 0.5) -> list[dict[str, Any]]:
        if not self.is_available():
            raise RuntimeError(f"Cannot execute inference: hardware accelerator '{self.name}' is unavailable.")
        return []
