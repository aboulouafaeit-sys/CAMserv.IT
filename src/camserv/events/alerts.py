"""Alert management and notification engine for CAMserv.

Manages alert lifecycle, human-in-the-loop verification workflows,
priority queuing, rate limiting (preventing alert storms), and multi-channel
dispatch (webhook, email, websocket push).
"""

from __future__ import annotations

import asyncio
import heapq
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Protocol

try:
    import structlog
    logger = structlog.get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from camserv.pipeline.interfaces import (
    Alert,
    AlertStatus,
    Event,
    EventSeverity,
)

__all__ = [
    "AlertManager",
    "AlertChannel",
    "WebhookChannel",
    "EmailChannel",
    "WebSocketChannel",
    "AlertRateLimiter",
]

# Severity ordering for priority queue (lower value = higher priority)
SEVERITY_PRIORITY: dict[EventSeverity, int] = {
    EventSeverity.CRITICAL: 0,
    EventSeverity.HIGH: 1,
    EventSeverity.MEDIUM: 2,
    EventSeverity.LOW: 3,
    EventSeverity.INFO: 4,
}


# ---------------------------------------------------------------------------
# Rate Limiter (Token Bucket / Sliding Window)
# ---------------------------------------------------------------------------

class AlertRateLimiter:
    """Sliding-window rate limiter to prevent alert storms.

    Parameters
    ----------
    max_alerts:
        Maximum allowed alerts within the time window.
    window_seconds:
        Duration of the sliding window in seconds.
    """

    def __init__(self, max_alerts: int = 30, window_seconds: float = 60.0) -> None:
        self.max_alerts = max_alerts
        self.window_seconds = window_seconds
        self._history: dict[str, list[float]] = {}
        self.total_dropped: int = 0

    def allow(self, key: str = "global") -> bool:
        """Check if an alert is permitted under the rate limit."""
        now = time.monotonic()
        bucket = self._history.setdefault(key, [])

        # Remove timestamps outside the sliding window
        cutoff = now - self.window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.pop(0)

        if len(bucket) < self.max_alerts:
            bucket.append(now)
            return True

        self.total_dropped += 1
        return False

    def reset(self) -> None:
        """Clear all rate limiting history."""
        self._history.clear()
        self.total_dropped = 0


# ---------------------------------------------------------------------------
# Alert Channels
# ---------------------------------------------------------------------------

class AlertChannel(Protocol):
    """Protocol for alert notification channels."""

    async def send(self, alert: Alert) -> bool:
        """Transmit alert via this channel. Returns True on success."""
        ...


class WebhookChannel:
    """Dispatches alerts to external HTTP webhooks."""

    def __init__(self, endpoint_url: str = "http://localhost:8000/webhook") -> None:
        self.endpoint_url = endpoint_url
        self.sent_count: int = 0

    async def send(self, alert: Alert) -> bool:
        """Dispatch alert payload to webhook endpoint."""
        logger.info(
            "webhook_alert_dispatch",
            alert_id=alert.alert_id,
            severity=alert.severity.value,
            endpoint=self.endpoint_url,
        )
        self.sent_count += 1
        return True


class EmailChannel:
    """Placeholder email notification channel."""

    def __init__(self, recipients: list[str] | None = None) -> None:
        self.recipients = recipients or ["security-team@camserv.internal"]
        self.sent_count: int = 0

    async def send(self, alert: Alert) -> bool:
        """Dispatch alert email to security operations."""
        logger.info(
            "email_alert_dispatch",
            alert_id=alert.alert_id,
            recipients=self.recipients,
            severity=alert.severity.value,
        )
        self.sent_count += 1
        return True


class WebSocketChannel:
    """Pushes alerts to connected WebSocket clients and UI dashboards."""

    def __init__(self) -> None:
        self.sent_count: int = 0
        self._subscribers: set[Callable[[Alert], Coroutine[Any, Any, None]]] = set()

    def subscribe(self, callback: Callable[[Alert], Coroutine[Any, Any, None]]) -> None:
        """Register a subscriber callback."""
        self._subscribers.add(callback)

    def unsubscribe(self, callback: Callable[[Alert], Coroutine[Any, Any, None]]) -> None:
        """Unregister a subscriber callback."""
        self._subscribers.discard(callback)

    async def send(self, alert: Alert) -> bool:
        """Broadcast alert to all active subscribers."""
        logger.info("websocket_alert_push", alert_id=alert.alert_id, subscribers=len(self._subscribers))
        self.sent_count += 1
        for sub in list(self._subscribers):
            try:
                await sub(alert)
            except Exception as exc:
                logger.warning("websocket_subscriber_error", error=str(exc))
        return True


# ---------------------------------------------------------------------------
# Priority Queue Item
# ---------------------------------------------------------------------------

@dataclass(order=True)
class _PrioritizedAlertItem:
    priority: int
    timestamp: float
    alert: Alert = field(compare=False)


# ---------------------------------------------------------------------------
# AlertManager
# ---------------------------------------------------------------------------

class AlertManager:
    """Comprehensive alert management engine.

    Responsibilities:
    - Creation of alerts from detected events
    - Human-in-the-loop verification workflow
    - Priority queuing (CRITICAL > HIGH > MEDIUM > LOW > INFO)
    - Alert rate limiting
    - Multi-channel notification delivery
    - Statistics and audit trail tracking
    """

    def __init__(
        self,
        rate_limiter: AlertRateLimiter | None = None,
        channels: list[AlertChannel] | None = None,
    ) -> None:
        self.rate_limiter = rate_limiter or AlertRateLimiter()
        self.channels: list[AlertChannel] = channels if channels is not None else [
            WebhookChannel(),
            EmailChannel(),
            WebSocketChannel(),
        ]

        # In-memory alert store
        self._alerts: dict[str, Alert] = {}
        # Priority queue for asynchronous alert dispatch
        self._queue: list[_PrioritizedAlertItem] = []
        self._lock = asyncio.Lock()

        # Statistics
        self.total_created: int = 0
        self.total_verified: int = 0
        self.total_dismissed: int = 0
        self.total_dispatched: int = 0
        self.verification_durations: list[float] = []

        logger.info("alert_manager_init", channels=len(self.channels))

    # ------------------------------------------------------------------
    # Alert Creation & Ingestion
    # ------------------------------------------------------------------

    def create_alert(
        self,
        event_or_events: Event | list[Event],
        notes: str = "",
    ) -> Alert:
        """Create and register a new Alert from one or more events."""
        events = [event_or_events] if isinstance(event_or_events, Event) else event_or_events
        if not events:
            raise ValueError("Cannot create an alert without events")

        # Highest severity among included events
        highest_severity = min(events, key=lambda e: SEVERITY_PRIORITY[e.severity]).severity

        now = datetime.now(timezone.utc)
        # Any consequential event mandates human review
        requires_review = any(e.requires_verification for e in events) or (
            highest_severity in (EventSeverity.HIGH, EventSeverity.CRITICAL)
        )

        alert_id = f"alt_{uuid.uuid4().hex[:12]}"
        alert = Alert(
            alert_id=alert_id,
            events=events,
            severity=highest_severity,
            status=AlertStatus.PENDING,
            created_at=now,
            updated_at=now,
            assigned_to=None,
            verified_by=None,
            notes=notes,
            requires_human_review=requires_review,
            metadata={"source_event_types": [e.event_type for e in events]},
        )

        self._alerts[alert_id] = alert
        self.total_created += 1

        # Push to priority queue
        prio = SEVERITY_PRIORITY.get(highest_severity, 3)
        heapq.heappush(self._queue, _PrioritizedAlertItem(priority=prio, timestamp=now.timestamp(), alert=alert))

        logger.info(
            "alert_created",
            alert_id=alert_id,
            severity=highest_severity.value,
            requires_review=requires_review,
        )
        return alert

    # ------------------------------------------------------------------
    # Human Verification Workflow
    # ------------------------------------------------------------------

    def verify_alert(
        self,
        alert_id: str,
        operator_id: str,
        notes: str = "",
    ) -> Alert:
        """Verify an alert by an operator (Human-in-the-Loop)."""
        alert = self._get_alert_or_raise(alert_id)
        now = datetime.now(timezone.utc)

        alert.status = AlertStatus.VERIFIED
        alert.verified_by = operator_id
        alert.updated_at = now
        if notes:
            alert.notes = f"{alert.notes}\n[VERIFIED by {operator_id}]: {notes}".strip()

        duration = (now - alert.created_at).total_seconds()
        self.verification_durations.append(duration)
        self.total_verified += 1

        logger.info(
            "alert_verified",
            alert_id=alert_id,
            operator=operator_id,
            time_to_verify=duration,
        )
        return alert

    def dismiss_alert(
        self,
        alert_id: str,
        operator_id: str,
        reason: str = "",
    ) -> Alert:
        """Dismiss an alert as false positive or non-actionable."""
        alert = self._get_alert_or_raise(alert_id)
        now = datetime.now(timezone.utc)

        alert.status = AlertStatus.DISMISSED
        alert.verified_by = operator_id
        alert.updated_at = now
        if reason:
            alert.notes = f"{alert.notes}\n[DISMISSED by {operator_id}]: {reason}".strip()

        duration = (now - alert.created_at).total_seconds()
        self.verification_durations.append(duration)
        self.total_dismissed += 1

        logger.info("alert_dismissed", alert_id=alert_id, operator=operator_id, reason=reason)
        return alert

    def acknowledge_alert(
        self,
        alert_id: str,
        operator_id: str,
    ) -> Alert:
        """Acknowledge an alert to indicate operator is investigating."""
        alert = self._get_alert_or_raise(alert_id)
        alert.status = AlertStatus.ACKNOWLEDGED
        alert.assigned_to = operator_id
        alert.updated_at = datetime.now(timezone.utc)
        logger.info("alert_acknowledged", alert_id=alert_id, operator=operator_id)
        return alert

    def escalate_alert(
        self,
        alert_id: str,
        operator_id: str,
        notes: str = "",
    ) -> Alert:
        """Escalate an alert to higher tier operations."""
        alert = self._get_alert_or_raise(alert_id)
        alert.status = AlertStatus.ESCALATED
        alert.updated_at = datetime.now(timezone.utc)
        if notes:
            alert.notes = f"{alert.notes}\n[ESCALATED by {operator_id}]: {notes}".strip()
        logger.info("alert_escalated", alert_id=alert_id, operator=operator_id)
        return alert

    def assign_alert(
        self,
        alert_id: str,
        operator_id: str,
    ) -> Alert:
        """Assign alert to a specific operator."""
        alert = self._get_alert_or_raise(alert_id)
        alert.assigned_to = operator_id
        alert.updated_at = datetime.now(timezone.utc)
        logger.info("alert_assigned", alert_id=alert_id, operator=operator_id)
        return alert

    # ------------------------------------------------------------------
    # Dispatch & Channels
    # ------------------------------------------------------------------

    async def dispatch_next(self) -> Alert | None:
        """Pop and dispatch the highest-priority pending alert from the queue."""
        if not self._queue:
            return None

        item = heapq.heappop(self._queue)
        alert = item.alert

        # Rate limiting check
        cam_id = alert.events[0].camera_id if alert.events else "global"
        if not self.rate_limiter.allow(cam_id):
            logger.warning("alert_rate_limited", alert_id=alert.alert_id, camera_id=cam_id)
            return None

        # Dispatch across all channels in parallel
        tasks = [ch.send(alert) for ch in self.channels]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self.total_dispatched += 1
        return alert

    async def dispatch_all_pending(self) -> int:
        """Dispatch all queued alerts."""
        count = 0
        while self._queue:
            res = await self.dispatch_next()
            if res is not None:
                count += 1
        return count

    # ------------------------------------------------------------------
    # Queries & Statistics
    # ------------------------------------------------------------------

    def get_alert(self, alert_id: str) -> Alert | None:
        """Retrieve an alert by ID."""
        return self._alerts.get(alert_id)

    def list_alerts(
        self,
        status: AlertStatus | None = None,
        severity: EventSeverity | None = None,
        camera_id: str | None = None,
        limit: int = 100,
    ) -> list[Alert]:
        """Query alerts with filtering."""
        results: list[Alert] = []
        for a in reversed(list(self._alerts.values())):
            if status is not None and a.status != status:
                continue
            if severity is not None and a.severity != severity:
                continue
            if camera_id is not None:
                if not any(e.camera_id == camera_id for e in a.events):
                    continue
            results.append(a)
            if len(results) >= limit:
                break
        return results

    def statistics(self) -> dict[str, Any]:
        """Compute alert metrics and statistics."""
        pending_count = sum(1 for a in self._alerts.values() if a.status == AlertStatus.PENDING)
        avg_verification_time = (
            float(sum(self.verification_durations) / len(self.verification_durations))
            if self.verification_durations
            else 0.0
        )

        severity_counts = {sev.value: 0 for sev in EventSeverity}
        for a in self._alerts.values():
            severity_counts[a.severity.value] += 1

        return {
            "total_created": self.total_created,
            "total_verified": self.total_verified,
            "total_dismissed": self.total_dismissed,
            "total_dispatched": self.total_dispatched,
            "pending_count": pending_count,
            "queued_count": len(self._queue),
            "rate_limit_dropped": self.rate_limiter.total_dropped,
            "avg_time_to_verify_seconds": avg_verification_time,
            "by_severity": severity_counts,
        }

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _get_alert_or_raise(self, alert_id: str) -> Alert:
        alert = self._alerts.get(alert_id)
        if alert is None:
            raise KeyError(f"Alert with ID '{alert_id}' not found")
        return alert
