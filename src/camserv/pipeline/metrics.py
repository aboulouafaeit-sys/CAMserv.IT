"""
camserv.pipeline.metrics
=========================

Latency, throughput and resource-usage metrics for the pipeline engine.

Key components:

* :class:`LatencyTracker` — streaming P50/P95/P99 estimation via a DDSketch-
  inspired algorithm (log-bucketed histogram) that requires O(1) memory per
  observation.
* :class:`ThroughputCounter` — sliding-window frames-per-second counter.
* :class:`QueueDepthMonitor` — tracks current, max and average queue depths.
* :class:`MemoryMonitor` — polls process RSS and (optionally) GPU VRAM.
* :class:`MetricsRegistry` — central registry with Prometheus-format export.
* :func:`run_benchmark` — synthetic workload harness.
"""

from __future__ import annotations

import asyncio
import math
import os
import time
from collections import deque
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


# ---------------------------------------------------------------------------
# DDSketch-inspired latency tracker
# ---------------------------------------------------------------------------

class LatencyTracker:
    """Streaming quantile estimator using logarithmic bucketing.

    This is a simplified DDSketch: observations are mapped to buckets
    of width ``γ = (1 + α) / (1 - α)`` in log space, where *α* controls
    relative accuracy (default 1 %).  Memory is bounded by the number of
    distinct buckets observed, not the observation count.

    Parameters
    ----------
    name:
        Metric name (used in export).
    alpha:
        Relative accuracy guarantee (0.01 ≈ 1 %).
    window:
        When set, only the most recent *window* observations are kept
        (useful for "last 5 min" views).  ``None`` keeps all.
    """

    def __init__(
        self,
        name: str,
        alpha: float = 0.01,
        window: int | None = None,
    ) -> None:
        self.name = name
        self._alpha = alpha
        self._gamma = (1.0 + alpha) / (1.0 - alpha)
        self._log_gamma = math.log(self._gamma)
        self._min_value = 1e-9  # clamp zero/negative

        # Global sketch (all time)
        self._buckets: dict[int, int] = {}
        self._count: int = 0
        self._total: float = 0.0
        self._min: float = float("inf")
        self._max: float = 0.0

        # Sliding window (optional)
        self._window = window
        self._window_values: deque[float] = deque(maxlen=window) if window else deque()

    # -- Recording ------------------------------------------------------------

    def record(self, value_ms: float) -> None:
        """Record a latency observation in **milliseconds**."""
        v = max(value_ms, self._min_value)
        bucket = self._key(v)
        self._buckets[bucket] = self._buckets.get(bucket, 0) + 1
        self._count += 1
        self._total += v
        if v < self._min:
            self._min = v
        if v > self._max:
            self._max = v
        self._window_values.append(v)

    # -- Queries --------------------------------------------------------------

    def quantile(self, q: float) -> float:
        """Return the estimated value at quantile *q* (0.0–1.0).

        Uses the global sketch (ignoring window).
        """
        if not self._buckets:
            return 0.0
        target = q * self._count
        cumulative = 0
        for key in sorted(self._buckets):
            cumulative += self._buckets[key]
            if cumulative >= target:
                return self._bucket_midpoint(key)
        return self._max

    @property
    def p50(self) -> float:
        return self.quantile(0.50)

    @property
    def p95(self) -> float:
        return self.quantile(0.95)

    @property
    def p99(self) -> float:
        return self.quantile(0.99)

    @property
    def mean(self) -> float:
        return self._total / self._count if self._count else 0.0

    @property
    def count(self) -> int:
        return self._count

    @property
    def min(self) -> float:
        return self._min if self._count else 0.0

    @property
    def max(self) -> float:
        return self._max

    def window_quantile(self, q: float) -> float:
        """Quantile computed over the sliding window only."""
        if not self._window_values:
            return 0.0
        sorted_vals = sorted(self._window_values)
        idx = int(q * (len(sorted_vals) - 1))
        return sorted_vals[idx]

    # -- Internals ------------------------------------------------------------

    def _key(self, value: float) -> int:
        return int(math.ceil(math.log(value) / self._log_gamma))

    def _bucket_midpoint(self, key: int) -> float:
        lo = self._gamma ** (key - 1)
        hi = self._gamma ** key
        return (lo + hi) / 2.0

    def reset(self) -> None:
        """Clear all recorded data."""
        self._buckets.clear()
        self._count = 0
        self._total = 0.0
        self._min = float("inf")
        self._max = 0.0
        self._window_values.clear()

    def summary(self) -> dict[str, float]:
        """Return a dict summary suitable for logging / JSON export."""
        return {
            "name": self.name,
            "count": self._count,
            "mean_ms": round(self.mean, 3),
            "min_ms": round(self.min, 3),
            "max_ms": round(self.max, 3),
            "p50_ms": round(self.p50, 3),
            "p95_ms": round(self.p95, 3),
            "p99_ms": round(self.p99, 3),
        }


# ---------------------------------------------------------------------------
# Throughput counter
# ---------------------------------------------------------------------------

class ThroughputCounter:
    """Sliding-window throughput counter (items per second).

    Parameters
    ----------
    name:
        Metric name.
    window_seconds:
        Width of the sliding window.
    """

    def __init__(self, name: str, window_seconds: float = 10.0) -> None:
        self.name = name
        self._window = window_seconds
        self._timestamps: deque[float] = deque()
        self._total: int = 0

    def tick(self, count: int = 1) -> None:
        """Record *count* items processed right now."""
        now = time.monotonic()
        for _ in range(count):
            self._timestamps.append(now)
        self._total += count
        self._prune(now)

    @property
    def rate(self) -> float:
        """Current items-per-second over the sliding window."""
        now = time.monotonic()
        self._prune(now)
        if not self._timestamps:
            return 0.0
        elapsed = now - self._timestamps[0]
        if elapsed <= 0:
            return float(len(self._timestamps))
        return len(self._timestamps) / elapsed

    @property
    def total(self) -> int:
        return self._total

    def _prune(self, now: float) -> None:
        cutoff = now - self._window
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    def reset(self) -> None:
        self._timestamps.clear()
        self._total = 0


# ---------------------------------------------------------------------------
# Queue depth monitor
# ---------------------------------------------------------------------------

class QueueDepthMonitor:
    """Tracks current, peak and running-average queue depths.

    Call :meth:`record` periodically (e.g. every time the pipeline polls a
    queue) with the current depth.
    """

    def __init__(self, name: str, window: int = 500) -> None:
        self.name = name
        self._samples: deque[int] = deque(maxlen=window)
        self._peak: int = 0

    def record(self, depth: int) -> None:
        self._samples.append(depth)
        if depth > self._peak:
            self._peak = depth

    @property
    def current(self) -> int:
        return self._samples[-1] if self._samples else 0

    @property
    def peak(self) -> int:
        return self._peak

    @property
    def average(self) -> float:
        return sum(self._samples) / len(self._samples) if self._samples else 0.0

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "current": self.current,
            "peak": self._peak,
            "average": round(self.average, 2),
            "samples": len(self._samples),
        }

    def reset(self) -> None:
        self._samples.clear()
        self._peak = 0


# ---------------------------------------------------------------------------
# Memory monitor
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class MemorySnapshot:
    """Point-in-time memory reading."""

    process_rss_mb: float
    process_vms_mb: float
    gpu_used_mb: float | None
    gpu_total_mb: float | None
    timestamp: float


class MemoryMonitor:
    """Tracks process RSS and (optionally) NVIDIA GPU memory usage.

    GPU monitoring requires ``pynvml``; if unavailable the GPU fields are
    ``None``.
    """

    def __init__(self, gpu_device_index: int = 0) -> None:
        self._gpu_index = gpu_device_index
        self._nvml_available = False
        self._handle: Any = None
        self._history: deque[MemorySnapshot] = deque(maxlen=300)
        self._log = logger.bind(component="memory_monitor")

        # Try to initialise NVML
        try:
            import pynvml  # type: ignore[import-untyped]

            pynvml.nvmlInit()
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_device_index)
            self._nvml_available = True
            self._pynvml = pynvml
            self._log.info("nvml_available", gpu_index=gpu_device_index)
        except Exception:
            self._log.info("nvml_unavailable_gpu_monitoring_disabled")

    def snapshot(self) -> MemorySnapshot:
        """Take a point-in-time reading of process and GPU memory."""
        try:
            import psutil  # type: ignore[import-untyped]

            proc = psutil.Process(os.getpid())
            mem = proc.memory_info()
            rss_mb = mem.rss / (1024 * 1024)
            vms_mb = mem.vms / (1024 * 1024)
        except ImportError:
            rss_mb = 0.0
            vms_mb = 0.0

        gpu_used: float | None = None
        gpu_total: float | None = None
        if self._nvml_available and self._handle is not None:
            try:
                info = self._pynvml.nvmlDeviceGetMemoryInfo(self._handle)
                gpu_used = info.used / (1024 * 1024)
                gpu_total = info.total / (1024 * 1024)
            except Exception:
                pass

        snap = MemorySnapshot(
            process_rss_mb=round(rss_mb, 2),
            process_vms_mb=round(vms_mb, 2),
            gpu_used_mb=round(gpu_used, 2) if gpu_used is not None else None,
            gpu_total_mb=round(gpu_total, 2) if gpu_total is not None else None,
            timestamp=time.monotonic(),
        )
        self._history.append(snap)
        return snap

    @property
    def latest(self) -> MemorySnapshot | None:
        return self._history[-1] if self._history else None

    @property
    def peak_rss_mb(self) -> float:
        return max((s.process_rss_mb for s in self._history), default=0.0)

    @property
    def peak_gpu_mb(self) -> float | None:
        gpu_vals = [s.gpu_used_mb for s in self._history if s.gpu_used_mb is not None]
        return max(gpu_vals) if gpu_vals else None


# ---------------------------------------------------------------------------
# Metrics Registry
# ---------------------------------------------------------------------------

class MetricsRegistry:
    """Central registry for all pipeline metrics with Prometheus export.

    Usage::

        reg = MetricsRegistry()
        lat = reg.create_latency("decode_stage")
        fps = reg.create_throughput("decode_stage")
        lat.record(12.3)
        fps.tick()
        print(reg.prometheus())
    """

    def __init__(self) -> None:
        self._latency: dict[str, LatencyTracker] = {}
        self._throughput: dict[str, ThroughputCounter] = {}
        self._queue_depth: dict[str, QueueDepthMonitor] = {}
        self._memory = MemoryMonitor()
        self._gauges: dict[str, float] = {}
        self._log = logger.bind(component="metrics_registry")

    # -- Factory methods ------------------------------------------------------

    def create_latency(
        self,
        name: str,
        alpha: float = 0.01,
        window: int | None = None,
    ) -> LatencyTracker:
        tracker = LatencyTracker(name, alpha=alpha, window=window)
        self._latency[name] = tracker
        return tracker

    def create_throughput(
        self,
        name: str,
        window_seconds: float = 10.0,
    ) -> ThroughputCounter:
        counter = ThroughputCounter(name, window_seconds=window_seconds)
        self._throughput[name] = counter
        return counter

    def create_queue_depth(
        self,
        name: str,
        window: int = 500,
    ) -> QueueDepthMonitor:
        monitor = QueueDepthMonitor(name, window=window)
        self._queue_depth[name] = monitor
        return monitor

    def set_gauge(self, name: str, value: float) -> None:
        """Set or update an arbitrary gauge metric."""
        self._gauges[name] = value

    # -- Queries --------------------------------------------------------------

    def get_latency(self, name: str) -> LatencyTracker | None:
        return self._latency.get(name)

    def get_throughput(self, name: str) -> ThroughputCounter | None:
        return self._throughput.get(name)

    def get_queue_depth(self, name: str) -> QueueDepthMonitor | None:
        return self._queue_depth.get(name)

    @property
    def memory(self) -> MemoryMonitor:
        return self._memory

    # -- Export ---------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Return a nested dict of all metric summaries."""
        mem_snap = self._memory.snapshot()
        return {
            "latency": {n: t.summary() for n, t in self._latency.items()},
            "throughput": {
                n: {"rate_fps": round(c.rate, 2), "total": c.total}
                for n, c in self._throughput.items()
            },
            "queue_depth": {
                n: m.summary() for n, m in self._queue_depth.items()
            },
            "memory": {
                "process_rss_mb": mem_snap.process_rss_mb,
                "gpu_used_mb": mem_snap.gpu_used_mb,
                "gpu_total_mb": mem_snap.gpu_total_mb,
            },
            "gauges": dict(self._gauges),
        }

    def prometheus(self) -> str:
        """Export all metrics in Prometheus text exposition format."""
        lines: list[str] = []

        # Latency histograms
        for name, tracker in self._latency.items():
            prefix = f"camserv_{name}_latency_ms"
            lines.append(f"# HELP {prefix} Latency in milliseconds")
            lines.append(f"# TYPE {prefix} summary")
            lines.append(f'{prefix}{{quantile="0.5"}} {tracker.p50:.3f}')
            lines.append(f'{prefix}{{quantile="0.95"}} {tracker.p95:.3f}')
            lines.append(f'{prefix}{{quantile="0.99"}} {tracker.p99:.3f}')
            lines.append(f"{prefix}_count {tracker.count}")
            lines.append(f"{prefix}_mean {tracker.mean:.3f}")

        # Throughput gauges
        for name, counter in self._throughput.items():
            prefix = f"camserv_{name}_throughput"
            lines.append(f"# HELP {prefix}_fps Frames per second")
            lines.append(f"# TYPE {prefix}_fps gauge")
            lines.append(f"{prefix}_fps {counter.rate:.2f}")
            lines.append(f"{prefix}_total {counter.total}")

        # Queue depths
        for name, monitor in self._queue_depth.items():
            prefix = f"camserv_{name}_queue"
            lines.append(f"# HELP {prefix}_depth Current queue depth")
            lines.append(f"# TYPE {prefix}_depth gauge")
            lines.append(f"{prefix}_depth {monitor.current}")
            lines.append(f"{prefix}_peak {monitor.peak}")
            lines.append(f"{prefix}_avg {monitor.average:.2f}")

        # Memory
        mem_snap = self._memory.snapshot()
        lines.append("# HELP camserv_memory_rss_mb Process RSS in MB")
        lines.append("# TYPE camserv_memory_rss_mb gauge")
        lines.append(f"camserv_memory_rss_mb {mem_snap.process_rss_mb}")
        if mem_snap.gpu_used_mb is not None:
            lines.append("# HELP camserv_gpu_memory_used_mb GPU VRAM used in MB")
            lines.append("# TYPE camserv_gpu_memory_used_mb gauge")
            lines.append(f"camserv_gpu_memory_used_mb {mem_snap.gpu_used_mb}")
            lines.append(f"camserv_gpu_memory_total_mb {mem_snap.gpu_total_mb}")

        # Gauges
        for name, value in self._gauges.items():
            prefix = f"camserv_{name}"
            lines.append(f"# TYPE {prefix} gauge")
            lines.append(f"{prefix} {value}")

        lines.append("")  # trailing newline
        return "\n".join(lines)

    def reset_all(self) -> None:
        """Reset every tracked metric."""
        for t in self._latency.values():
            t.reset()
        for c in self._throughput.values():
            c.reset()
        for m in self._queue_depth.values():
            m.reset()
        self._gauges.clear()


# ---------------------------------------------------------------------------
# Benchmark harness
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class BenchmarkResult:
    """Outcome of a synthetic benchmark run."""

    stage_name: str
    iterations: int
    total_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    throughput_fps: float


async def run_benchmark(
    stage_name: str,
    work_fn: Any,  # Callable[[], Awaitable[None]]
    iterations: int = 1000,
    warmup: int = 50,
) -> BenchmarkResult:
    """Run *work_fn* for *iterations* and return latency/throughput stats.

    Parameters
    ----------
    stage_name:
        Label for the benchmark.
    work_fn:
        An ``async def`` callable that performs one unit of work.
    iterations:
        Number of timed iterations.
    warmup:
        Number of un-timed warmup iterations.
    """
    log = logger.bind(benchmark=stage_name)
    log.info("benchmark_start", iterations=iterations, warmup=warmup)

    # Warmup
    for _ in range(warmup):
        await work_fn()

    tracker = LatencyTracker(f"bench_{stage_name}")
    t0 = time.monotonic()

    for _ in range(iterations):
        start = time.monotonic()
        await work_fn()
        elapsed_ms = (time.monotonic() - start) * 1000.0
        tracker.record(elapsed_ms)

    total_ms = (time.monotonic() - t0) * 1000.0
    fps = iterations / (total_ms / 1000.0) if total_ms > 0 else 0.0

    result = BenchmarkResult(
        stage_name=stage_name,
        iterations=iterations,
        total_ms=round(total_ms, 2),
        p50_ms=round(tracker.p50, 3),
        p95_ms=round(tracker.p95, 3),
        p99_ms=round(tracker.p99, 3),
        throughput_fps=round(fps, 2),
    )

    log.info(
        "benchmark_complete",
        total_ms=result.total_ms,
        p50=result.p50_ms,
        p95=result.p95_ms,
        p99=result.p99_ms,
        fps=result.throughput_fps,
    )
    return result
