"""
camserv.pipeline.adaptive_scheduler
====================================

Multi-Rate Adaptive Analytical Sampling Scheduler for CAMserv (Condition C4).

Implements:
- Tier 1: Continuous baseline analytical sampling (default 5.0 FPS).
- Tier 2: Incident-triggered burst analytical sampling (up to 30.0 FPS) when threat score T >= 70
  or on explicit security event trigger.
- Hysteresis & Cooldown: Sustained burst sampling during cooldown window (default 5.0s)
  to prevent rapid oscillation.
- Fair-Share Resource Governor: Proportionally scales sampling rates across up to 16 concurrent
  cameras when aggregate analytical FPS demand exceeds system compute budget (e.g. 150 FPS).
- Telemetry: Real-time sampling rates, dropped frames, active tiers, and compute envelope status.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any

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


class SamplingTier(enum.Enum):
    """Analytical sampling tier for a camera stream."""

    BASELINE = "baseline"       # Default continuous background analysis (e.g., 5 FPS)
    BURST = "burst"             # Incident-driven high temporal resolution (e.g., 30 FPS)
    THROTTLED = "throttled"     # Resource-constrained fair-share allocation


@dataclass(slots=True)
class StreamSamplingState:
    """Per-stream scheduling telemetry and state."""

    camera_id: str
    tier: SamplingTier = SamplingTier.BASELINE
    effective_fps: float = 5.0
    threat_score: float = 0.0
    last_sampled_timestamp: float = 0.0
    last_burst_trigger_time: float = 0.0
    total_frames_evaluated: int = 0
    total_frames_sampled: int = 0
    total_frames_skipped: int = 0


@dataclass(slots=True)
class SchedulerConfig:
    """Configuration for the adaptive multi-rate scheduler."""

    baseline_fps: float = 5.0
    burst_fps: float = 30.0
    threat_threshold: float = 70.0
    cooldown_seconds: float = 5.0
    max_system_fps_budget: float = 160.0  # Safe envelope for 16 cams (16 * 5 = 80 baseline)
    min_stream_fps: float = 2.0


class AdaptiveSamplingScheduler:
    """Orchestrates per-camera analytical frame selection based on threat telemetry."""

    def __init__(self, config: SchedulerConfig | None = None) -> None:
        self.config = config or SchedulerConfig()
        self._streams: dict[str, StreamSamplingState] = {}
        self._log = logger.bind(component="adaptive_scheduler")

    def register_stream(self, camera_id: str) -> None:
        """Register a camera stream for adaptive scheduling."""
        if camera_id not in self._streams:
            self._streams[camera_id] = StreamSamplingState(
                camera_id=camera_id,
                effective_fps=self.config.baseline_fps,
                tier=SamplingTier.BASELINE,
            )
            self._recalculate_effective_rates()

    def unregister_stream(self, camera_id: str) -> None:
        """Remove a camera stream from scheduling."""
        self._streams.pop(camera_id, None)
        self._recalculate_effective_rates()

    def update_threat_score(self, camera_id: str, threat_score: float, current_time: float | None = None) -> None:
        """Update threat evaluation for a stream; elevates to BURST if threshold met."""
        state = self._streams.get(camera_id)
        if state is None:
            self.register_stream(camera_id)
            state = self._streams[camera_id]

        now = current_time if current_time is not None else time.time()
        state.threat_score = max(0.0, min(100.0, threat_score))

        if state.threat_score >= self.config.threat_threshold:
            state.last_burst_trigger_time = now
            if state.tier != SamplingTier.BURST:
                state.tier = SamplingTier.BURST
                self._log.info(
                    "scheduler.tier_elevated",
                    camera_id=camera_id,
                    threat=state.threat_score,
                    tier=state.tier.value,
                )
                self._recalculate_effective_rates(now)

    def trigger_incident(self, camera_id: str, current_time: float | None = None) -> None:
        """Explicit trigger (e.g. sensor alarm, tripwire, external API trigger)."""
        self.update_threat_score(camera_id, 100.0, current_time)

    def _is_burst_active(self, state: StreamSamplingState, current_time: float) -> bool:
        """Return True if stream is actively within burst trigger or cooldown window."""
        if state.threat_score >= self.config.threat_threshold:
            return True
        return (current_time - state.last_burst_trigger_time) <= self.config.cooldown_seconds

    def should_sample(self, camera_id: str, frame_timestamp: float | None = None) -> bool:
        """Predicate called for each incoming ingested frame.

        Returns True if the frame should be dispatched to deep analytical inference,
        or False if it should be skipped from inference while remaining in raw storage.
        """
        now = frame_timestamp if frame_timestamp is not None else time.time()
        state = self._streams.get(camera_id)
        if state is None:
            self.register_stream(camera_id)
            state = self._streams[camera_id]

        state.total_frames_evaluated += 1

        # Periodic / on-demand rate recalculation
        self._recalculate_effective_rates(now)

        interval = 1.0 / state.effective_fps if state.effective_fps > 0 else 0.2
        time_since_last = now - state.last_sampled_timestamp

        if state.last_sampled_timestamp == 0.0 or time_since_last >= (interval * 0.95):
            state.last_sampled_timestamp = now
            state.total_frames_sampled += 1
            return True
        else:
            state.total_frames_skipped += 1
            return False

    def _recalculate_effective_rates(self, current_time: float | None = None) -> None:
        """Enforces multi-camera fair queuing under total compute budget."""
        now = current_time if current_time is not None else time.time()
        if not self._streams:
            return

        # 1. Determine requested demand for each stream based on burst state
        demands: dict[str, float] = {}
        for cid, state in self._streams.items():
            if self._is_burst_active(state, now):
                demands[cid] = self.config.burst_fps
            else:
                demands[cid] = self.config.baseline_fps

        total_demand = sum(demands.values())
        budget = self.config.max_system_fps_budget

        if total_demand <= budget:
            for cid, state in self._streams.items():
                state.effective_fps = demands[cid]
                if demands[cid] == self.config.burst_fps:
                    state.tier = SamplingTier.BURST
                else:
                    state.tier = SamplingTier.BASELINE
        else:
            # Proportional fair-share allocation protecting minimum floor
            floor_total = len(self._streams) * self.config.min_stream_fps
            excess_budget = budget - floor_total

            if excess_budget <= 0:
                floor_rate = budget / len(self._streams)
                for state in self._streams.values():
                    state.effective_fps = round(max(1.0, floor_rate), 2)
                    state.tier = SamplingTier.THROTTLED
            else:
                raw_excess_demand = sum(max(0.0, d - self.config.min_stream_fps) for d in demands.values())
                scale = excess_budget / raw_excess_demand if raw_excess_demand > 0 else 1.0

                for cid, state in self._streams.items():
                    surplus = (demands[cid] - self.config.min_stream_fps) * scale
                    state.effective_fps = round(self.config.min_stream_fps + surplus, 2)
                    if demands[cid] == self.config.burst_fps:
                        state.tier = SamplingTier.BURST if state.effective_fps >= self.config.burst_fps else SamplingTier.THROTTLED
                    else:
                        state.tier = SamplingTier.BASELINE

    def telemetry(self) -> dict[str, Any]:
        """Return operational telemetry across all managed streams."""
        now = time.time()
        streams_telemetry = {}
        total_fps_demand = 0.0

        for cid, state in self._streams.items():
            streams_telemetry[cid] = {
                "tier": state.tier.value,
                "effective_fps": state.effective_fps,
                "threat_score": state.threat_score,
                "evaluated": state.total_frames_evaluated,
                "sampled": state.total_frames_sampled,
                "skipped": state.total_frames_skipped,
                "burst_active": (now - state.last_burst_trigger_time <= self.config.cooldown_seconds),
            }
            total_fps_demand += state.effective_fps

        return {
            "stream_count": len(self._streams),
            "aggregate_analytical_fps": round(total_fps_demand, 2),
            "budget_fps": self.config.max_system_fps_budget,
            "headroom_fps": round(max(0.0, self.config.max_system_fps_budget - total_fps_demand), 2),
            "streams": streams_telemetry,
        }
