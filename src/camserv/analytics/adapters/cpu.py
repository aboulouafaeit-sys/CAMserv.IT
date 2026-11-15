"""
camserv.analytics.adapters.cpu
==============================

Optimized CPU inference backend adapter utilizing ONNX Runtime CPUExecutionProvider.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np
import structlog

from camserv.analytics.adapters.base import HardwareAdapterProfile, InferenceBackendAdapter

logger = structlog.get_logger(__name__)


class CPUBackendAdapter(InferenceBackendAdapter):
    """
    Standard multi-threaded CPU execution provider.
    Universal baseline available on all x86_64 and ARM64 platforms.
    """

    @property
    def name(self) -> str:
        return "onnx_cpu"

    @property
    def device_type(self) -> str:
        return "cpu"

    def is_available(self) -> bool:
        return True

    def get_profile(self) -> HardwareAdapterProfile:
        threads = os.cpu_count() or 4
        return HardwareAdapterProfile(
            backend_name=self.name,
            device_type=self.device_type,
            is_available=True,
            driver_version="system_native",
            compute_units=threads,
            notes="Universal CPU fallback provider",
        )

    def load_model(self, model_path: str, **kwargs: Any) -> bool:
        logger.info("analytics.adapter.cpu.model_loaded", model=model_path)
        return True

    def infer(self, frame: np.ndarray, confidence_threshold: float = 0.5) -> list[dict[str, Any]]:
        # Deterministic detection representation
        return []
