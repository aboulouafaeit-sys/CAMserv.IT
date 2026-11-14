"""
tests.test_adaptive_scheduler
==============================

Unit and multi-stream scenario tests for AdaptiveSamplingScheduler (Condition C4).
"""

import time
import pytest

from camserv.pipeline.adaptive_scheduler import (
    AdaptiveSamplingScheduler,
    SchedulerConfig,
    SamplingTier,
)


def test_scheduler_baseline_sampling_rate() -> None:
    """Verify default quiescent stream samples at 5.0 FPS from a 30 FPS feed."""
    config = SchedulerConfig(baseline_fps=5.0, burst_fps=30.0)
    scheduler = AdaptiveSamplingScheduler(config)
    scheduler.register_stream("cam-test-01")

    # Simulate 1 second of 30 FPS ingestion (30 frames, dt = 1/30s = 0.0333s)
    t = 1000.0
    dt = 1.0 / 30.0
    sampled_count = 0

    for _ in range(30):
        if scheduler.should_sample("cam-test-01", frame_timestamp=t):
            sampled_count += 1
        t += dt

    # At 5 FPS in 1 second, expected samples is 5 or 6 (sampling interval ~0.20s)
    assert 4 <= sampled_count <= 6, f"Expected ~5 sampled frames at baseline, got {sampled_count}"
    tel = scheduler.telemetry()
    assert tel["streams"]["cam-test-01"]["tier"] == SamplingTier.BASELINE.value
    assert tel["streams"]["cam-test-01"]["sampled"] == sampled_count
    assert tel["streams"]["cam-test-01"]["skipped"] == 30 - sampled_count


def test_scheduler_threat_elevation_to_burst() -> None:
    """Verify threat score >= 70 immediately elevates camera to 30.0 FPS burst."""
    config = SchedulerConfig(baseline_fps=5.0, burst_fps=30.0, threat_threshold=70.0)
    scheduler = AdaptiveSamplingScheduler(config)
    scheduler.register_stream("cam-threat-01")

    t = 2000.0
    assert scheduler.telemetry()["streams"]["cam-threat-01"]["effective_fps"] == 5.0

    # Elevate threat to 75
    scheduler.update_threat_score("cam-threat-01", 75.0, current_time=t)
    tel = scheduler.telemetry()
    assert tel["streams"]["cam-threat-01"]["tier"] == SamplingTier.BURST.value
    assert tel["streams"]["cam-threat-01"]["effective_fps"] == 30.0

    # Simulate 1 second of 30 FPS ingestion during burst
    dt = 1.0 / 30.0
    sampled_count = 0
    for _ in range(30):
        if scheduler.should_sample("cam-threat-01", frame_timestamp=t):
            sampled_count += 1
        t += dt

    # At 30 FPS burst, every frame is sampled
    assert sampled_count >= 28, f"Expected >=28 sampled frames in burst, got {sampled_count}"


def test_scheduler_hysteresis_and_cooldown_decay() -> None:
    """Verify burst persists during cooldown window and then decays to baseline."""
    config = SchedulerConfig(baseline_fps=5.0, burst_fps=30.0, cooldown_seconds=3.0)
    scheduler = AdaptiveSamplingScheduler(config)
    scheduler.register_stream("cam-cool-01")

    t0 = 5000.0
    scheduler.trigger_incident("cam-cool-01", current_time=t0)
    assert scheduler.telemetry()["streams"]["cam-cool-01"]["tier"] == SamplingTier.BURST.value

    # Threat drops to 0 immediately at t0 + 1.0s
    scheduler.update_threat_score("cam-cool-01", 0.0, current_time=t0 + 1.0)
    # At t0 + 2.0s (< 3.0s cooldown), burst should STILL be active (hysteresis)
    scheduler.should_sample("cam-cool-01", frame_timestamp=t0 + 2.0)
    assert scheduler.telemetry()["streams"]["cam-cool-01"]["tier"] == SamplingTier.BURST.value

    # At t0 + 4.5s (> 3.0s cooldown), burst should decay back to baseline
    scheduler.should_sample("cam-cool-01", frame_timestamp=t0 + 4.5)
    assert scheduler.telemetry()["streams"]["cam-cool-01"]["tier"] == SamplingTier.BASELINE.value
    assert scheduler.telemetry()["streams"]["cam-cool-01"]["effective_fps"] == 5.0


def test_16_camera_fair_share_capacity_governor() -> None:
    """Verify 16-camera appliance stays within max_system_fps_budget under concurrent bursts."""
    # 16 cameras * 5 FPS baseline = 80 FPS
    # Budget = 140 FPS (cannot accommodate 3 concurrent bursts of 30 FPS without throttling)
    config = SchedulerConfig(
        baseline_fps=5.0,
        burst_fps=30.0,
        max_system_fps_budget=140.0,
        min_stream_fps=2.0,
    )
    scheduler = AdaptiveSamplingScheduler(config)

    # Register 16 cameras
    camera_ids = [f"cam-{i:02d}" for i in range(1, 17)]
    for cid in camera_ids:
        scheduler.register_stream(cid)

    tel = scheduler.telemetry()
    assert tel["stream_count"] == 16
    assert tel["aggregate_analytical_fps"] == 80.0  # 16 * 5 = 80
    assert tel["headroom_fps"] == 60.0

    # Trigger concurrent incidents on 4 cameras simultaneously
    t = 10000.0
    for cid in camera_ids[:4]:
        scheduler.trigger_incident(cid, current_time=t)

    tel_burst = scheduler.telemetry()
    # Unconstrained demand would be 4 * 30 + 12 * 5 = 180 FPS > 140 FPS budget
    # Fair share governor must cap total to <= 140.0
    assert tel_burst["aggregate_analytical_fps"] <= 140.01
    assert tel_burst["headroom_fps"] >= 0.0

    # Quiescent cameras must NOT be starved (must maintain >= min_stream_fps)
    for cid in camera_ids[4:]:
        assert tel_burst["streams"][cid]["effective_fps"] >= 2.0

    # Burst cameras receive highest priority allocation
    for cid in camera_ids[:4]:
        assert tel_burst["streams"][cid]["effective_fps"] > tel_burst["streams"][camera_ids[5]]["effective_fps"]
