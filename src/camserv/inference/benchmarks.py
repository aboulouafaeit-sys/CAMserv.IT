"""Inference benchmarking for CAMserv.

Measures detection latency (P50 / P95 / P99), throughput (frames/sec),
and memory usage for each detector backend.  Results are saved as JSON.

IMPORTANT: latency figures are always *measured* wall-clock times — we never
claim zero or synthetic latency values.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import structlog

from camserv.inference.detector import BaseDetector, DetectorFactory

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Result data structures
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class LatencyStats:
    """Latency percentiles in milliseconds."""

    p50: float
    p95: float
    p99: float
    mean: float
    min: float
    max: float
    std: float


@dataclass(slots=True)
class MemoryUsage:
    """Memory usage snapshot."""

    cpu_rss_mb: float
    cpu_vms_mb: float
    gpu_allocated_mb: float | None = None
    gpu_reserved_mb: float | None = None


@dataclass(slots=True)
class BenchmarkResult:
    """Complete benchmark result for one backend."""

    backend: str
    iterations: int
    warmup_iterations: int
    input_shape: tuple[int, ...]
    latency: LatencyStats
    throughput_fps: float
    memory_before: MemoryUsage
    memory_after: MemoryUsage
    timestamp: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ComparisonReport:
    """Side-by-side comparison of multiple backends."""

    results: list[BenchmarkResult]
    fastest_backend: str
    summary: str


# ---------------------------------------------------------------------------
# Memory helpers
# ---------------------------------------------------------------------------

def _get_cpu_memory() -> tuple[float, float]:
    """Return (RSS MB, VMS MB) for the current process."""
    try:
        import psutil  # type: ignore[import-untyped]

        proc = psutil.Process(os.getpid())
        mem = proc.memory_info()
        return mem.rss / (1024 ** 2), mem.vms / (1024 ** 2)
    except ImportError:
        return 0.0, 0.0


def _get_gpu_memory() -> tuple[float | None, float | None]:
    """Return (allocated MB, reserved MB) for CUDA device 0, or (None, None)."""
    try:
        import torch  # type: ignore[import-untyped]

        if torch.cuda.is_available():
            alloc = torch.cuda.memory_allocated(0) / (1024 ** 2)
            reserved = torch.cuda.memory_reserved(0) / (1024 ** 2)
            return alloc, reserved
    except ImportError:
        pass
    # Fallback: try pynvml
    try:
        import pynvml  # type: ignore[import-untyped]

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        alloc = info.used / (1024 ** 2)
        return alloc, None
    except Exception:
        pass
    return None, None


def _snapshot_memory() -> MemoryUsage:
    rss, vms = _get_cpu_memory()
    gpu_alloc, gpu_res = _get_gpu_memory()
    return MemoryUsage(
        cpu_rss_mb=round(rss, 2),
        cpu_vms_mb=round(vms, 2),
        gpu_allocated_mb=round(gpu_alloc, 2) if gpu_alloc is not None else None,
        gpu_reserved_mb=round(gpu_res, 2) if gpu_res is not None else None,
    )


# ---------------------------------------------------------------------------
# Benchmark engine
# ---------------------------------------------------------------------------

class InferenceBenchmark:
    """Measure detection latency, throughput, and memory usage.

    Parameters
    ----------
    warmup_iterations:
        Number of warm-up passes before timing begins.
    iterations:
        Number of timed iterations.
    input_shape:
        (H, W, C) of the synthetic input frame.
    """

    def __init__(
        self,
        warmup_iterations: int = 10,
        iterations: int = 100,
        input_shape: tuple[int, int, int] = (640, 640, 3),
    ) -> None:
        self._warmup = warmup_iterations
        self._iterations = iterations
        self._input_shape = input_shape

    # ------------------------------------------------------------------ #
    # Single backend benchmark
    # ------------------------------------------------------------------ #

    def benchmark(self, detector: BaseDetector) -> BenchmarkResult:
        """Benchmark a single detector backend.

        Returns measured latency percentiles and throughput — never
        synthetic or estimated values.
        """
        logger.info(
            "benchmark_start",
            backend=detector.backend_name,
            warmup=self._warmup,
            iterations=self._iterations,
            shape=self._input_shape,
        )

        frame = np.random.randint(
            0, 256, size=self._input_shape, dtype=np.uint8
        )

        # -- Warm-up phase --
        for _ in range(self._warmup):
            detector.detect(frame)
        logger.debug("warmup_complete", backend=detector.backend_name)

        # -- Timed phase --
        mem_before = _snapshot_memory()
        latencies_ms: list[float] = []

        for _ in range(self._iterations):
            t0 = time.perf_counter()
            detector.detect(frame)
            elapsed = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(elapsed)

        mem_after = _snapshot_memory()

        arr = np.array(latencies_ms, dtype=np.float64)
        total_sec = arr.sum() / 1000.0

        latency = LatencyStats(
            p50=round(float(np.percentile(arr, 50)), 3),
            p95=round(float(np.percentile(arr, 95)), 3),
            p99=round(float(np.percentile(arr, 99)), 3),
            mean=round(float(arr.mean()), 3),
            min=round(float(arr.min()), 3),
            max=round(float(arr.max()), 3),
            std=round(float(arr.std()), 3),
        )

        throughput = self._iterations / total_sec if total_sec > 0 else 0.0

        result = BenchmarkResult(
            backend=detector.backend_name,
            iterations=self._iterations,
            warmup_iterations=self._warmup,
            input_shape=self._input_shape,
            latency=latency,
            throughput_fps=round(throughput, 2),
            memory_before=mem_before,
            memory_after=mem_after,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        )

        logger.info(
            "benchmark_complete",
            backend=detector.backend_name,
            p50_ms=latency.p50,
            p95_ms=latency.p95,
            p99_ms=latency.p99,
            fps=result.throughput_fps,
        )
        return result

    # ------------------------------------------------------------------ #
    # Batch benchmark
    # ------------------------------------------------------------------ #

    def benchmark_batch(
        self,
        detector: BaseDetector,
        batch_size: int = 4,
    ) -> BenchmarkResult:
        """Benchmark batched inference.

        Measures latency for a full batch, then divides by *batch_size* to
        obtain per-frame latency.
        """
        frames = [
            np.random.randint(0, 256, size=self._input_shape, dtype=np.uint8)
            for _ in range(batch_size)
        ]

        # Warm up
        for _ in range(self._warmup):
            detector.detect_batch(frames)

        mem_before = _snapshot_memory()
        latencies_ms: list[float] = []

        for _ in range(self._iterations):
            t0 = time.perf_counter()
            detector.detect_batch(frames)
            elapsed = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(elapsed / batch_size)

        mem_after = _snapshot_memory()

        arr = np.array(latencies_ms, dtype=np.float64)
        total_sec = arr.sum() / 1000.0
        total_frames = self._iterations * batch_size

        latency = LatencyStats(
            p50=round(float(np.percentile(arr, 50)), 3),
            p95=round(float(np.percentile(arr, 95)), 3),
            p99=round(float(np.percentile(arr, 99)), 3),
            mean=round(float(arr.mean()), 3),
            min=round(float(arr.min()), 3),
            max=round(float(arr.max()), 3),
            std=round(float(arr.std()), 3),
        )

        throughput = total_frames / total_sec if total_sec > 0 else 0.0

        result = BenchmarkResult(
            backend=f"{detector.backend_name}_batch{batch_size}",
            iterations=self._iterations,
            warmup_iterations=self._warmup,
            input_shape=self._input_shape,
            latency=latency,
            throughput_fps=round(throughput, 2),
            memory_before=mem_before,
            memory_after=mem_after,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            extra={"batch_size": batch_size},
        )

        logger.info(
            "batch_benchmark_complete",
            backend=detector.backend_name,
            batch_size=batch_size,
            per_frame_p50_ms=latency.p50,
            fps=result.throughput_fps,
        )
        return result

    # ------------------------------------------------------------------ #
    # Multi-backend comparison
    # ------------------------------------------------------------------ #

    def compare_backends(
        self,
        backends: Sequence[str] | None = None,
        *,
        model_path: str = "yolov8n.onnx",
        ultralytics_model: str = "yolov8n.pt",
    ) -> ComparisonReport:
        """Benchmark multiple backends and produce a comparison report.

        Parameters
        ----------
        backends:
            List of backend names to compare.  Defaults to
            ``["onnx_cpu", "onnx_gpu", "ultralytics"]``.
        """
        backends = backends or ["onnx_cpu", "onnx_gpu", "ultralytics"]
        results: list[BenchmarkResult] = []

        for be_name in backends:
            try:
                detector = DetectorFactory.create(
                    backend=be_name,
                    model_path=model_path,
                    ultralytics_model=ultralytics_model,
                    auto_fallback=False,
                )
                result = self.benchmark(detector)
                results.append(result)
            except Exception as exc:
                logger.warning(
                    "backend_benchmark_skipped",
                    backend=be_name,
                    error=str(exc),
                )

        if not results:
            return ComparisonReport(
                results=[],
                fastest_backend="none",
                summary="No backends could be benchmarked.",
            )

        fastest = min(results, key=lambda r: r.latency.p50)
        lines = ["Backend Comparison:"]
        for r in results:
            lines.append(
                f"  {r.backend}: P50={r.latency.p50}ms  P95={r.latency.p95}ms  "
                f"P99={r.latency.p99}ms  FPS={r.throughput_fps}"
            )
        lines.append(f"Fastest (P50): {fastest.backend}")
        summary = "\n".join(lines)

        logger.info("backend_comparison_complete", fastest=fastest.backend)
        return ComparisonReport(
            results=results,
            fastest_backend=fastest.backend,
            summary=summary,
        )

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    @staticmethod
    def save_results(
        results: BenchmarkResult | ComparisonReport,
        path: str | Path,
    ) -> None:
        """Save benchmark results as JSON.

        Parameters
        ----------
        results:
            A single :class:`BenchmarkResult` or a :class:`ComparisonReport`.
        path:
            Output JSON file path.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(results, ComparisonReport):
            data = {
                "type": "comparison",
                "fastest_backend": results.fastest_backend,
                "summary": results.summary,
                "results": [asdict(r) for r in results.results],
            }
        else:
            data = {"type": "single", **asdict(results)}

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

        logger.info("benchmark_results_saved", path=str(path))

    @staticmethod
    def load_results(path: str | Path) -> dict[str, Any]:
        """Load previously saved benchmark results."""
        with open(path, encoding="utf-8") as f:
            return json.load(f)
