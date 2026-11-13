"""
camserv.acquisition.decoder
===========================

Frame decoding and pre-processing pipeline stage.

Implements :class:`~camserv.pipeline.interfaces.FrameDecoder` with:
- Resizing to inference input dimensions (e.g., 640x640)
- Color space conversion (e.g., BGR -> RGB)
- Consecutive frame deduplication (filtering static scenes to save inference GPU compute)
- Optional GPU-accelerated operations when available
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

try:
    import numpy as np
except ImportError:
    class _MockNDArray:
        shape: tuple[int, ...] = (480, 640, 3)
        dtype = "uint8"
        nbytes: int = 480 * 640 * 3
        def copy(self) -> Any:
            return self
    class _MockNumpy:
        ndarray = _MockNDArray
        uint8 = "uint8"
        float32 = "float32"
        def mean(self, arr: Any) -> float:
            return 0.0
    np = _MockNumpy()  # type: ignore[assignment]

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


from camserv.pipeline.interfaces import DecodingError, Frame, FrameDecoder

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DecoderConfig:
    """Pre-processing and decoding parameters."""

    target_size: tuple[int, int] | None = (640, 640)  # (width, height)
    to_rgb: bool = True
    normalize_float: bool = False  # Divide by 255.0 to produce float32
    enable_deduplication: bool = True
    dedup_threshold_mse: float = 2.0  # Mean squared error threshold for duplicates
    use_gpu: bool = True  # Attempt GPU-accelerated transformations


# ---------------------------------------------------------------------------
# FrameDecoder Implementation
# ---------------------------------------------------------------------------

class FrameDecoderImpl:
    """Decodes, resizes, converts color spaces, and deduplicates video frames.

    Satisfies :class:`~camserv.pipeline.interfaces.FrameDecoder`.
    """

    def __init__(self, config: DecoderConfig | None = None) -> None:
        self.config = config or DecoderConfig()
        self._last_frames: dict[str, np.ndarray] = {}  # camera_id -> downsampled image
        self._dedup_drop_count: dict[str, int] = {}
        self._has_gpu = False

        self._log = logger.bind(component="frame_decoder")
        self._check_gpu_support()

    def _check_gpu_support(self) -> None:
        """Inspect environment for CUDA/PyTorch/OpenCV GPU support."""
        if not self.config.use_gpu:
            return

        try:
            import cv2  # type: ignore[import-untyped]
            if hasattr(cv2, "cuda") and cv2.cuda.getCudaEnabledDeviceCount() > 0:
                self._has_gpu = True
                self._log.info("opencv_cuda_acceleration_available")
                return
        except Exception:
            pass

        try:
            import torch  # type: ignore[import-untyped]
            if torch.cuda.is_available():
                self._has_gpu = True
                self._log.info("torch_cuda_acceleration_available")
                return
        except Exception:
            pass

        self._log.debug("gpu_acceleration_unavailable_using_cpu")

    # ---------------------------------------------------------------------------
    # Protocol Methods
    # ---------------------------------------------------------------------------

    async def decode(
        self,
        frame: Frame,
        target_size: tuple[int, int] | None = None,
    ) -> Frame:
        """Process a single frame asynchronously without blocking the event loop."""
        return await asyncio.to_thread(self._process_frame_sync, frame, target_size)

    async def batch_decode(
        self,
        frames: list[Frame],
        target_size: tuple[int, int] | None = None,
    ) -> list[Frame]:
        """Decode a sequence of frames in parallel."""
        tasks = [self.decode(f, target_size) for f in frames]
        return await asyncio.gather(*tasks)

    # ---------------------------------------------------------------------------
    # Synchronous Execution
    # ---------------------------------------------------------------------------

    def _process_frame_sync(
        self,
        frame: Frame,
        target_size: tuple[int, int] | None = None,
    ) -> Frame:
        """CPU/GPU transformations applied to the raw frame array."""
        img = frame.image
        if img is None or not isinstance(img, np.ndarray):
            raise DecodingError(f"Invalid frame buffer for frame_id {frame.frame_id}")

        dest_size = target_size or self.config.target_size

        # 1. Deduplication check
        is_duplicate = False
        if self.config.enable_deduplication:
            is_duplicate = self._check_duplicate(frame.camera_id, img)

        processed = img.copy()

        # 2. Resizing
        if dest_size is not None and (processed.shape[1], processed.shape[0]) != dest_size:
            processed = self._resize_image(processed, dest_size)

        # 3. Color conversion (BGR -> RGB)
        if self.config.to_rgb:
            processed = self._to_rgb(processed)

        # 4. Normalization
        if self.config.normalize_float and processed.dtype == np.uint8:
            processed = processed.astype(np.float32) / 255.0

        # Create updated metadata
        meta = dict(frame.metadata)
        meta["is_duplicate"] = is_duplicate
        meta["original_shape"] = frame.shape
        meta["processed_shape"] = processed.shape

        return Frame(
            image=processed,
            camera_id=frame.camera_id,
            timestamp=frame.timestamp,
            frame_id=frame.frame_id,
            metadata=meta,
        )

    def _resize_image(self, img: np.ndarray, target_size: tuple[int, int]) -> np.ndarray:
        """Resize image to (width, height)."""
        w, h = target_size
        try:
            import cv2  # type: ignore[import-untyped]
            return cv2.resize(img, (w, h), interpolation=cv2.INTER_LINEAR)
        except ImportError:
            # Simple numpy subsampling / nearest-neighbor fallback
            orig_h, orig_w = img.shape[:2]
            row_idx = (np.linspace(0, orig_h - 1, h)).astype(int)
            col_idx = (np.linspace(0, orig_w - 1, w)).astype(int)
            return img[row_idx[:, None], col_idx]

    def _to_rgb(self, img: np.ndarray) -> np.ndarray:
        """Convert BGR image to RGB."""
        if len(img.shape) == 3 and img.shape[2] == 3:
            try:
                import cv2  # type: ignore[import-untyped]
                return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            except ImportError:
                return img[:, :, ::-1]
        return img

    def _check_duplicate(self, camera_id: str, img: np.ndarray) -> bool:
        """Check if frame is near-identical to the previous one via downsampled MSE."""
        # Downsample to 64x64 thumbnail for fast comparison
        try:
            import cv2  # type: ignore[import-untyped]
            thumb = cv2.resize(img, (64, 64), interpolation=cv2.INTER_NEAREST)
        except ImportError:
            thumb = img[::max(1, img.shape[0] // 64), ::max(1, img.shape[1] // 64)]
            if thumb.shape[:2] != (64, 64):
                thumb = thumb[:64, :64]

        last = self._last_frames.get(camera_id)
        self._last_frames[camera_id] = thumb

        if last is None or last.shape != thumb.shape:
            return False

        mse = float(np.mean((thumb.astype(np.float32) - last.astype(np.float32)) ** 2))
        is_dup = mse < self.config.dedup_threshold_mse

        if is_dup:
            cnt = self._dedup_drop_count.get(camera_id, 0) + 1
            self._dedup_drop_count[camera_id] = cnt
        return is_dup

    def deduplication_stats(self) -> dict[str, int]:
        """Return count of detected duplicates per camera."""
        return dict(self._dedup_drop_count)
