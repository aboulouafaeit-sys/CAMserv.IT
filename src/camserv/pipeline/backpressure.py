"""
camserv.pipeline.backpressure
==============================

Backpressure-aware bounded queues for the pipeline engine.

The :class:`BackpressureQueue` wraps :class:`asyncio.Queue` and adds
configurable drop policies, fill-ratio monitoring, priority support and
comprehensive metrics so the pipeline can shed load gracefully under
sustained pressure rather than blocking producers or running out of memory.
"""

from __future__ import annotations

import asyncio
import enum
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

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

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Drop Policy
# ---------------------------------------------------------------------------

class DropPolicy(enum.Enum):
    """Strategy applied when the queue is full and a new item arrives."""

    DROP_OLDEST = "drop_oldest"
    DROP_NEWEST = "drop_newest"
    BLOCK = "block"


# ---------------------------------------------------------------------------
# Priority Wrapper
# ---------------------------------------------------------------------------

@dataclass(order=True, slots=True)
class PriorityItem(Generic[T]):
    """Wrapper that gives an item a numeric priority (lower = higher
    priority).  Events default to priority 0 while regular frames default
    to 10.
    """

    priority: int
    sequence: int = field(compare=True)  # tie-breaker for FIFO within a level
    item: Any = field(compare=False)


# ---------------------------------------------------------------------------
# Queue Statistics
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class QueueStats:
    """Snapshot of queue health metrics."""

    name: str
    current_depth: int
    max_depth: int
    total_enqueued: int
    total_dequeued: int
    total_dropped: int
    fill_ratio: float
    avg_wait_ms: float
    peak_depth: int


# ---------------------------------------------------------------------------
# BackpressureQueue
# ---------------------------------------------------------------------------

class BackpressureQueue(Generic[T]):
    """A bounded async queue with configurable backpressure behaviour.

    Parameters
    ----------
    name:
        Human-readable name for logging and metrics.
    maxsize:
        Maximum number of items the queue can hold.
    drop_policy:
        What to do when ``maxsize`` is reached and a new item arrives.
    warning_threshold:
        Fill ratio (0.0–1.0) at which a warning is emitted.
    critical_threshold:
        Fill ratio (0.0–1.0) at which a critical warning is emitted.
    enable_priority:
        When ``True``, items are ordered by :class:`PriorityItem`.priority
        (lower number = dequeued first).
    """

    def __init__(
        self,
        name: str,
        maxsize: int = 128,
        drop_policy: DropPolicy = DropPolicy.DROP_OLDEST,
        warning_threshold: float = 0.75,
        critical_threshold: float = 0.90,
        enable_priority: bool = False,
    ) -> None:
        self._name = name
        self._maxsize = max(1, maxsize)
        self._drop_policy = drop_policy
        self._warning_threshold = warning_threshold
        self._critical_threshold = critical_threshold
        self._enable_priority = enable_priority

        # Internal storage ----------------------------------------------------
        if enable_priority:
            self._queue: asyncio.PriorityQueue[PriorityItem[T]] = (
                asyncio.PriorityQueue(maxsize=0)  # unbounded; we manage size
            )
        else:
            self._queue: asyncio.Queue[T] = asyncio.Queue(maxsize=0)

        # We maintain our own deque mirror for drop_oldest support since
        # asyncio.Queue does not expose random removal.
        self._buffer: deque[Any] = deque()
        self._item_available = asyncio.Event()
        self._lock = asyncio.Lock()

        # Metrics --------------------------------------------------------------
        self._seq = 0
        self._total_enqueued: int = 0
        self._total_dequeued: int = 0
        self._total_dropped: int = 0
        self._peak_depth: int = 0
        self._wait_times: deque[float] = deque(maxlen=500)
        self._last_warning_time: float = 0.0
        self._WARNING_COOLDOWN: float = 5.0  # seconds between repeated warnings

        self._log = logger.bind(queue=name)

    # -- Properties -----------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def maxsize(self) -> int:
        return self._maxsize

    @property
    def qsize(self) -> int:
        return len(self._buffer)

    @property
    def fill_ratio(self) -> float:
        return len(self._buffer) / self._maxsize if self._maxsize else 0.0

    @property
    def is_full(self) -> bool:
        return len(self._buffer) >= self._maxsize

    @property
    def is_empty(self) -> bool:
        return len(self._buffer) == 0

    @property
    def dropped_count(self) -> int:
        return self._total_dropped

    # -- Core Operations ------------------------------------------------------

    async def put(self, item: T, priority: int = 10) -> bool:
        """Enqueue *item*, applying the drop policy if the queue is full.

        Returns ``True`` if the item was accepted, ``False`` if it was
        dropped (only possible with ``DROP_NEWEST`` policy).
        """
        async with self._lock:
            self._check_thresholds()

            if len(self._buffer) >= self._maxsize:
                if self._drop_policy is DropPolicy.DROP_OLDEST:
                    dropped = self._buffer.popleft()
                    self._total_dropped += 1
                    self._log.warning(
                        "backpressure_drop_oldest",
                        dropped_seq=getattr(dropped, "sequence", None),
                        depth=len(self._buffer),
                    )
                elif self._drop_policy is DropPolicy.DROP_NEWEST:
                    self._total_dropped += 1
                    self._log.warning(
                        "backpressure_drop_newest",
                        depth=len(self._buffer),
                    )
                    return False
                else:
                    # BLOCK — release lock and wait for space
                    pass  # handled below

            if self._drop_policy is DropPolicy.BLOCK and len(self._buffer) >= self._maxsize:
                # We must release the lock while waiting
                pass  # fall through to blocking put

        # Blocking path (outside lock) ----------------------------------------
        if self._drop_policy is DropPolicy.BLOCK and len(self._buffer) >= self._maxsize:
            while len(self._buffer) >= self._maxsize:
                await asyncio.sleep(0.01)

        async with self._lock:
            self._seq += 1
            if self._enable_priority:
                wrapped = PriorityItem(priority=priority, sequence=self._seq, item=item)
                self._buffer.append(wrapped)
                # Keep buffer sorted by priority then sequence for peek/drop
                # We use a heap via PriorityQueue for actual get ordering
            else:
                self._buffer.append(item)

            self._total_enqueued += 1
            if len(self._buffer) > self._peak_depth:
                self._peak_depth = len(self._buffer)

            self._item_available.set()

        return True

    async def get(self, timeout: float | None = None) -> T:
        """Dequeue and return the next item.

        If ``enable_priority`` is ``True``, the highest-priority (lowest
        number) item is returned first.

        Raises ``asyncio.TimeoutError`` if *timeout* seconds elapse with
        no item available.
        """
        start = time.monotonic()

        while True:
            async with self._lock:
                if self._buffer:
                    if self._enable_priority:
                        # Find the item with lowest priority value
                        best_idx = 0
                        best_pri = self._buffer[0].priority
                        for idx, entry in enumerate(self._buffer):
                            if entry.priority < best_pri:
                                best_pri = entry.priority
                                best_idx = idx
                        wrapped = self._buffer[best_idx]
                        del self._buffer[best_idx]
                        item = wrapped.item
                    else:
                        item = self._buffer.popleft()

                    self._total_dequeued += 1
                    elapsed_ms = (time.monotonic() - start) * 1000.0
                    self._wait_times.append(elapsed_ms)

                    if not self._buffer:
                        self._item_available.clear()

                    return item  # type: ignore[return-value]

            # Wait for an item to become available
            try:
                await asyncio.wait_for(
                    self._item_available.wait(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                raise

    async def peek(self) -> T | None:
        """Return the next item without removing it, or ``None``."""
        async with self._lock:
            if not self._buffer:
                return None
            if self._enable_priority:
                best = min(self._buffer, key=lambda x: (x.priority, x.sequence))
                return best.item  # type: ignore[return-value]
            return self._buffer[0]  # type: ignore[return-value]

    async def clear(self) -> int:
        """Remove and discard all items.  Returns the number discarded."""
        async with self._lock:
            count = len(self._buffer)
            self._buffer.clear()
            self._total_dropped += count
            self._item_available.clear()
            self._log.info("queue_cleared", discarded=count)
            return count

    # -- Monitoring -----------------------------------------------------------

    def stats(self) -> QueueStats:
        """Return a snapshot of queue health metrics."""
        avg_wait = (
            sum(self._wait_times) / len(self._wait_times)
            if self._wait_times
            else 0.0
        )
        return QueueStats(
            name=self._name,
            current_depth=len(self._buffer),
            max_depth=self._maxsize,
            total_enqueued=self._total_enqueued,
            total_dequeued=self._total_dequeued,
            total_dropped=self._total_dropped,
            fill_ratio=self.fill_ratio,
            avg_wait_ms=avg_wait,
            peak_depth=self._peak_depth,
        )

    def _check_thresholds(self) -> None:
        """Emit log warnings when fill ratio exceeds thresholds."""
        now = time.monotonic()
        if now - self._last_warning_time < self._WARNING_COOLDOWN:
            return

        ratio = self.fill_ratio
        if ratio >= self._critical_threshold:
            self._log.critical(
                "queue_critical",
                fill_ratio=round(ratio, 3),
                depth=len(self._buffer),
                maxsize=self._maxsize,
                dropped_total=self._total_dropped,
            )
            self._last_warning_time = now
        elif ratio >= self._warning_threshold:
            self._log.warning(
                "queue_high",
                fill_ratio=round(ratio, 3),
                depth=len(self._buffer),
                maxsize=self._maxsize,
            )
            self._last_warning_time = now

    # -- Dunder ---------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._buffer)

    def __repr__(self) -> str:
        return (
            f"BackpressureQueue(name={self._name!r}, "
            f"depth={len(self._buffer)}/{self._maxsize}, "
            f"policy={self._drop_policy.value})"
        )
