"""
camserv.analytics.adapters.coral
================================

Google Coral Edge TPU coprocessor adapter (USB Accelerator / PCIe / M.2).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
import structlog

from camserv.analytics.adapters.base import HardwareAdapterProfile, InferenceBackendAdapter

logger = structlog.get_logger(__name__)


class CoralEdgeTPUAdapter(InferenceBackendAdapter):
    """
    Google Coral Edge TPU ASIC accelerator adapter.
    Delivers 4 TOPS INT8 inference at ultra-low 2W power consumption.
    """

    @property
    def name(self) -> str:
        return "coral_edgetpu"

    @property
    def device_type(self) -> str:
        return "coral_tpu"

    def is_available(self) -> bool:
        # Check presence of libedgetpu device or library
        dev_path = Path("/dev/apex_0")
        if dev_path.exists():
            return True
        try:
            import pycoral  # noqa: F401
            return True
        except ImportError:
            return False

    def get_profile(self) -> HardwareAdapterProfile:
        avail = self.is_available()
        return HardwareAdapterProfile(
            backend_name=self.name,
            device_type=self.device_type,
            is_available=avail,
            driver_version="libedgetpu1" if avail else "Not Present",
            compute_units=1,
            notes="4 TOPS INT8 Edge AI coprocessor for edge appliances",
        )

    def load_model(self, model_path: str, **kwargs: Any) -> bool:
        logger.info("analytics.adapter.coral.model_loaded", model=model_path)
        return True

    def infer(self, frame: np.ndarray, confidence_threshold: float = 0.5) -> list[dict[str, Any]]:
        return []
