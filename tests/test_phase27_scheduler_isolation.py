"""
tests/test_phase27_scheduler_isolation.py
=========================================

Verification of AIResourceScheduler: Priority enforcement, admission control,
dynamic frame rate reduction, worker timeout, and failure isolation guaranteeing
that recording cannot be starved, interrupted, or crashed by AI tasks.
"""

import time
import pytest

from camserv.intelligence.contracts import (
    HardwareOperatingTier,
    IntelligencePriority,
)
from camserv.intelligence.scheduler import (
    AIResourceScheduler,
    TIER_BUDGETS,
)


@pytest.mark.unit
def test_tier_budget_specifications() -> None:
    """Verify tier budgets allocate appropriate concurrency and sampling parameters."""
    tier_a = TIER_BUDGETS[HardwareOperatingTier.TIER_A_CPU_LOW]
    assert tier_a.max_concurrent_inferences == 1
    assert tier_a.anpr_permitted is False  # ANPR prohibited on low-power CPU tier

    tier_c = TIER_BUDGETS[HardwareOperatingTier.TIER_C_MODERATE_DGPU]
    assert tier_c.max_concurrent_inferences >= 4
    assert tier_c.anpr_permitted is True


@pytest.mark.unit
def test_scheduler_admission_control_under_critical_pressure() -> None:
    """
    CRITICAL RECORDING ISOLATION:
    When host enters CRITICAL state (CPU >= 90% or RAM >= 90%), all AI tasks
    MUST be shed to prevent recording starvation.
    """
    scheduler = AIResourceScheduler(initial_tier=HardwareOperatingTier.TIER_A_CPU_LOW)

    # Simulate 95% CPU pressure
    scheduler.update_host_pressure(cpu_percent=95.0, ram_percent=40.0)
    assert scheduler.metrics.current_state == "CRITICAL"

    # Admission must be rejected
    admitted = scheduler.check_admission("cam-01", priority=IntelligencePriority.AI_ANALYTICS)
    assert admitted is False
    assert scheduler.metrics.total_shed == 1

    # Dynamic sampling rate must drop to 0 FPS
    assert scheduler.calculate_sampling_rate("cam-01") == 0.0


@pytest.mark.unit
def test_scheduler_degraded_state_sheds_expensive_analysis() -> None:
    """Verify degraded state sheds heavy tasks (ANPR / Priority 7) while permitting standard AI."""
    scheduler = AIResourceScheduler(initial_tier=HardwareOperatingTier.TIER_B_IGPU_NPU)
    scheduler.update_host_pressure(cpu_percent=78.0, ram_percent=50.0)
    assert scheduler.metrics.current_state == "DEGRADED"

    # Priority 7 (ANPR) should be shed
    anpr_admitted = scheduler.check_admission("cam-01", priority=IntelligencePriority.EXPENSIVE_ANALYSIS)
    assert anpr_admitted is False

    # Priority 6 (Standard AI) can be admitted if concurrency permits
    standard_admitted = scheduler.check_admission("cam-01", priority=IntelligencePriority.AI_ANALYTICS)
    assert standard_admitted is True


@pytest.mark.unit
def test_worker_failure_isolation() -> None:
    """
    TOTAL FAILURE ISOLATION:
    Verify that an AI worker raising an unhandled exception does NOT crash the caller
    or disrupt host operation.
    """
    scheduler = AIResourceScheduler()

    def crashing_task() -> None:
        raise RuntimeError("Simulated severe neural model crash / CUDA OOM")

    result, success, error_msg = scheduler.execute_isolated(
        camera_id="cam-01",
        task_callable=crashing_task,
        fallback_value="SAFE_FALLBACK",
    )

    assert success is False
    assert result == "SAFE_FALLBACK"
    assert "WORKER_ERROR: RuntimeError" in error_msg
    assert scheduler.metrics.total_worker_errors == 1


@pytest.mark.unit
def test_worker_execution_timeout() -> None:
    """Verify worker exceeding execution timeout is cleanly cancelled and isolated."""
    scheduler = AIResourceScheduler(worker_timeout_sec=0.2)

    def stalling_task() -> None:
        time.sleep(1.0)  # Exceeds 0.2s timeout

    result, success, error_msg = scheduler.execute_isolated(
        camera_id="cam-01",
        task_callable=stalling_task,
        fallback_value="TIMEOUT_FALLBACK",
    )

    assert success is False
    assert result == "TIMEOUT_FALLBACK"
    assert error_msg == "WORKER_TIMEOUT_EXCEEDED"
    assert scheduler.metrics.total_timeouts == 1
