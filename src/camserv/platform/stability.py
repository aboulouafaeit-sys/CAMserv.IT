"""
camserv.platform.stability
==========================

Zero-Freeze Architecture, Pipeline Bounded Queues, Failure Isolation & Service Supervision.
Ensures CAMserv operates reliably under extreme resource pressure, network interruptions,
accelerator crashes, and camera disconnect storms without UI blocking, recording stalls,
or uncontrolled memory growth.

Key Invariants:
1. UI and Recording paths NEVER block synchronously on network, AI, or slow disk I/O.
2. Ingestion and Recording have absolute priority over optional AI analysis.
3. All inter-subsystem queues are strictly bounded with documented capacity & overflow policies.
4. AI crashes, timeouts, and restarts are isolated and never crash or pause core recording.
5. Camera reconnect storms are mitigated via exponential backoff with randomized jitter.
"""

from __future__ import annotations

import asyncio
import collections
import enum
import math
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Generic, TypeVar

import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class QueueOverflowPolicy(str, enum.Enum):
    """Documented capacity policies when an internal pipeline queue saturates."""

    DROP_OLDEST = "drop_oldest"          # Evicts oldest items (optimal for preview / transient AI frames)
    DROP_NEWEST = "drop_newest"          # Rejects incoming item (sheds peak transient burst)
    APPLY_BACKPRESSURE = "backpressure"  # Blocks producer with a bounded timeout (used for recording writes)
    FAIL_CLOSED = "fail_closed"          # Raises QueueFull exception (strict deterministic isolation)


class ServicePriority(str, enum.Enum):
    """Subsystem execution priorities."""

    CRITICAL_RECORDING = "critical_recording"    # Highest priority: RTSP ingest, elementary stream write, hashing
    STORAGE_PERSISTENCE = "storage_persistence"  # High priority: SQLite WAL holds, segment commit, rotation
    OPTIONAL_AI_ANALYSIS = "optional_ai"         # Optional priority: Object detection, classification, tracking
    UI_INTERACTIVE = "ui_interactive"            # Operator interface: Rendering, search, forensic export


@dataclass(slots=True)
class QueueTelemetry:
    """Real-time observability metrics for a bounded pipeline queue."""

    queue_name: str
    capacity: int
    current_size: int
    total_enqueued: int = 0
    total_dequeued: int = 0
    total_dropped: int = 0
    overflow_events: int = 0
    high_watermark: int = 0
    max_latency_ms: float = 0.0

    @property
    def utilization_percent(self) -> float:
        if self.capacity <= 0:
            return 0.0
        return round((self.current_size / self.capacity) * 100.0, 1)


class BoundedPipelineQueue(Generic[T]):
    """
    Thread-safe, bounded pipeline queue with explicit overflow policies,
    telemetry accounting, and non-blocking semantics.
    Prevents uncontrolled heap expansion during slow disk I/O or AI stalls.
    """

    def __init__(
        self,
        name: str,
        maxsize: int = 120,
        policy: QueueOverflowPolicy = QueueOverflowPolicy.DROP_OLDEST,
        priority: ServicePriority = ServicePriority.OPTIONAL_AI_ANALYSIS,
    ) -> None:
        if maxsize <= 0:
            raise ValueError(f"Queue capacity must be positive, got {maxsize}")
        self.name = name
        self.maxsize = maxsize
        self.policy = policy
        self.priority = priority

        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._not_full = threading.Condition(self._lock)
        self._deque: collections.deque[tuple[T, float]] = collections.deque()

        # Telemetry
        self.total_enqueued = 0
        self.total_dequeued = 0
        self.total_dropped = 0
        self.overflow_events = 0
        self.high_watermark = 0
        self.max_latency_ms = 0.0

    def put(self, item: T, timeout_sec: float | None = None) -> bool:
        """
        Enqueue an item following the configured overflow policy.
        Returns True if item was accepted into queue, False if dropped.
        """
        now = time.time()
        with self._lock:
            # Check if queue has space
            if len(self._deque) < self.maxsize:
                self._deque.append((item, now))
                self.total_enqueued += 1
                self.high_watermark = max(self.high_watermark, len(self._deque))
                self._not_empty.notify()
                return True

            # Capacity reached: apply policy
            self.overflow_events += 1

            if self.policy == QueueOverflowPolicy.DROP_OLDEST:
                evicted, enq_time = self._deque.popleft()
                self.total_dropped += 1
                self._deque.append((item, now))
                self.total_enqueued += 1
                self._not_empty.notify()
                logger.debug(
                    "bounded_queue.drop_oldest",
                    queue=self.name,
                    dropped_count=self.total_dropped,
                )
                return True

            elif self.policy == QueueOverflowPolicy.DROP_NEWEST:
                self.total_dropped += 1
                logger.debug(
                    "bounded_queue.drop_newest",
                    queue=self.name,
                    dropped_count=self.total_dropped,
                )
                return False

            elif self.policy == QueueOverflowPolicy.APPLY_BACKPRESSURE:
                deadline = (now + timeout_sec) if timeout_sec is not None else None
                while len(self._deque) >= self.maxsize:
                    if deadline is not None:
                        remaining = deadline - time.time()
                        if remaining <= 0:
                            self.total_dropped += 1
                            return False
                        self._not_full.wait(remaining)
                    else:
                        self._not_full.wait(0.5)

                self._deque.append((item, now))
                self.total_enqueued += 1
                self.high_watermark = max(self.high_watermark, len(self._deque))
                self._not_empty.notify()
                return True

            else:  # FAIL_CLOSED
                self.total_dropped += 1
                raise BufferError(f"Queue '{self.name}' saturated at capacity {self.maxsize}")

    def get(self, timeout_sec: float | None = 0.1) -> T | None:
        """Dequeue an item with timeout. Returns None if queue is empty."""
        with self._lock:
            if not self._deque:
                if timeout_sec and timeout_sec > 0:
                    self._not_empty.wait(timeout_sec)
                if not self._deque:
                    return None

            item, enq_time = self._deque.popleft()
            self.total_dequeued += 1
            latency = (time.time() - enq_time) * 1000.0
            self.max_latency_ms = max(self.max_latency_ms, latency)
            self._not_full.notify()
            return item

    def get_telemetry(self) -> QueueTelemetry:
        """Retrieve real-time queue health telemetry."""
        with self._lock:
            return QueueTelemetry(
                queue_name=self.name,
                capacity=self.maxsize,
                current_size=len(self._deque),
                total_enqueued=self.total_enqueued,
                total_dequeued=self.total_dequeued,
                total_dropped=self.total_dropped,
                overflow_events=self.overflow_events,
                high_watermark=self.high_watermark,
                max_latency_ms=round(self.max_latency_ms, 2),
            )

    def clear(self) -> int:
        """Clear all pending items and return count of cleared items."""
        with self._lock:
            count = len(self._deque)
            self._deque.clear()
            self._not_full.notify_all()
            return count


def calculate_backoff_with_jitter(
    attempt: int,
    base_delay_sec: float = 1.0,
    max_delay_sec: float = 60.0,
    jitter_factor: float = 0.25,
) -> float:
    """
    Calculate exponential backoff with full randomized jitter to prevent reconnect storms.
    Formula: delay = min(max_delay, base * 2^attempt) * (1 +/- random(0, jitter))
    """
    attempt = max(0, min(10, attempt))
    exp_delay = min(max_delay_sec, base_delay_sec * math.pow(2, max(0, attempt - 1)))
    # Add randomized symmetric jitter
    jitter = exp_delay * jitter_factor * (random.random() * 2.0 - 1.0)
    final_delay = max(0.1, exp_delay + jitter)
    return round(final_delay, 3)


class WorkerCrashSupervisor:
    """
    Monitors background workers (AI inference, camera RTSP decoders, flusher).
    Provides crash isolation: ensures that an exception or death of an optional AI
    worker never halts core video recording or freezes the UI.
    """

    def __init__(self, name: str, max_restarts: int = 5, backoff_base_sec: float = 1.0) -> None:
        self.name = name
        self.max_restarts = max_restarts
        self.backoff_base_sec = backoff_base_sec
        self.restart_count = 0
        self.crash_history: list[dict[str, Any]] = []
        self.is_alive = True
        self.is_fenced = False

    def record_crash(self, exception: Exception | str) -> float:
        """
        Record worker crash, increment restart counter, and compute safe delay before retry.
        If max_restarts is exceeded, fences worker to prevent continuous thrashing.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        self.restart_count += 1
        err_msg = str(exception)

        self.crash_history.append({
            "restart_attempt": self.restart_count,
            "timestamp_utc": now_iso,
            "error": err_msg,
        })

        if self.restart_count > self.max_restarts:
            self.is_fenced = True
            self.is_alive = False
            logger.error(
                "worker_supervisor.worker_fenced_exceeded_restarts",
                worker=self.name,
                restarts=self.restart_count,
                error=err_msg,
            )
            return -1.0  # Fenced: do not restart

        delay = calculate_backoff_with_jitter(self.restart_count, self.backoff_base_sec)
        logger.warning(
            "worker_supervisor.worker_crashed_isolated",
            worker=self.name,
            restart_count=self.restart_count,
            next_retry_delay_sec=delay,
            error=err_msg,
        )
        return delay

    def reset_clean(self) -> None:
        """Reset restart count after a period of stable execution."""
        self.restart_count = 0
        self.is_fenced = False
        self.is_alive = True


class NonBlockingExecutor:
    """
    Utility ensuring long-running operations (RTSP probe, storage sync, neural model loading)
    are executed asynchronously with hard timeouts, completely isolating the graphical UI.
    """

    @staticmethod
    def execute_with_timeout(
        task_fn: Callable[[], T],
        timeout_sec: float = 3.0,
        fallback_value: T | None = None,
    ) -> tuple[bool, T | None, str | None]:
        """
        Execute task_fn in a worker thread with guaranteed timeout.
        Returns: (success, result, error_message)
        """
        result: list[T | None] = [fallback_value]
        exc_holder: list[Exception | None] = [None]
        completed = threading.Event()

        def _target() -> None:
            try:
                result[0] = task_fn()
            except Exception as e:
                exc_holder[0] = e
            finally:
                completed.set()

        t = threading.Thread(target=_target, daemon=True)
        t.start()
        is_finished = completed.wait(timeout_sec)

        if not is_finished:
            return (
                False,
                fallback_value,
                f"Operation timed out after {timeout_sec:.2f} seconds (Non-blocking guard engaged).",
            )

        if exc_holder[0] is not None:
            return False, fallback_value, str(exc_holder[0])

        return True, result[0], None
