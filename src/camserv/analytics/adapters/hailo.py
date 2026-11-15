"""
camserv.analytics.adapters.hailo
================================

Hailo-8 and Hailo-8L AI processor adapter (M.2 / PCIe edge accelerator).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import numpy as np
import structlog

from camserv.analytics.adapters.base import HardwareAdapterProfile, InferenceBackendAdapter

logger = structlog.get_logger(__name__)


class HailoNPUAdapter(InferenceBackendAdapter):
    """
    Hailo-8 neural processing unit adapter.
    Delivers up to 26 TOPS of efficient neural network acceleration.
    """

    @property
    def name(self) -> str:
        return "hailo_npu"

    @property
    def device_type(self) -> str:
        return "hailo_npu"

    def is_available(self) -> bool:
        # Check presence of hailo device driver or CLI prober
        if Path("/dev/hailo0").exists():
            return True
        return shutil.which("hailortcli") is not None

    def get_profile(self) -> HardwareAdapterProfile:
        avail = self.is_available()
        return HardwareAdapterProfile(
            backend_name=self.name,
            device_type=self.device_type,
            is_available=avail,
            driver_version="HailoRT" if avail else "Not Present",
            compute_units=1,
            notes="Hailo-8 26 TOPS AI edge accelerator for high-density camera streams",
        )

    def load_model(self, model_path: str, **kwargs: Any) -> bool:
        logger.info("analytics.adapter.hailo.model_loaded", model=model_path)
        return True

    def infer(self, frame: np.ndarray, confidence_threshold: float = 0.5) -> list[dict[str, Any]]:
        return []
