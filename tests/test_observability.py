"""
tests.test_observability
========================

Unit tests for CAMserv platform observability, Prometheus /metrics exposition,
composite health probe aggregation, and sustained memory soak test stability.
"""

from camserv.platform.observability import (
    HealthProbeAggregator,
    MetricType,
    PrometheusMetricsCollector,
)
from scripts.soak_test_harness import SoakTestHarness


def test_prometheus_metrics_registration_and_export():
    """Verify metric recording, labeling, and standard Prometheus text export format."""
    collector = PrometheusMetricsCollector()

    # Set gauges
    collector.set_gauge("camserv_ingestion_fps", 29.8, labels={"camera_id": "cam_gate"})
    collector.set_gauge("camserv_memory_rss_bytes", 256000000)

    # Increment counter
    collector.increment_counter("camserv_dropped_frames_total", 3.0, labels={"camera_id": "cam_gate"})
    collector.increment_counter("camserv_dropped_frames_total", 2.0, labels={"camera_id": "cam_gate"})

    text = collector.export_text_format()

    assert "# HELP camserv_ingestion_fps" in text
    assert "# TYPE camserv_ingestion_fps gauge" in text
    assert 'camserv_ingestion_fps{camera_id="cam_gate"} 29.8' in text

    assert "# HELP camserv_dropped_frames_total" in text
    assert "# TYPE camserv_dropped_frames_total counter" in text
    assert 'camserv_dropped_frames_total{camera_id="cam_gate"} 5.0' in text
    assert "camserv_memory_rss_bytes 256000000.0" in text


def test_health_probe_aggregator_states():
    """Verify UP, DEGRADED, and DOWN states in composite health probe."""
    aggregator = HealthProbeAggregator()

    # All components healthy -> UP
    aggregator.register_subsystem_status("ingestion", is_healthy=True)
    aggregator.register_subsystem_status("inference", is_healthy=True)
    aggregator.register_subsystem_status("storage", is_healthy=True)
    h_up = aggregator.evaluate_overall_health()
    assert h_up["status"] == "UP"
    assert h_up["healthy"] is True
    assert h_up["healthy_components"] == 3

    # One component failure -> DEGRADED
    aggregator.register_subsystem_status("inference", is_healthy=False, details="CUDA OOM")
    h_deg = aggregator.evaluate_overall_health()
    assert h_deg["status"] == "DEGRADED"
    assert h_deg["healthy"] is False

    # All components failure -> DOWN
    aggregator.register_subsystem_status("ingestion", is_healthy=False)
    aggregator.register_subsystem_status("storage", is_healthy=False)
    h_down = aggregator.evaluate_overall_health()
    assert h_down["status"] == "DOWN"
    assert h_down["healthy_components"] == 0


def test_soak_test_harness_memory_stability():
    """Verify that continuous frame ring buffer processing maintains memory stability without leaks."""
    harness = SoakTestHarness(frame_count=300, resolution=(320, 240))
    results = harness.run_simulation()

    assert results["processed_frames"] == 300
    assert results["effective_fps"] > 50.0  # Fast in-memory processing
    assert results["is_memory_stable"] is True
    assert results["peak_memory_kb"] > 0.0
