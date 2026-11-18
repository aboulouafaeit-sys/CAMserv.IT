"""
camserv.intelligence.health
===========================

Intelligence Health Monitor & Latency Telemetry.

Features:
- Real-time engine health state monitoring (ACTIVE, AVAILABLE, LIMITED, DEGRADED, etc.).
- Thread-safe sliding window latency tracker (P50, P95, P99, average, and FPS).
- Drop and error counters for backpressure tracking.
- Web Console & API-compatible health status summary.
"""

from __future__ import annotations

import collections
import math
import threading
import time
from typing import Any

from camserv.intelligence.contracts import EngineHealthStatus


class IntelligenceHealthMonitor:
    """
    Collects performance, latency percentiles, error rates, and operational
    health states across all intelligence engines.
    """

    def __init__(self, max_samples: int = 500) -> None:
        self._max_samples = max_samples
        self._lock = threading.RLock()
        self._latencies: collections.deque[float] = collections.deque(maxlen=max_samples)
        self._engine_states: dict[str, EngineHealthStatus] = {}
        self._total_inferences = 0
        self._dropped_frames = 0
        self._error_count = 0
        self._start_time = time.monotonic()

    def record_engine_status(self, engine_name: str, status: EngineHealthStatus) -> None:
        """Register the current operational state of a named engine."""
        with self._lock:
            self._engine_states[engine_name] = status

    def record_latency(self, latency_ms: float) -> None:
        """Record an inference latency observation in milliseconds."""
        with self._lock:
            self._latencies.append(latency_ms)
            self._total_inferences += 1

    def record_drop(self) -> None:
        """Record a dropped inference request due to backpressure."""
        with self._lock:
            self._dropped_frames += 1

    def record_error(self) -> None:
        """Record an engine or worker execution error."""
        with self._lock:
            self._error_count += 1

    def _percentile(self, p: float) -> float:
        """Compute the p-th percentile from recorded latency window."""
        with self._lock:
            if not self._latencies:
                return 0.0
            sorted_samples = sorted(self._latencies)
            idx = int(math.ceil((p / 100.0) * len(sorted_samples))) - 1
            idx = max(0, min(idx, len(sorted_samples) - 1))
            return float(sorted_samples[idx])

    @property
    def p50_ms(self) -> float:
        return self._percentile(50.0)

    @property
    def p95_ms(self) -> float:
        return self._percentile(95.0)

    @property
    def p99_ms(self) -> float:
        return self._percentile(99.0)

    @property
    def avg_ms(self) -> float:
        with self._lock:
            if not self._latencies:
                return 0.0
            return float(sum(self._latencies) / len(self._latencies))

    @property
    def effective_fps(self) -> float:
        with self._lock:
            elapsed = time.monotonic() - self._start_time
            if elapsed <= 0 or self._total_inferences == 0:
                return 0.0
            return float(self._total_inferences / elapsed)

    def get_summary(self) -> dict[str, Any]:
        """Generate a structured health report for dashboards and telemetry."""
        with self._lock:
            # Overall subsystem health is degraded if any critical engine is degraded
            overall_status = EngineHealthStatus.ACTIVE
            for st in self._engine_states.values():
                if st == EngineHealthStatus.DEGRADED:
                    overall_status = EngineHealthStatus.DEGRADED
                    break
                elif st == EngineHealthStatus.LIMITED and overall_status != EngineHealthStatus.DEGRADED:
                    overall_status = EngineHealthStatus.LIMITED

            return {
                "overall_status": overall_status.value,
                "engine_states": {name: st.value for name, st in self._engine_states.items()},
                "p50_ms": round(self.p50_ms, 2),
                "p95_ms": round(self.p95_ms, 2),
                "p99_ms": round(self.p99_ms, 2),
                "avg_ms": round(self.avg_ms, 2),
                "effective_fps": round(self.effective_fps, 2),
                "total_inferences": self._total_inferences,
                "dropped_frames": self._dropped_frames,
                "error_count": self._error_count,
            }
