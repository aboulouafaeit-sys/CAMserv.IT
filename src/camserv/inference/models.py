"""
camserv.inference.models
========================

AI Model Registry, Task Definitions, and Integrity Management for CAMserv.

Features:
- Explicit task separation: Object detection, instance segmentation, pose, tracking.
- Cryptographic integrity verification (SHA-256 checksums).
- Structured model metadata: Input/output shapes, classes, license, provenance.
- Thread-safe ModelRegistry for model registration and discovery.
"""

from __future__ import annotations

import enum
import hashlib
import os
import threading
from dataclasses import dataclass, field
from typing import Any

try:
    import structlog
except ImportError:
    import logging
    class _FallbackLogger:
        def __init__(self, name: str = "camserv") -> None:
            self._logger = logging.getLogger(name)
        def bind(self, **kwargs: Any) -> _FallbackLogger:
            return self
        def info(self, event: str, **kwargs: Any) -> None:
            self._logger.info(f"{event} {kwargs}" if kwargs else event)
        def warning(self, event: str, **kwargs: Any) -> None:
            self._logger.warning(f"{event} {kwargs}" if kwargs else event)
        def error(self, event: str, **kwargs: Any) -> None:
            self._logger.error(f"{event} {kwargs}" if kwargs else event)
        def debug(self, event: str, **kwargs: Any) -> None:
            self._logger.debug(f"{event} {kwargs}" if kwargs else event)
        def critical(self, event: str, **kwargs: Any) -> None:
            self._logger.critical(f"{event} {kwargs}" if kwargs else event)
    class _MockStructlog:
        @staticmethod
        def get_logger(name: str | None = None) -> _FallbackLogger:
            return _FallbackLogger(name or "camserv")
    structlog = _MockStructlog()  # type: ignore[assignment]


logger = structlog.get_logger(__name__)


class ModelTask(enum.Enum):
    """Specific computer vision and analytical tasks supported by models."""

    OBJECT_DETECTION = "object_detection"
    INSTANCE_SEGMENTATION = "instance_segmentation"
    SEMANTIC_SEGMENTATION = "semantic_segmentation"
    POSE_ESTIMATION = "pose_estimation"
    OBJECT_TRACKING = "object_tracking"
    FACE_DETECTION = "face_detection"
    PLATE_DETECTION = "plate_detection"


class InferenceProvider(enum.Enum):
    """Hardware acceleration and software inference providers."""

    CUDA = "CUDAExecutionProvider"
    TENSORRT = "TensorrtExecutionProvider"
    OPENVINO = "OpenVINOExecutionProvider"
    DIRECTML = "DmlExecutionProvider"
    CPU = "CPUExecutionProvider"


class ModelIntegrityError(Exception):
    """Raised when a model file fails cryptographic integrity verification."""


class ModelNotFoundError(Exception):
    """Raised when requesting a model not present in the registry."""


@dataclass(slots=True)
class ModelMetadata:
    """Comprehensive specification for an AI model artifact."""

    name: str
    version: str
    task: ModelTask
    framework: str                      # "onnx", "tensorrt", "openvino"
    file_path: str
    input_shape: tuple[int, ...]        # e.g. (1, 3, 640, 640)
    output_shape: list[tuple[int, ...]] # e.g. [(1, 84, 8400)]
    class_names: list[str]
    sha256_hash: str                    # Hexadecimal SHA-256 digest
    license: str                        # e.g. "Apache-2.0", "MIT", "AGPL-3.0"
    provenance: str                     # Source repository, paper, or build origin
    supports_fp16: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def calculate_file_hash(self) -> str:
        """Calculate the SHA-256 digest of the model file on disk."""
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"Model file does not exist: {self.file_path}")

        hasher = hashlib.sha256()
        with open(self.file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def verify_integrity(self) -> bool:
        """Verify that the model file hash matches the registered hash."""
        computed = self.calculate_file_hash()
        return computed.lower() == self.sha256_hash.lower()


class ModelRegistry:
    """Thread-safe registry for AI models and their verified metadata."""

    def __init__(self) -> None:
        self._models: dict[tuple[str, str], ModelMetadata] = {}
        self._lock = threading.RLock()
        self._log = logger.bind(component="model_registry")

    def register_model(self, metadata: ModelMetadata, verify_immediately: bool = True) -> None:
        """Register a model artifact with optional immediate integrity check."""
        with self._lock:
            key = (metadata.name, metadata.version)
            if verify_immediately and os.path.exists(metadata.file_path):
                if not metadata.verify_integrity():
                    self._log.error(
                        "model_registry.integrity_check_failed",
                        model=metadata.name,
                        version=metadata.version,
                        path=metadata.file_path,
                    )
                    raise ModelIntegrityError(
                        f"Integrity check failed for model '{metadata.name}:{metadata.version}'. "
                        f"Expected SHA-256 {metadata.sha256_hash}, file hash differs."
                    )

            self._models[key] = metadata
            self._log.info(
                "model_registry.registered",
                model=metadata.name,
                version=metadata.version,
                task=metadata.task.value,
                path=metadata.file_path,
            )

    def unregister_model(self, name: str, version: str) -> bool:
        """Remove a model from the registry."""
        with self._lock:
            key = (name, version)
            return self._models.pop(key, None) is not None

    def get_model(self, name: str, version: str | None = None) -> ModelMetadata:
        """Retrieve model metadata by name and optional version (defaults to latest registered)."""
        with self._lock:
            if version is not None:
                key = (name, version)
                if key in self._models:
                    return self._models[key]
                raise ModelNotFoundError(f"Model '{name}' version '{version}' not found in registry.")

            # Find matching models and pick latest version
            candidates = [m for (n, _), m in self._models.items() if n == name]
            if not candidates:
                raise ModelNotFoundError(f"Model '{name}' not found in registry.")
            return candidates[-1]

    def list_models(self, task: ModelTask | None = None) -> list[ModelMetadata]:
        """List registered models, optionally filtered by task."""
        with self._lock:
            if task is None:
                return list(self._models.values())
            return [m for m in self._models.values() if m.task == task]

    def clear(self) -> None:
        """Clear all registered models."""
        with self._lock:
            self._models.clear()


# Global default registry instance
global_model_registry = ModelRegistry()
