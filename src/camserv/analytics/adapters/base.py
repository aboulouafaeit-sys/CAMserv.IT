"""
camserv.analytics.adapters.base
===============================

Abstract Base Class and unified contract for hardware inference accelerator adapters.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(slots=True)
class HardwareAdapterProfile:
    """Diagnostic profile describing hardware backend accelerator capabilities."""

    backend_name: str
    device_type: str  # 'cpu', 'cuda', 'tensorrt', 'openvino', 'coral_tpu', 'hailo_npu'
    is_available: bool
    driver_version: str = "N/A"
    compute_units: int = 1
    memory_available_mb: float = 0.0
    notes: str = ""


class InferenceBackendAdapter(abc.ABC):
    """
    Standard interface implemented by all hardware neural inference backends.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique identifier for the accelerator backend."""

    @property
    @abc.abstractmethod
    def device_type(self) -> str:
        """Physical device class."""

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Probe host environment to confirm driver and device presence."""

    @abc.abstractmethod
    def get_profile(self) -> HardwareAdapterProfile:
        """Return diagnostic profile."""

    @abc.abstractmethod
    def load_model(self, model_path: str, **kwargs: Any) -> bool:
        """Compile and load model weights onto accelerator memory."""

    @abc.abstractmethod
    def infer(self, frame: np.ndarray, confidence_threshold: float = 0.5) -> list[dict[str, Any]]:
        """
        Execute forward inference pass over input frame.
        Returns list of detection dictionaries:
        [{'bbox': [x1, y1, x2, y2], 'class_name': str, 'confidence': float}]
        """
