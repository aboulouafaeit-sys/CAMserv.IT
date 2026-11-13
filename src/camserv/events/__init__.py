"""CAMserv events package — rule-based event detection and alert management.

Provides an event detection engine that evaluates configurable rules against
tracked objects, plus an alert manager for lifecycle management, human
verification workflows, and multi-channel notifications.

All events carry confidence scores and are explicitly labeled as predictions.
Consequential events default to requiring human verification.
"""

from camserv.events.detector import EventDetector
from camserv.events.alerts import AlertManager

__all__ = [
    "EventDetector",
    "AlertManager",
]
