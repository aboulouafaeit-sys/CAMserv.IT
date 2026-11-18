"""
camserv.intelligence.events
===========================

Structured Event Engine, Deduplication & Auditable Event Ledger.

Features:
- Standardized event creation matching IntelligenceEventType taxonomy.
- Sliding-window event deduplication per camera and track ID.
- Bounded memory ring buffer for event histories.
- Human review status tracking (`UNREVIEWED` -> `CONFIRMED` | `DISMISSED`).
- Tamper-evident SHA-256 evidence linking.
"""

from __future__ import annotations

import collections
import threading
import time
import uuid
from typing import Any, Sequence

from camserv.intelligence.contracts import (
    EngineHealthStatus,
    EpistemicLevel,
    IntelligenceEvent,
    IntelligenceEventType,
)


class EventDetectionEngine:
    """
    Manages the lifecycle, deduplication, and persistence of structured
    intelligence events.
    """

    def __init__(
        self,
        max_history_size: int = 1000,
        deduplication_window_sec: float = 5.0,
    ) -> None:
        self._max_history = max_history_size
        self._dedup_window_sec = deduplication_window_sec
        self._lock = threading.RLock()
        self._history: collections.deque[IntelligenceEvent] = collections.deque(maxlen=max_history_size)
        self._recent_events: dict[str, float] = {}  # dedup_key -> timestamp
        self._health_status = EngineHealthStatus.ACTIVE

    @property
    def health_status(self) -> EngineHealthStatus:
        with self._lock:
            return self._health_status

    @property
    def event_count(self) -> int:
        with self._lock:
            return len(self._history)

    def publish_event(
        self,
        event_type: IntelligenceEventType,
        camera_id: str,
        confidence: float,
        severity: str,
        epistemic_level: EpistemicLevel,
        evidence_hash: str,
        source_segment_id: str,
        source_frame_id: int,
        model_version: str = "v1.0",
        entity_key: str = "",
        requires_human_review: bool = False,
        metadata: dict[str, Any] | None = None,
        timestamp_utc: float | None = None,
    ) -> IntelligenceEvent | None:
        """
        Publish a structured event with automatic deduplication.
        Returns the published event, or None if suppressed by deduplication.
        """
        now = timestamp_utc or time.time()
        dedup_key = f"{camera_id}:{event_type.value}:{entity_key}"

        with self._lock:
            # Check deduplication window
            last_time = self._recent_events.get(dedup_key, 0.0)
            if now - last_time < self._dedup_window_sec:
                # Suppress duplicated event within window
                return None

            self._recent_events[dedup_key] = now

            # Clean stale deduplication keys
            stale_keys = [k for k, ts in self._recent_events.items() if now - ts > self._dedup_window_sec * 2]
            for k in stale_keys:
                self._recent_events.pop(k, None)

            event = IntelligenceEvent(
                event_id=f"evt_{uuid.uuid4().hex[:12]}",
                event_type=event_type,
                camera_id=camera_id,
                timestamp_utc=now,
                confidence=round(confidence, 4),
                severity=severity,
                epistemic_level=epistemic_level,
                evidence_hash=evidence_hash,
                source_segment_id=source_segment_id,
                source_frame_id=source_frame_id,
                model_version=model_version,
                requires_human_review=requires_human_review,
                review_status="UNREVIEWED",
                is_prediction=True,
                metadata=metadata or {},
            )
            self._history.append(event)
            return event

    def list_events(
        self,
        camera_id: str | None = None,
        event_type: IntelligenceEventType | None = None,
        limit: int = 100,
    ) -> list[IntelligenceEvent]:
        """Query recent events with optional filters."""
        with self._lock:
            res = list(self._history)
            if camera_id:
                res = [e for e in res if e.camera_id == camera_id]
            if event_type:
                res = [e for e in res if e.event_type == event_type]
            return res[-limit:]

    def update_review_status(
        self,
        event_id: str,
        new_status: str,
        operator: str,
    ) -> bool:
        """Update the human review status of an event."""
        with self._lock:
            for e in self._history:
                if e.event_id == event_id:
                    object.__setattr__(e, "review_status", new_status)
                    e.metadata["reviewed_by"] = operator
                    e.metadata["reviewed_at_utc"] = time.time()
                    return True
            return False
