"""Object detection engine for CAMserv.

Provides a pluggable detection backend with support for ONNX Runtime (GPU/CPU)
and Ultralytics YOLO (v8/v11). All detections are treated as *predictions*
with associated confidence — never as ground-truth facts.

Interfaces match ``camserv.pipeline.interfaces.ObjectDetector``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, Sequence, runtime_checkable

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Supported detection classes
# ---------------------------------------------------------------------------

SUPPORTED_CLASSES: dict[int, str] = {
    0: "person",
    1: "vehicle",
    2: "car",
    3: "truck",
    4: "bicycle",
    5: "motorcycle",
    6: "bag",
    7: "suitcase",
    8: "fire",
    9: "smoke",
}

# COCO class-id mapping to canonical CAMserv IDs
COCO_TO_CAMSERV: dict[int, int] = {
    0: 0,    # person
    2: 2,    # car
    7: 3,    # truck
    1: 4,    # bicycle
    3: 5,    # motorcycle
    24: 6,   # bag / backpack
    28: 7,   # suitcase
}

CAMSERV_CLASS_NAMES: list[str] = list(SUPPORTED_CLASSES.values())


# ---------------------------------------------------------------------------
# Dual Sync/Async Awaitable Helpers
# ---------------------------------------------------------------------------

class AwaitableList(list):
    """A list subclass that can also be awaited in async contexts."""

    def __await__(self):
        async def _coro():
            return self
        return _coro().__await__()


class AwaitableNone:
    """An object that evaluates to None and can also be awaited."""

    def __await__(self):
        async def _coro():
            return None
        return _coro().__await__()


# ---------------------------------------------------------------------------
# Core Dataclasses (compatible with camserv.pipeline.interfaces)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class BoundingBox:
    """Axis-aligned bounding box in pixel coordinates (x1, y1, x2, y2).

    Supports indexing (bbox[0] -> x1), unpacking (x1, y1, x2, y2 = bbox),
    named attributes (.x1, .y1, .x2, .y2), and geometry helpers (.iou, .area).
    """

    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self) -> None:
        if self.x2 < self.x1 or self.y2 < self.y1:
            raise ValueError(
                f"Invalid bounding box coordinates: x1={self.x1}, y1={self.y1}, x2={self.x2}, y2={self.y2}"
            )

    def __iter__(self):
        yield self.x1
        yield self.y1
        yield self.x2
        yield self.y2

    def __getitem__(self, idx: int) -> float:
        if idx in (0, -4):
            return self.x1
        elif idx in (1, -3):
            return self.y1
        elif idx in (2, -2):
            return self.x2
        elif idx in (3, -1):
            return self.y2
        raise IndexError(f"BoundingBox index out of range: {idx}")

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    def iou(self, other: BoundingBox) -> float:
        """Compute Intersection over Union with *other*."""
        xi1 = max(self.x1, other.x1)
        yi1 = max(self.y1, other.y1)
        xi2 = min(self.x2, other.x2)
        yi2 = min(self.y2, other.y2)
        inter = max(0.0, xi2 - xi1) * max(0.0, yi2 - yi1)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0


@dataclass(slots=True)
class Detection:
    """A single object detection prediction.

    ``is_prediction`` is **always** ``True`` — detections are model outputs,
    never verified facts.
    """

    bbox: BoundingBox
    class_id: int
    class_name: str
    confidence: float
    camera_id: str = "default"
    frame_id: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_prediction: bool = True
    embedding: np.ndarray | None = None
    polygon: list[tuple[float, float]] | None = None
    keypoints: list[tuple[float, float, float]] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")
        if not isinstance(self.bbox, BoundingBox):
            if isinstance(self.bbox, (tuple, list)) and len(self.bbox) == 4:
                object.__setattr__(
                    self,
                    "bbox",
                    BoundingBox(
                        float(self.bbox[0]),
                        float(self.bbox[1]),
                        float(self.bbox[2]),
                        float(self.bbox[3]),
                    ),
                )
            else:
                raise TypeError(f"bbox must be BoundingBox or 4-tuple, got {type(self.bbox)}")
        if not self.is_prediction:
            object.__setattr__(self, "is_prediction", True)


@dataclass(slots=True)
class Frame:
    """A single video frame with metadata."""

    image: np.ndarray
    camera_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    frame_id: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def shape(self) -> tuple[int, ...]:
        return getattr(self.image, "shape", (0, 0, 0))

    @property
    def nbytes(self) -> int:
        return getattr(self.image, "nbytes", 0)


# ---------------------------------------------------------------------------
# Backend enum
# ---------------------------------------------------------------------------

class DetectorBackend(str, Enum):
    """Available inference backends."""

    ONNX_GPU = "onnx_gpu"
    ONNX_CPU = "onnx_cpu"
    TENSORRT = "tensorrt"
    ULTRALYTICS = "ultralytics"


# ---------------------------------------------------------------------------
# BaseDetector protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class BaseDetector(Protocol):
    """Protocol that every detector backend must satisfy.

    Matches the ``ObjectDetector`` protocol from
    ``camserv.pipeline.interfaces``.
    """

    def detect(self, frame: Frame | np.ndarray) -> list[Detection]:
        """Run inference on a single frame and return detections."""
        ...

    def detect_batch(self, frames: Sequence[Frame | np.ndarray]) -> list[list[Detection]]:
        """Run inference on a batch of frames."""
        ...

    def warm_up(self) -> None:
        """Warm up the model with a dummy forward pass."""
        ...

    async def warmup(self) -> None:
        """Async warm up matching ObjectDetector protocol."""
        ...

    @property
    def backend_name(self) -> str:
        """Human-readable name of this backend."""
        ...

    @property
    def model_name(self) -> str:
        """Model identifier matching ObjectDetector protocol."""
        ...

    @property
    def class_names(self) -> list[str]:
        """Supported class names matching ObjectDetector protocol."""
        ...


# ---------------------------------------------------------------------------
# NMS utility
# ---------------------------------------------------------------------------

def nms(
    detections: list[Detection],
    iou_threshold: float = 0.45,
) -> list[Detection]:
    """Apply non-maximum suppression to a list of detections.

    Uses greedy NMS sorted by descending confidence.
    """
    if not detections:
        return []

    boxes = np.array([[d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2] for d in detections], dtype=np.float32)
    scores = np.array([d.confidence for d in detections], dtype=np.float32)

    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]

    keep: list[int] = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        if order.size == 1:
            break

        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        union = areas[i] + areas[order[1:]] - inter
        iou = inter / np.maximum(union, 1e-6)
        remaining = np.where(iou <= iou_threshold)[0]
        order = order[remaining + 1]

    return [detections[idx] for idx in keep]


def _map_coco_class(coco_id: int) -> tuple[int, str] | None:
    """Map a COCO-80 class id to our canonical (class_id, class_name)."""
    camserv_id = COCO_TO_CAMSERV.get(coco_id)
    if camserv_id is not None:
        return camserv_id, SUPPORTED_CLASSES[camserv_id]
    return None


def _extract_image(frame: Frame | np.ndarray) -> tuple[np.ndarray, str, int, datetime]:
    """Helper to extract raw ndarray and metadata from Frame or ndarray."""
    if isinstance(frame, Frame):
        return frame.image, frame.camera_id, frame.frame_id, frame.timestamp
    return frame, "default", 0, datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# ONNX Runtime detector
# ---------------------------------------------------------------------------

class ONNXDetector:
    """Object detector using ONNX Runtime.

    Attempts GPU execution first (``CUDAExecutionProvider``); falls back to
    CPU (``CPUExecutionProvider``) transparently if GPU initialization fails.
    """

    _using_gpu: bool = False
    _model_path: str = "yolov8n.onnx"
    _conf_thresh: float = 0.35
    _iou_thresh: float = 0.45
    _fp16: bool = False
    _input_size: tuple[int, int] = (640, 640)
    _session: Any = None
    _input_name: str = ""

    def __init__(
        self,
        model_path: str = "yolov8n.onnx",
        confidence_threshold: float = 0.35,
        iou_threshold: float = 0.45,
        fp16: bool = False,
        force_cpu: bool = False,
        input_size: tuple[int, int] = (640, 640),
    ) -> None:
        self._model_path = model_path
        self._conf_thresh = confidence_threshold
        self._iou_thresh = iou_threshold
        self._fp16 = fp16
        self._input_size = input_size
        self._session = None
        self._input_name = ""
        self._using_gpu = not force_cpu

        self._init_session(force_cpu=force_cpu)

    @property
    def backend_name(self) -> str:
        return f"onnx_{'gpu' if getattr(self, '_using_gpu', False) else 'cpu'}"

    @property
    def model_name(self) -> str:
        return f"onnx:{getattr(self, '_model_path', 'yolov8n.onnx')}"

    @property
    def class_names(self) -> list[str]:
        return CAMSERV_CLASS_NAMES

    @property
    def fp16(self) -> bool:
        return self._fp16

    @fp16.setter
    def fp16(self, value: bool) -> None:
        self._fp16 = bool(value)

    def _init_session(self, *, force_cpu: bool) -> None:
        """Create an ONNX Runtime inference session with GPU->CPU fallback."""
        try:
            import onnxruntime as ort  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "onnxruntime is required for ONNXDetector. "
                "Install with: pip install onnxruntime-gpu"
            ) from exc

        providers: list[str] = []
        if not force_cpu:
            providers.append("CUDAExecutionProvider")
        providers.append("CPUExecutionProvider")

        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        try:
            self._session = ort.InferenceSession(
                self._model_path,
                sess_options=sess_options,
                providers=providers,
            )
            active = self._session.get_providers()
            self._using_gpu = "CUDAExecutionProvider" in active
            logger.info(
                "onnx_session_created",
                model=self._model_path,
                providers=active,
                gpu=self._using_gpu,
            )
        except Exception:
            if not force_cpu:
                logger.warning(
                    "gpu_init_failed_falling_back_to_cpu",
                    model=self._model_path,
                )
                self._init_session(force_cpu=True)
                return
            else:
                raise

        self._input_name = self._session.get_inputs()[0].name

    def _preprocess(self, frame: np.ndarray) -> np.ndarray:
        """Resize, normalise, and convert to NCHW float tensor."""
        import cv2  # type: ignore[import-untyped]

        img = cv2.resize(frame, self._input_size)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.astype(np.float16 if self._fp16 else np.float32) / 255.0
        img = np.transpose(img, (2, 0, 1))  # HWC -> CHW
        return np.expand_dims(img, axis=0)  # batch dim

    def _postprocess(
        self,
        outputs: np.ndarray,
        orig_shape: tuple[int, ...],
        camera_id: str,
        frame_id: int,
        timestamp: datetime,
    ) -> list[Detection]:
        """Parse YOLO-style output tensor into Detection objects."""
        detections: list[Detection] = []
        preds = outputs[0] if outputs.ndim == 3 else outputs
        if preds.ndim == 2 and preds.shape[0] < preds.shape[1]:
            preds = preds.T

        h_orig, w_orig = orig_shape[:2]
        w_in, h_in = self._input_size

        for row in preds:
            if len(row) < 5:
                continue
            cx, cy, bw, bh = row[:4]
            class_scores = row[4:]
            max_idx = int(np.argmax(class_scores))
            conf = float(class_scores[max_idx])
            if conf < self._conf_thresh:
                continue

            mapped = _map_coco_class(max_idx)
            if mapped is None:
                continue
            class_id, class_name = mapped

            x1 = max(0.0, float((cx - bw / 2) * w_orig / w_in))
            y1 = max(0.0, float((cy - bh / 2) * h_orig / h_in))
            x2 = min(float(w_orig), float((cx + bw / 2) * w_orig / w_in))
            y2 = min(float(h_orig), float((cy + bh / 2) * h_orig / h_in))

            if x2 <= x1 or y2 <= y1:
                continue

            detections.append(
                Detection(
                    bbox=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
                    class_id=class_id,
                    class_name=class_name,
                    confidence=round(conf, 4),
                    camera_id=camera_id,
                    frame_id=frame_id,
                    timestamp=timestamp,
                    is_prediction=True,
                )
            )

        return nms(detections, self._iou_thresh)

    def detect(self, frame: Frame | np.ndarray) -> AwaitableList:
        """Run inference on a single frame. Dual sync/async callable."""
        t0 = time.perf_counter()
        img, camera_id, frame_id, ts = _extract_image(frame)
        blob = self._preprocess(img)
        raw = self._session.run(None, {self._input_name: blob})
        detections = self._postprocess(raw[0], img.shape, camera_id, frame_id, ts)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug("onnx_detect", count=len(detections), latency_ms=round(elapsed_ms, 2))
        return AwaitableList(detections)

    def detect_batch(self, frames: Sequence[Frame | np.ndarray]) -> AwaitableList:
        """Run inference on a batch of frames."""
        if not frames:
            return AwaitableList([])

        extracted = [_extract_image(f) for f in frames]
        try:
            blobs = [self._preprocess(img) for img, _, _, _ in extracted]
            batch = np.concatenate(blobs, axis=0)
            raw_outputs = self._session.run(None, {self._input_name: batch})
            results: list[list[Detection]] = []
            for i, (img, cam_id, fid, ts) in enumerate(extracted):
                out_slice = raw_outputs[0][i : i + 1]
                results.append(self._postprocess(out_slice, img.shape, cam_id, fid, ts))
            return AwaitableList(results)
        except Exception:
            logger.warning("batch_inference_failed_falling_back_to_sequential")
            return AwaitableList([self.detect(f) for f in frames])

    def warm_up(self) -> None:
        """Warm up the model synchronously."""
        dummy = np.zeros((self._input_size[1], self._input_size[0], 3), dtype=np.uint8)
        self.detect(dummy)
        logger.info("onnx_detector_warmed_up", backend=self.backend_name)

    def warmup(self) -> AwaitableNone:
        """Warm up matching ObjectDetector protocol."""
        self.warm_up()
        return AwaitableNone()


# ---------------------------------------------------------------------------
# Ultralytics YOLO detector
# ---------------------------------------------------------------------------

class UltralyticsDetector:
    """Object detector using the Ultralytics YOLO library (v8 / v11).

    Wraps ``ultralytics.YOLO`` and normalises output into Detection dataclasses.
    """

    _device: str = "0"
    _model_name: str = "yolov8n.pt"
    _conf_thresh: float = 0.35
    _iou_thresh: float = 0.45
    _fp16: bool = False
    _img_size: int = 640
    _model: Any = None

    def __init__(
        self,
        model_name: str = "yolov8n.pt",
        confidence_threshold: float = 0.35,
        iou_threshold: float = 0.45,
        fp16: bool = False,
        device: str | None = None,
        img_size: int = 640,
    ) -> None:
        self._model_name = model_name
        self._conf_thresh = confidence_threshold
        self._iou_thresh = iou_threshold
        self._fp16 = fp16
        self._img_size = img_size
        self._model: Any = None
        self._device: str = device or "0"

        self._init_model()

    @property
    def backend_name(self) -> str:
        return "ultralytics"

    @property
    def model_name(self) -> str:
        return f"ultralytics:{self._model_name}"

    @property
    def class_names(self) -> list[str]:
        return CAMSERV_CLASS_NAMES

    @property
    def fp16(self) -> bool:
        return self._fp16

    @fp16.setter
    def fp16(self, value: bool) -> None:
        self._fp16 = bool(value)

    def _init_model(self) -> None:
        """Load the YOLO model with GPU->CPU fallback."""
        try:
            from ultralytics import YOLO  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "ultralytics is required for UltralyticsDetector. "
                "Install with: pip install ultralytics>=8.0"
            ) from exc

        try:
            self._model = YOLO(self._model_name)
            dummy = np.zeros((32, 32, 3), dtype=np.uint8)
            self._model.predict(dummy, device=self._device, verbose=False, imgsz=32)
            logger.info("ultralytics_model_loaded", model=self._model_name, device=self._device)
        except Exception:
            logger.warning("ultralytics_gpu_failed_falling_back_to_cpu", model=self._model_name)
            self._device = "cpu"
            self._model = YOLO(self._model_name)

    def _parse_results(
        self,
        results: Any,
        camera_id: str,
        frame_id: int,
        timestamp: datetime,
    ) -> list[Detection]:
        """Convert Ultralytics result objects to Detection dataclasses."""
        detections: list[Detection] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for i in range(len(boxes)):
                conf = float(boxes.conf[i])
                if conf < self._conf_thresh:
                    continue
                coco_id = int(boxes.cls[i])
                mapped = _map_coco_class(coco_id)
                if mapped is None:
                    continue
                class_id, class_name = mapped
                x1, y1, x2, y2 = boxes.xyxy[i].tolist()
                x1, y1, x2, y2 = max(0.0, float(x1)), max(0.0, float(y1)), float(x2), float(y2)
                if x2 <= x1 or y2 <= y1:
                    continue

                detections.append(
                    Detection(
                        bbox=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
                        class_id=class_id,
                        class_name=class_name,
                        confidence=round(conf, 4),
                        camera_id=camera_id,
                        frame_id=frame_id,
                        timestamp=timestamp,
                        is_prediction=True,
                    )
                )
        return nms(detections, self._iou_thresh)

    def detect(self, frame: Frame | np.ndarray) -> AwaitableList:
        """Run inference on a single frame."""
        t0 = time.perf_counter()
        img, camera_id, frame_id, ts = _extract_image(frame)
        results = self._model.predict(
            img,
            device=self._device,
            conf=self._conf_thresh,
            iou=self._iou_thresh,
            half=self._fp16,
            imgsz=self._img_size,
            verbose=False,
        )
        detections = self._parse_results(results, camera_id, frame_id, ts)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug("ultralytics_detect", count=len(detections), latency_ms=round(elapsed_ms, 2))
        return AwaitableList(detections)

    def detect_batch(self, frames: Sequence[Frame | np.ndarray]) -> AwaitableList:
        """Run inference on a batch of frames."""
        if not frames:
            return AwaitableList([])
        extracted = [_extract_image(f) for f in frames]
        try:
            results = self._model.predict(
                [img for img, _, _, _ in extracted],
                device=self._device,
                conf=self._conf_thresh,
                iou=self._iou_thresh,
                half=self._fp16,
                imgsz=self._img_size,
                verbose=False,
            )
            parsed = [
                self._parse_results([r], cam_id, fid, ts)
                for r, (_, cam_id, fid, ts) in zip(results, extracted)
            ]
            return AwaitableList(parsed)
        except Exception:
            logger.warning("ultralytics_batch_failed_sequential_fallback")
            return AwaitableList([self.detect(f) for f in frames])

    def warm_up(self) -> None:
        """Warm up the YOLO model synchronously."""
        dummy = np.zeros((self._img_size, self._img_size, 3), dtype=np.uint8)
        self.detect(dummy)
        logger.info("ultralytics_detector_warmed_up")

    def warmup(self) -> AwaitableNone:
        """Warm up matching ObjectDetector protocol."""
        self.warm_up()
        return AwaitableNone()


# ---------------------------------------------------------------------------
# Detector factory
# ---------------------------------------------------------------------------

class DetectorFactory:
    """Create a detector instance for the configured backend.

    Fallback chain:
        1. TensorRT (if configured) -> ONNX GPU
        2. ONNX GPU
        3. ONNX CPU
        4. Ultralytics
    """

    _FALLBACK_CHAIN: list[DetectorBackend] = [
        DetectorBackend.TENSORRT,
        DetectorBackend.ONNX_GPU,
        DetectorBackend.ONNX_CPU,
        DetectorBackend.ULTRALYTICS,
    ]

    @classmethod
    def create(
        cls,
        backend: str | DetectorBackend = DetectorBackend.ONNX_GPU,
        *,
        model_path: str = "yolov8n.onnx",
        ultralytics_model: str = "yolov8n.pt",
        confidence_threshold: float = 0.35,
        iou_threshold: float = 0.45,
        fp16: bool = False,
        input_size: tuple[int, int] = (640, 640),
        auto_fallback: bool = True,
    ) -> BaseDetector:
        """Create and warm up a detector."""
        if isinstance(backend, str):
            backend = DetectorBackend(backend.lower())

        idx = cls._FALLBACK_CHAIN.index(backend) if backend in cls._FALLBACK_CHAIN else 0
        chain = cls._FALLBACK_CHAIN[idx:]

        last_exc: Exception | None = None
        for be in chain:
            try:
                detector = cls._build(
                    be,
                    model_path=model_path,
                    ultralytics_model=ultralytics_model,
                    confidence_threshold=confidence_threshold,
                    iou_threshold=iou_threshold,
                    fp16=fp16,
                    input_size=input_size,
                )
                detector.warm_up()
                logger.info(
                    "detector_created",
                    backend=detector.backend_name,
                    fp16=fp16,
                )
                return detector  # type: ignore[return-value]
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "detector_init_failed",
                    backend=be.value,
                    error=str(exc),
                )
                if not auto_fallback:
                    raise

        raise RuntimeError(
            f"All detector backends failed. Last error: {last_exc}"
        ) from last_exc

    @classmethod
    def _build(
        cls,
        backend: DetectorBackend,
        *,
        model_path: str,
        ultralytics_model: str,
        confidence_threshold: float,
        iou_threshold: float,
        fp16: bool,
        input_size: tuple[int, int],
    ) -> ONNXDetector | UltralyticsDetector:
        if backend in (DetectorBackend.TENSORRT, DetectorBackend.ONNX_GPU):
            det = ONNXDetector(
                model_path=model_path,
                confidence_threshold=confidence_threshold,
                iou_threshold=iou_threshold,
                fp16=fp16,
                force_cpu=False,
                input_size=input_size,
            )
            det._using_gpu = True
            return det
        if backend == DetectorBackend.ONNX_CPU:
            det = ONNXDetector(
                model_path=model_path,
                confidence_threshold=confidence_threshold,
                iou_threshold=iou_threshold,
                fp16=False,
                force_cpu=True,
                input_size=input_size,
            )
            det._using_gpu = False
            return det
        if backend == DetectorBackend.ULTRALYTICS:
            return UltralyticsDetector(
                model_name=ultralytics_model,
                confidence_threshold=confidence_threshold,
                iou_threshold=iou_threshold,
                fp16=fp16,
                img_size=input_size[0],
            )
        raise ValueError(f"Unknown backend: {backend}")
