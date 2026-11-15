"""
camserv.platform.observability
==============================

Deep diagnostic telemetry, Prometheus /metrics exposition, OpenTelemetry trace context,
and composite health probe aggregation for enterprise CAMserv deployments.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class MetricType(str, enum.Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass(slots=True)
class MetricDefinition:
    name: str
    help_text: str
    metric_type: MetricType
    values: dict[str, float] = field(default_factory=dict)  # label_key -> value


class PrometheusMetricsCollector:
    """
    Standard Prometheus /metrics exporter formatting metrics into the official
    text-based OpenMetrics exposition format.
    """

    def __init__(self) -> None:
        self.metrics: dict[str, MetricDefinition] = {}
        self._init_standard_metrics()

    def _init_standard_metrics(self) -> None:
        """Initialize standard platform telemetry metrics."""
        self.register_metric("camserv_ingestion_fps", "Current camera ingestion frame rate", MetricType.GAUGE)
        self.register_metric("camserv_inference_latency_ms", "Neural inference duration percentiles", MetricType.GAUGE)
        self.register_metric("camserv_dropped_frames_total", "Total frames dropped due to backpressure", MetricType.COUNTER)
        self.register_metric("camserv_active_tracks", "Current confirmed anonymous multi-object tracks", MetricType.GAUGE)
        self.register_metric("camserv_privacy_blackout_total", "Total full-frame fail-closed blackouts triggered", MetricType.COUNTER)
        self.register_metric("camserv_memory_rss_bytes", "Resident Set Size memory consumption in bytes", MetricType.GAUGE)
        self.register_metric("camserv_storage_free_bytes", "Available disk capacity in bytes", MetricType.GAUGE)
        self.register_metric("camserv_gpu_temperature_celsius", "Primary hardware accelerator die temperature", MetricType.GAUGE)

    def register_metric(self, name: str, help_text: str, metric_type: MetricType) -> None:
        """Register a new metric definition."""
        self.metrics[name] = MetricDefinition(name=name, help_text=help_text, metric_type=metric_type)

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Set the value of a gauge metric with optional labels."""
        if name in self.metrics:
            label_str = self._format_labels(labels or {})
            self.metrics[name].values[label_str] = float(value)

    def increment_counter(self, name: str, value: float = 1.0, labels: dict[str, str] | None = None) -> None:
        """Increment a counter metric."""
        if name in self.metrics:
            label_str = self._format_labels(labels or {})
            curr = self.metrics[name].values.get(label_str, 0.0)
            self.metrics[name].values[label_str] = curr + value

    def export_text_format(self) -> str:
        """Format all registered metrics into Prometheus text format."""
        lines: list[str] = []
        for name, m in sorted(self.metrics.items()):
            lines.append(f"# HELP {name} {m.help_text}")
            lines.append(f"# TYPE {name} {m.metric_type.value}")
            if not m.values:
                lines.append(f"{name} 0.0")
            else:
                for lbl, val in sorted(m.values.items()):
                    if lbl:
                        lines.append(f"{name}{lbl} {val}")
                    else:
                        lines.append(f"{name} {val}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _format_labels(labels: dict[str, str]) -> str:
        if not labels:
            return ""
        items = [f'{k}="{v}"' for k, v in sorted(labels.items())]
        return "{" + ",".join(items) + "}"


class HealthProbeAggregator:
    """
    Evaluates composite system health across ingestion, inference,
    storage, privacy, and network subsystems.
    """

    def __init__(self) -> None:
        self.subsystem_probes: dict[str, Any] = {}

    def register_subsystem_status(self, name: str, is_healthy: bool, details: str = "Nominal") -> None:
        """Record status of a subsystem probe."""
        self.subsystem_probes[name] = {
            "healthy": is_healthy,
            "details": details,
            "checked_at": time.time(),
        }

    def evaluate_overall_health(self) -> dict[str, Any]:
        """Determine overall platform health status (UP, DEGRADED, DOWN)."""
        if not self.subsystem_probes:
            return {"status": "INITIALIZING", "healthy": True, "components": {}}

        total = len(self.subsystem_probes)
        healthy_count = sum(1 for p in self.subsystem_probes.values() if p["healthy"])

        if healthy_count == total:
            status = "UP"
        elif healthy_count > 0:
            status = "DEGRADED"
        else:
            status = "DOWN"

        return {
            "status": status,
            "healthy": (status == "UP"),
            "healthy_components": healthy_count,
            "total_components": total,
            "components": self.subsystem_probes,
        }
