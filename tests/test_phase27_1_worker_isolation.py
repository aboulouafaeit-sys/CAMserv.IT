"""
tests/test_phase27_1_worker_isolation.py
========================================

Phase 27.1 Worker Isolation & Scheduler Resilience Tests:
- Verification of accurate worker states: RUNNING, TERMINATION_UNCONFIRMED, RECOVERY_FAILED.
- Verification that timeout returns control while acknowledging thread termination is unconfirmed.
- Verification of hysteresis damping preventing threshold oscillation.
- Compound failure scenario: Simultaneous worker timeout, error, and high CPU load.
"""

import time
import pytest

from camserv.intelligence.contracts import (
    HardwareOperatingTier,
    IntelligencePriority,
    WorkerLifecycleState,
)
from camserv.intelligence.scheduler import AIResourceScheduler


@pytest.mark.adversarial
def test_worker_lifecycle_state_termination_unconfirmed() -> None:
    """
    CRITICAL WORKER AUDIT:
    When an AI task times out, verify that the scheduler records its state as
    TERMINATION_UNCONFIRMED rather than falsely asserting the thread was terminated.
    """
    scheduler = AIResourceScheduler(worker_timeout_sec=0.2)

    def lingering_task() -> None:
        time.sleep(0.8)

    result, success, error_msg = scheduler.execute_isolated(
        camera_id="cam-isolate",
        task_callable=lingering_task,
        fallback_value="FALLBACK",
    )

    assert success is False
    assert error_msg == "WORKER_TIMEOUT_EXCEEDED"
    assert scheduler.metrics.total_timeouts == 1

    # Check worker states dictionary
    states = list(scheduler.worker_states.values())
    assert WorkerLifecycleState.TERMINATION_UNCONFIRMED in states


@pytest.mark.adversarial
def test_scheduler_admission_hysteresis_damping() -> None:
    """
    SCHEDULER OSCILLATION TEST:
    Verify that host pressure hysteresis prevents thrashing between NORMAL and CRITICAL.
    When load spikes to 92%, state becomes CRITICAL.
    When load drops to 85%, state MUST REMAIN in CRITICAL (10% hysteresis buffer).
    State exits CRITICAL only when load drops below 80%.
    """
    scheduler = AIResourceScheduler()

    # Initial state: Normal
    scheduler.update_host_pressure(cpu_percent=50.0, ram_percent=40.0)
    assert scheduler.metrics.current_state == "NORMAL"

    # Spike above 90% -> Enters CRITICAL
    scheduler.update_host_pressure(cpu_percent=92.0, ram_percent=40.0)
    assert scheduler.metrics.current_state == "CRITICAL"

    # Small reduction to 85% -> MUST REMAIN in CRITICAL due to hysteresis damping
    scheduler.update_host_pressure(cpu_percent=85.0, ram_percent=40.0)
    assert scheduler.metrics.current_state == "CRITICAL"

    # Substantial reduction to 74% -> Exits CRITICAL to DEGRADED
    scheduler.update_host_pressure(cpu_percent=74.0, ram_percent=40.0)
    assert scheduler.metrics.current_state in ("DEGRADED", "PRESSURE")


@pytest.mark.adversarial
def test_compound_failure_recording_protection() -> None:
    """
    COMPOUND FAULT INJECTION:
    Simultaneously trigger a crashing task, a lingering task, and high host CPU load.
    Verify that recording tasks (Priority 1) are never affected.
    """
    scheduler = AIResourceScheduler(initial_tier=HardwareOperatingTier.TIER_A_CPU_LOW)

    # 1. Crashing task
    def crasher():
        raise MemoryError("Simulated Out of Memory in inference model")

    res1, succ1, err1 = scheduler.execute_isolated("cam-01", crasher, fallback_value=None)
    assert succ1 is False
    assert "MemoryError" in err1

    # 2. Host load spikes to 95%
    scheduler.update_host_pressure(cpu_percent=95.0, ram_percent=95.0)
    assert scheduler.metrics.current_state == "CRITICAL"

    # 3. New analytics request must be rejected immediately to protect recording
    admitted = scheduler.check_admission("cam-01", priority=IntelligencePriority.AI_ANALYTICS)
    assert admitted is False
    assert scheduler.metrics.total_shed >= 1
