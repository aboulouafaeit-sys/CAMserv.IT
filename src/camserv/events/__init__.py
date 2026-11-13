"""camserv.events package exports."""
from camserv.events.alerts import (
    AlertChannel,
    AlertManager,
    AlertRateLimiter,
    EmailChannel,
    WebhookChannel,
    WebSocketChannel,
)
from camserv.events.detector import EventDetector as RuleEventDetector
from camserv.events.detector import EventRule
from camserv.events.temporal import (
    ObservationEvidence,
    TemporalEventEngine,
    TemporalTrackState,
)
from camserv.events.threat_engine import (
    LocalThreatEngine,
    SecurityNarrative,
    ThreatScoreBreakdown,
)

__all__ = [
    "AlertChannel",
    "AlertManager",
    "AlertRateLimiter",
    "EmailChannel",
    "EventRule",
    "ObservationEvidence",
    "RuleEventDetector",
    "TemporalEventEngine",
    "TemporalTrackState",
    "LocalThreatEngine",
    "SecurityNarrative",
    "ThreatScoreBreakdown",
    "WebhookChannel",
    "WebSocketChannel",
]
