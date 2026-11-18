"""
camserv.intelligence.process_worker
===================================

Process-Isolated AI Inference Worker & Supervisor Architecture (Phase 27.2).

Enforces:
- Full 12-state supervised lifecycle:
  CREATED -> STARTING -> READY -> RUNNING -> UNRESPONSIVE ->
  CANCELLATION_REQUESTED -> GRACEFUL_TERMINATION_REQUESTED ->
  FORCE_TERMINATION_REQUESTED -> TERMINATION_UNCONFIRMED ->
  TERMINATED -> RESTART_PENDING -> RECOVERY_FAILED.
- Worker epochs & generation counters: strictly rejects stale results
  from old generations, expired leases, or cancelled tasks.
- True OS process termination: escalates from graceful IPC cancel to
  OS terminate/kill and confirms OS exit status before reporting TERMINATED.
- Cross-platform compatibility: uses 'spawn' multiprocessing context
  compatible with Windows 11 and POSIX Linux.
- Total failure isolation: worker crash, segfault, hang, or memory leak
  cannot crash the main CAMserv application or interrupt recording continuity.
"""

from __future__ import annotations

import collections
import logging
import multiprocessing
import os
import queue
import signal
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from camserv.intelligence.contracts import (
    BoundingBox,
    DetectionPrediction,
    InferenceTaskLease,
    WorkerLifecycleState,
)

logger = logging.getLogger(__name__)

# Bounded queue sizes to prevent IPC memory exhaustion
DEFAULT_IPC_QUEUE_MAXSIZE = 8
DEFAULT_GRACE_PERIOD_SEC = 0.4
DEFAULT_FORCE_KILL_TIMEOUT_SEC = 0.6


# ---------------------------------------------------------------------------
# Worker IPC Message Protocol
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class WorkerTaskMessage:
    """Task submission message delivered across process boundary."""

    task_id: str
    lease_id: str
    generation: int
    camera_id: str
    frame_id: int
    frame_shape: tuple[int, ...]
    frame_dtype: str
    frame_bytes: bytes
    timestamp_utc: float
    confidence_threshold: float = 0.35
    model_id: str = "camserv_det_cpu_v1"


@dataclass(slots=True)
class WorkerResultMessage:
    """Result message returned from isolated worker process."""

    task_id: str
    lease_id: str
    generation: int
    camera_id: str
    frame_id: int
    success: bool
    predictions: list[dict[str, Any]]
    latency_ms: float
    error_message: str | None = None
    worker_pid: int | None = None


# ---------------------------------------------------------------------------
# Top-Level Worker Process Entrypoint (Picklable for Spawn Context)
# ---------------------------------------------------------------------------

def _ai_worker_process_entrypoint(
    task_queue: multiprocessing.Queue,
    result_queue: multiprocessing.Queue,
    control_event: Any,
    generation: int,
    worker_id: str,
) -> None:
    """
    Isolated child process loop. Runs in an independent OS process address space.
    Has NO ACCESS to camera passwords, vault master keys, or recording queues.
    """
    # Lazy imports inside isolated process
    from camserv.intelligence.detection import ObjectDetectionEngine
    from camserv.intelligence.registry import ModelCapabilityRegistry

    pid = os.getpid()
    engine = ObjectDetectionEngine(confidence_threshold=0.35, allow_heuristic_fallback=True)

    while not control_event.is_set():
        try:
            # Poll task queue with bounded timeout to check control_event
            msg: WorkerTaskMessage | dict[str, Any] = task_queue.get(timeout=0.2)
        except (queue.Empty, TimeoutError):
            continue
        except (KeyboardInterrupt, EOFError):
            break

        if isinstance(msg, dict) and msg.get("cmd") == "STOP":
            break

        if not isinstance(msg, WorkerTaskMessage):
            continue

        # Check generation epoch
        if msg.generation != generation:
            # Stale generation task, ignore
            continue

        t_start = time.perf_counter()
        try:
            # Reconstruct frame from raw bytes
            frame = np.frombuffer(msg.frame_bytes, dtype=np.dtype(msg.frame_dtype)).reshape(msg.frame_shape)
            dets = engine.detect(
                frame,
                camera_id=msg.camera_id,
                frame_id=msg.frame_id,
                timestamp_utc=msg.timestamp_utc,
            )
            latency_ms = (time.perf_counter() - t_start) * 1000.0

            # Convert predictions to serializable format
            pred_dicts = [
                {
                    "bbox": d.bbox.as_tuple(),
                    "class_id": d.class_id,
                    "class_name": d.class_name,
                    "confidence": d.confidence,
                    "camera_id": d.camera_id,
                    "frame_id": d.frame_id,
                    "timestamp_utc": d.timestamp_utc,
                    "metadata": d.metadata,
                }
                for d in dets
            ]

            result = WorkerResultMessage(
                task_id=msg.task_id,
                lease_id=msg.lease_id,
                generation=generation,
                camera_id=msg.camera_id,
                frame_id=msg.frame_id,
                success=True,
                predictions=pred_dicts,
                latency_ms=round(latency_ms, 2),
                error_message=None,
                worker_pid=pid,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - t_start) * 1000.0
            result = WorkerResultMessage(
                task_id=msg.task_id,
                lease_id=msg.lease_id,
                generation=generation,
                camera_id=msg.camera_id,
                frame_id=msg.frame_id,
                success=False,
                predictions=[],
                latency_ms=round(latency_ms, 2),
                error_message=f"{type(exc).__name__}: {str(exc)}",
                worker_pid=pid,
            )

        try:
            result_queue.put(result, timeout=1.0)
        except Exception:
            break


# ---------------------------------------------------------------------------
# Process-Isolated Inference Supervisor
# ---------------------------------------------------------------------------

class ProcessIsolatedInferenceSupervisor:
    """
    Supervisor managing native OS process isolation for heavy visual inference.
    Guarantees confirmed OS termination, generation protection against stale results,
    and automatic bounded restart without starving recording.
    """

    def __init__(
        self,
        worker_id: str = "ai_proc_worker_1",
        task_timeout_sec: float = 2.0,
        grace_period_sec: float = DEFAULT_GRACE_PERIOD_SEC,
        force_kill_timeout_sec: float = DEFAULT_FORCE_KILL_TIMEOUT_SEC,
        auto_restart: bool = True,
        max_restarts_per_window: int = 5,
        restart_window_sec: float = 10.0,
    ) -> None:
        self.worker_id = worker_id
        self.task_timeout_sec = task_timeout_sec
        self.grace_period_sec = grace_period_sec
        self.force_kill_timeout_sec = force_kill_timeout_sec
        self.auto_restart = auto_restart
        self.max_restarts_per_window = max_restarts_per_window
        self.restart_window_sec = restart_window_sec

        self._ctx = multiprocessing.get_context("spawn")
        self._lock = threading.RLock()
        self._generation: int = 0
        self._state: WorkerLifecycleState = WorkerLifecycleState.CREATED
        self._process: multiprocessing.Process | None = None
        self._task_queue: multiprocessing.Queue | None = None
        self._result_queue: multiprocessing.Queue | None = None
        self._stop_event: Any = None

        self._active_leases: dict[str, InferenceTaskLease] = {}
        self._restart_timestamps: collections.deque[float] = collections.deque()
        self._last_error: str | None = None
        self._worker_pid: int | None = None

        # Start supervisor initial worker
        self._start_worker_process()

    @property
    def state(self) -> WorkerLifecycleState:
        with self._lock:
            return self._state

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def worker_pid(self) -> int | None:
        with self._lock:
            return self._worker_pid

    @property
    def is_alive(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.is_alive()

    def _start_worker_process(self) -> bool:
        """Spawn a new child process with incremented generation."""
        with self._lock:
            self._state = WorkerLifecycleState.STARTING
            self._generation += 1

            # Check circuit breaker
            now = time.time()
            self._restart_timestamps.append(now)
            while self._restart_timestamps and self._restart_timestamps[0] < now - self.restart_window_sec:
                self._restart_timestamps.popleft()

            if len(self._restart_timestamps) > self.max_restarts_per_window:
                logger.error("Supervisor circuit breaker tripped for %s: too many restarts", self.worker_id)
                self._state = WorkerLifecycleState.RECOVERY_FAILED
                return False

            self._task_queue = self._ctx.Queue(maxsize=DEFAULT_IPC_QUEUE_MAXSIZE)
            self._result_queue = self._ctx.Queue(maxsize=DEFAULT_IPC_QUEUE_MAXSIZE)
            self._stop_event = self._ctx.Event()

            self._process = self._ctx.Process(
                target=_ai_worker_process_entrypoint,
                args=(
                    self._task_queue,
                    self._result_queue,
                    self._stop_event,
                    self._generation,
                    self.worker_id,
                ),
                name=f"camserv_ai_{self.worker_id}_gen{self._generation}",
                daemon=True,
            )
            self._process.start()
            self._worker_pid = self._process.pid
            self._state = WorkerLifecycleState.READY
            return True

    def submit_and_wait(
        self,
        frame: np.ndarray,
        camera_id: str,
        frame_id: int,
        timestamp_utc: float | None = None,
        timeout_sec: float | None = None,
    ) -> tuple[list[DetectionPrediction], bool, str]:
        """
        Submit a frame for inference, enforce task lease, and await isolated result.
        Returns: (predictions, success, status_message).
        """
        ts = timestamp_utc or time.time()
        timeout = timeout_sec or self.task_timeout_sec

        with self._lock:
            if self._state not in (WorkerLifecycleState.READY, WorkerLifecycleState.RUNNING):
                if self._state == WorkerLifecycleState.RECOVERY_FAILED:
                    return [], False, "WORKER_RECOVERY_FAILED"
                if not self.is_alive:
                    if self.auto_restart:
                        if not self._start_worker_process():
                            return [], False, "WORKER_FAILED_TO_START"
                    else:
                        return [], False, f"WORKER_INACTIVE_{self._state.value.upper()}"

            # Create unique task lease
            lease_id = str(uuid.uuid4())
            lease = InferenceTaskLease(
                lease_id=lease_id,
                worker_id=self.worker_id,
                generation=self._generation,
                camera_id=camera_id,
                created_at_utc=ts,
                expires_at_utc=ts + timeout,
            )
            self._active_leases[lease_id] = lease
            task_id = f"task_{uuid.uuid4().hex[:8]}"
            current_gen = self._generation
            self._state = WorkerLifecycleState.RUNNING

            # Prepare message
            msg = WorkerTaskMessage(
                task_id=task_id,
                lease_id=lease_id,
                generation=current_gen,
                camera_id=camera_id,
                frame_id=frame_id,
                frame_shape=frame.shape,
                frame_dtype=str(frame.dtype),
                frame_bytes=frame.tobytes(),
                timestamp_utc=ts,
            )

            try:
                assert self._task_queue is not None
                self._task_queue.put(msg, timeout=0.2)
            except Exception as exc:
                self._state = WorkerLifecycleState.READY
                self._active_leases.pop(lease_id, None)
                return [], False, f"IPC_QUEUE_FULL: {str(exc)}"

        # Await result outside lock
        result_msg: WorkerResultMessage | None = None
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                assert self._result_queue is not None
                res: WorkerResultMessage = self._result_queue.get(timeout=0.1)
                # Verify lease and generation to protect against stale results
                with self._lock:
                    active_lease = self._active_leases.get(res.lease_id)
                    if not active_lease or active_lease.is_cancelled:
                        # Stale / cancelled lease result rejected
                        logger.warning("Rejected stale/cancelled result for lease %s", res.lease_id)
                        continue
                    if res.generation != self._generation:
                        # Old generation result rejected
                        logger.warning("Rejected stale generation result: gen %d != %d", res.generation, self._generation)
                        continue
                    if res.task_id == task_id:
                        result_msg = res
                        self._active_leases.pop(lease_id, None)
                        break
            except (queue.Empty, TimeoutError):
                continue
            except Exception:
                break

        with self._lock:
            if result_msg is not None:
                self._state = WorkerLifecycleState.READY
                if not result_msg.success:
                    return [], False, f"WORKER_INFERENCE_ERROR: {result_msg.error_message}"

                # Reconstruct DetectionPrediction objects
                predictions: list[DetectionPrediction] = []
                for p in result_msg.predictions:
                    bx1, by1, bx2, by2 = p["bbox"]
                    pred = DetectionPrediction(
                        bbox=BoundingBox(bx1, by1, bx2, by2),
                        class_id=p["class_id"],
                        class_name=p["class_name"],
                        confidence=p["confidence"],
                        camera_id=p["camera_id"],
                        frame_id=p["frame_id"],
                        timestamp_utc=p["timestamp_utc"],
                        is_prediction=True,
                        metadata=p.get("metadata", {}),
                    )
                    predictions.append(pred)

                return predictions, True, "SUCCESS"

            # Timeout occurred! Enforce controlled termination
            logger.warning("Worker %s timed out on task %s (lease %s)", self.worker_id, task_id, lease_id)
            self._state = WorkerLifecycleState.UNRESPONSIVE
            lease = self._active_leases.get(lease_id)
            if lease:
                lease.is_cancelled = True
                self._active_leases.pop(lease_id, None)

            # Trigger controlled termination and restart
            self.terminate_worker(graceful=False)

            if self.auto_restart:
                self._state = WorkerLifecycleState.RESTART_PENDING
                self._start_worker_process()

            return [], False, "WORKER_TIMEOUT_EXCEEDED"

    def terminate_worker(self, graceful: bool = True) -> WorkerLifecycleState:
        """
        Controlled termination sequence:
        1. Invalidate active leases.
        2. Set CANCELLATION_REQUESTED.
        3. If graceful: send stop command, wait grace_period.
        4. If alive: transition to FORCE_TERMINATION_REQUESTED, terminate/kill OS process.
        5. Verify OS process exit via join / is_alive.
        6. Return final confirmed state: TERMINATED or TERMINATION_UNCONFIRMED.
        """
        with self._lock:
            # 1. Invalidate all leases
            for lease in self._active_leases.values():
                lease.is_cancelled = True
            self._active_leases.clear()

            self._state = WorkerLifecycleState.CANCELLATION_REQUESTED

            proc = self._process
            if proc is None or not proc.is_alive():
                self._state = WorkerLifecycleState.TERMINATED
                return self._state

            # 2. Graceful attempt if requested
            if graceful and self._stop_event is not None:
                self._state = WorkerLifecycleState.GRACEFUL_TERMINATION_REQUESTED
                self._stop_event.set()
                if self._task_queue is not None:
                    try:
                        self._task_queue.put({"cmd": "STOP"}, timeout=0.1)
                    except Exception:
                        pass
                proc.join(timeout=self.grace_period_sec)

            # 3. Escalate to OS force termination if still alive
            if proc.is_alive():
                self._state = WorkerLifecycleState.FORCE_TERMINATION_REQUESTED
                try:
                    proc.terminate()
                except Exception:
                    pass
                proc.join(timeout=self.force_kill_timeout_sec)

            # 4. Final POSIX kill escalation if still alive
            if proc.is_alive():
                try:
                    if hasattr(proc, "kill"):
                        proc.kill()
                    elif hasattr(os, "kill"):
                        os.kill(proc.pid, signal.SIGKILL)
                except Exception:
                    pass
                proc.join(timeout=0.3)

            # 5. Confirm OS exit status
            if proc.is_alive():
                # OS could not confirm process exit (e.g. uninterruptible kernel D-state)
                logger.error("Worker %s OS termination UNCONFIRMED (PID %s still alive)", self.worker_id, proc.pid)
                self._state = WorkerLifecycleState.TERMINATION_UNCONFIRMED
            else:
                self._state = WorkerLifecycleState.TERMINATED
                self._worker_pid = None
                self._process = None

            # Clean up queues
            self._cleanup_queues()
            return self._state

    def _cleanup_queues(self) -> None:
        """Safely drain and close multiprocessing queues."""
        for q in (self._task_queue, self._result_queue):
            if q is not None:
                try:
                    q.close()
                    q.cancel_join_thread()
                except Exception:
                    pass
        self._task_queue = None
        self._result_queue = None

    def shutdown(self) -> None:
        """Shutdown supervisor and permanently terminate child process."""
        with self._lock:
            self.auto_restart = False
            self.terminate_worker(graceful=True)
