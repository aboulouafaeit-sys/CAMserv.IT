"""
camserv.intelligence.scheduler
==============================

Hardware-Adaptive AI Resource Scheduler & Failure Isolation Supervisor.

Enforces:
- Non-negotiable priority order: Recording (#1) must NEVER be starved by AI (#6/7).
- Tier-based resource budgets (Tier A CPU, Tier B iGPU/NPU, Tier C dGPU, Tier D Server).
- Admission control based on CPU, RAM, thermal load, and queue depth.
- Dynamic frame sampling and automatic workload reduction under pressure.
- Total failure isolation: Worker crashes, timeouts, or OOM cannot touch recording.
"""

from __future__ import annotations

import collections
import concurrent.futures
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from camserv.intelligence.contracts import (
    BoundingBox,
    DetectionPrediction,
    EngineHealthStatus,
    HardwareOperatingTier,
    IntelligencePriority,
    WorkerLifecycleState,
)
from camserv.intelligence.process_worker import ProcessIsolatedInferenceSupervisor

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Admission & Budget Exceptions
# ---------------------------------------------------------------------------

class ResourceAdmissionError(Exception):
    """Raised when an AI workload is shed due to host resource pressure."""


class WorkerExecutionTimeoutError(Exception):
    """Raised when an AI worker exceeds its maximum allowed execution timeout."""


# ---------------------------------------------------------------------------
# Resource Profile & Metrics Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class TierBudget:
    """Operational parameters allocated to each hardware tier."""

    tier: HardwareOperatingTier
    max_concurrent_inferences: int
    max_queue_depth_per_cam: int
    default_sampling_fps: float
    min_sampling_fps: float
    anpr_permitted: bool
    heavy_analytics_permitted: bool


TIER_BUDGETS: dict[HardwareOperatingTier, TierBudget] = {
    HardwareOperatingTier.TIER_A_CPU_LOW: TierBudget(
        tier=HardwareOperatingTier.TIER_A_CPU_LOW,
        max_concurrent_inferences=1,
        max_queue_depth_per_cam=4,
        default_sampling_fps=2.0,
        min_sampling_fps=0.5,
        anpr_permitted=False,
        heavy_analytics_permitted=False,
    ),
    HardwareOperatingTier.TIER_B_IGPU_NPU: TierBudget(
        tier=HardwareOperatingTier.TIER_B_IGPU_NPU,
        max_concurrent_inferences=2,
        max_queue_depth_per_cam=8,
        default_sampling_fps=4.0,
        min_sampling_fps=1.0,
        anpr_permitted=True,
        heavy_analytics_permitted=False,
    ),
    HardwareOperatingTier.TIER_C_MODERATE_DGPU: TierBudget(
        tier=HardwareOperatingTier.TIER_C_MODERATE_DGPU,
        max_concurrent_inferences=4,
        max_queue_depth_per_cam=16,
        default_sampling_fps=8.0,
        min_sampling_fps=2.0,
        anpr_permitted=True,
        heavy_analytics_permitted=True,
    ),
    HardwareOperatingTier.TIER_D_HIGH_PERF_SERVER: TierBudget(
        tier=HardwareOperatingTier.TIER_D_HIGH_PERF_SERVER,
        max_concurrent_inferences=8,
        max_queue_depth_per_cam=32,
        default_sampling_fps=15.0,
        min_sampling_fps=5.0,
        anpr_permitted=True,
        heavy_analytics_permitted=True,
    ),
}


@dataclass(slots=True)
class SchedulerMetrics:
    """Real-time performance and shedding telemetry."""

    total_submitted: int = 0
    total_completed: int = 0
    total_shed: int = 0
    total_timeouts: int = 0
    total_worker_errors: int = 0
    active_inferences: int = 0
    current_tier: HardwareOperatingTier = HardwareOperatingTier.TIER_A_CPU_LOW
    current_state: str = "NORMAL"  # NORMAL, PRESSURE, DEGRADED, CRITICAL


# ---------------------------------------------------------------------------
# AI Resource Scheduler
# ---------------------------------------------------------------------------

class AIResourceScheduler:
    """
    Supervises AI task submission, enforces admission control, isolates worker
    failures, and prevents resource starvation of the primary recording engine.
    """

    def __init__(
        self,
        initial_tier: HardwareOperatingTier = HardwareOperatingTier.TIER_A_CPU_LOW,
        worker_timeout_sec: float = 2.0,
    ) -> None:
        self._tier = initial_tier
        self._budget = TIER_BUDGETS[initial_tier]
        self._worker_timeout_sec = worker_timeout_sec
        self._lock = threading.RLock()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max(2, self._budget.max_concurrent_inferences + 1),
            thread_name_prefix="camserv_ai_worker",
        )

        self._active_tasks = 0
        self._camera_queues: dict[str, collections.deque[float]] = {}
        self._worker_states: dict[str, WorkerLifecycleState] = {}
        self._supervisors: dict[str, ProcessIsolatedInferenceSupervisor] = {}
        self._next_worker_id: int = 1
        self._metrics = SchedulerMetrics(current_tier=self._tier)

        # External host load overrides (from AdaptiveResourceManager or platform probers)
        self._cpu_pressure_percent: float = 20.0
        self._ram_pressure_percent: float = 30.0
        self._thermal_throttling_active: bool = False
        self._recording_active: bool = True

    @property
    def current_tier(self) -> HardwareOperatingTier:
        with self._lock:
            return self._tier

    @property
    def worker_states(self) -> dict[str, WorkerLifecycleState]:
        with self._lock:
            return dict(self._worker_states)

    def get_worker_state(self, worker_id: str) -> WorkerLifecycleState | None:
        with self._lock:
            return self._worker_states.get(worker_id)

    @property
    def metrics(self) -> SchedulerMetrics:
        with self._lock:
            return SchedulerMetrics(
                total_submitted=self._metrics.total_submitted,
                total_completed=self._metrics.total_completed,
                total_shed=self._metrics.total_shed,
                total_timeouts=self._metrics.total_timeouts,
                total_worker_errors=self._metrics.total_worker_errors,
                active_inferences=self._active_tasks,
                current_tier=self._tier,
                current_state=self._metrics.current_state,
            )

    def set_hardware_tier(self, tier: HardwareOperatingTier) -> None:
        """Dynamically adjust operational budget to match detected hardware tier."""
        with self._lock:
            self._tier = tier
            self._budget = TIER_BUDGETS[tier]
            self._metrics.current_tier = tier

    def update_host_pressure(
        self,
        cpu_percent: float,
        ram_percent: float,
        thermal_throttling: bool = False,
    ) -> None:
        """
        Update host telemetry to inform admission control with hysteresis damping
        to prevent rapid threshold oscillation.
        """
        with self._lock:
            self._cpu_pressure_percent = cpu_percent
            self._ram_pressure_percent = ram_percent
            self._thermal_throttling_active = thermal_throttling

            current = self._metrics.current_state

            # Hysteresis damping to prevent rapid threshold oscillation
            if cpu_percent >= 90.0 or ram_percent >= 90.0:
                self._metrics.current_state = "CRITICAL"
            elif current == "CRITICAL" and (cpu_percent >= 80.0 or ram_percent >= 80.0):
                # Remain in CRITICAL until load drops below 80% (10% hysteresis buffer)
                self._metrics.current_state = "CRITICAL"
            elif cpu_percent >= 75.0 or ram_percent >= 80.0 or thermal_throttling:
                self._metrics.current_state = "DEGRADED"
            elif current == "DEGRADED" and (cpu_percent >= 68.0 or ram_percent >= 72.0):
                # Remain in DEGRADED until load drops below 68%
                self._metrics.current_state = "DEGRADED"
            elif cpu_percent >= 60.0:
                self._metrics.current_state = "PRESSURE"
            elif current == "PRESSURE" and cpu_percent >= 52.0:
                self._metrics.current_state = "PRESSURE"
            else:
                self._metrics.current_state = "NORMAL"

    def calculate_sampling_rate(self, camera_id: str) -> float:
        """Compute the dynamic FPS sampling rate based on host pressure."""
        with self._lock:
            state = self._metrics.current_state
            if state == "CRITICAL":
                return 0.0  # Suspend inference entirely to protect recording
            elif state == "DEGRADED":
                return self._budget.min_sampling_fps
            elif state == "PRESSURE":
                return (self._budget.default_sampling_fps + self._budget.min_sampling_fps) / 2.0
            return self._budget.default_sampling_fps

    def check_admission(
        self,
        camera_id: str,
        priority: IntelligencePriority = IntelligencePriority.AI_ANALYTICS,
    ) -> bool:
        """
        Evaluate whether an intelligence task is admitted or must be shed.
        Higher priority numbers (e.g. 7 - Heavy/ANPR) are shed first.
        """
        with self._lock:
            self._metrics.total_submitted += 1

            # 1. Critical host condition: shed all AI analytics to preserve recording
            if self._metrics.current_state == "CRITICAL":
                self._metrics.total_shed += 1
                return False

            # 2. Degraded state: shed optional heavy tasks (ANPR / secondary models)
            if self._metrics.current_state == "DEGRADED" and priority >= IntelligencePriority.EXPENSIVE_ANALYSIS:
                self._metrics.total_shed += 1
                return False

            # 3. Concurrency budget check
            if self._active_tasks >= self._budget.max_concurrent_inferences:
                self._metrics.total_shed += 1
                return False

            # 4. Per-camera bounded queue depth check
            queue = self._camera_queues.setdefault(camera_id, collections.deque(maxlen=self._budget.max_queue_depth_per_cam))
            if len(queue) >= self._budget.max_queue_depth_per_cam:
                self._metrics.total_shed += 1
                return False

            queue.append(time.time())
            return True

    def execute_isolated(
        self,
        camera_id: str,
        task_callable: Callable[..., T],
        *args: Any,
        priority: IntelligencePriority = IntelligencePriority.AI_ANALYTICS,
        timeout_override_sec: float | None = None,
        fallback_value: T | None = None,
        **kwargs: Any,
    ) -> tuple[T | None, bool, str]:
        """
        Execute an intelligence task with complete failure isolation.
        Returns: (result, success, error_message).
        Guarantees that no exception, crash, or timeout can propagate to recording.
        """
        if not self.check_admission(camera_id, priority):
            return fallback_value, False, "RESOURCE_ADMISSION_REJECTED"

        with self._lock:
            worker_id = f"worker_{self._next_worker_id}"
            self._next_worker_id += 1
            self._worker_states[worker_id] = WorkerLifecycleState.RUNNING
            self._active_tasks += 1

        timeout = timeout_override_sec or self._worker_timeout_sec
        future = self._executor.submit(task_callable, *args, **kwargs)

        try:
            result = future.result(timeout=timeout)
            with self._lock:
                self._metrics.total_completed += 1
                self._worker_states[worker_id] = WorkerLifecycleState.TERMINATED
            return result, True, "SUCCESS"
        except concurrent.futures.TimeoutError:
            with self._lock:
                self._metrics.total_timeouts += 1
                # ThreadPoolExecutor cannot forcibly kill a running thread; state is unconfirmed termination
                self._worker_states[worker_id] = WorkerLifecycleState.TERMINATION_UNCONFIRMED
            return fallback_value, False, "WORKER_TIMEOUT_EXCEEDED"
        except Exception as exc:
            with self._lock:
                self._metrics.total_worker_errors += 1
                self._worker_states[worker_id] = WorkerLifecycleState.RECOVERY_FAILED
            return fallback_value, False, f"WORKER_ERROR: {type(exc).__name__}: {str(exc)}"
        finally:
            with self._lock:
                self._active_tasks = max(0, self._active_tasks - 1)
                queue = self._camera_queues.get(camera_id)
                if queue and len(queue) > 0:
                    queue.popleft()

    def get_or_create_process_supervisor(
        self,
        camera_id: str,
    ) -> ProcessIsolatedInferenceSupervisor:
        """Retrieve or initialize a dedicated process-isolated supervisor for a camera."""
        with self._lock:
            if camera_id not in self._supervisors:
                self._supervisors[camera_id] = ProcessIsolatedInferenceSupervisor(
                    worker_id=f"proc_{camera_id}_{len(self._supervisors) + 1}",
                    task_timeout_sec=self._worker_timeout_sec,
                    auto_restart=True,
                )
            return self._supervisors[camera_id]

    def execute_process_isolated(
        self,
        camera_id: str,
        frame: Any,
        frame_id: int = 0,
        priority: IntelligencePriority = IntelligencePriority.AI_ANALYTICS,
        timeout_override_sec: float | None = None,
        fallback_value: list[DetectionPrediction] | None = None,
    ) -> tuple[list[DetectionPrediction], bool, str]:
        """
        Execute visual inference in a separate OS process with true OS process termination.
        Guarantees that hung native execution can be forcefully terminated at the OS process level.
        """
        if not self.check_admission(camera_id, priority):
            return fallback_value or [], False, "RESOURCE_ADMISSION_REJECTED"

        supervisor = self.get_or_create_process_supervisor(camera_id)
        worker_id = supervisor.worker_id

        with self._lock:
            self._worker_states[worker_id] = supervisor.state
            self._active_tasks += 1

        timeout = timeout_override_sec or self._worker_timeout_sec
        try:
            preds, success, msg = supervisor.submit_and_wait(
                frame=frame,
                camera_id=camera_id,
                frame_id=frame_id,
                timeout_sec=timeout,
            )
            with self._lock:
                self._worker_states[worker_id] = supervisor.state
                if success:
                    self._metrics.total_completed += 1
                elif "TIMEOUT" in msg:
                    self._metrics.total_timeouts += 1
                else:
                    self._metrics.total_worker_errors += 1
            return (preds if success else (fallback_value or [])), success, msg
        except Exception as exc:
            with self._lock:
                self._metrics.total_worker_errors += 1
                self._worker_states[worker_id] = WorkerLifecycleState.RECOVERY_FAILED
            return (
                fallback_value or [],
                False,
                f"PROCESS_WORKER_ERROR: {type(exc).__name__}: {str(exc)}",
            )
        finally:
            with self._lock:
                self._active_tasks = max(0, self._active_tasks - 1)
                queue = self._camera_queues.get(camera_id)
                if queue and len(queue) > 0:
                    queue.popleft()

    def shutdown(self, wait: bool = True) -> None:
        """Safely terminate scheduler workers and all isolated process supervisors."""
        with self._lock:
            for sup in self._supervisors.values():
                sup.shutdown()
            self._supervisors.clear()
        self._executor.shutdown(wait=wait)
