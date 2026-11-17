"""
camserv.workspace.event_focus
=============================

Event-Driven Camera Focus & Human-in-the-Loop Operator Alert Controller.
Integrates event ingestion with camera viewport focusing, temporary enlargement,
cooldown anti-stealing protection, and 1-click layout restoration.
Enforces ethical AI conventions: detections are hypotheses requiring human review.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from camserv.workspace.models import CameraTile, DisplayLayout, LayoutPreset

logger = structlog.get_logger(__name__)


class FocusPolicyMode(str, enum.Enum):
    """Operator focus response policy for incoming events."""

    MANUAL_BANNER = "manual_banner"          # Display notification banner with 1-click focus
    AUTO_FOCUS_CRITICAL = "auto_critical"    # Automatically focus only CRITICAL events; banner others
    DISABLED = "disabled"                    # Log to events list only; no viewport intervention


@dataclass(slots=True)
class FocusState:
    """Historical layout state recorded before an event-driven focus occurred."""

    is_focused: bool = False
    focused_camera_id: str | None = None
    event_id: str | None = None
    severity: str = "low"
    previous_preset: LayoutPreset | None = None
    previous_maximized_tile_id: str | None = None
    focused_at: float = 0.0


class EventDrivenFocusController:
    """
    Manages event-driven camera enlargement, focus policies, and layout restoration.
    """

    SEVERITY_LEVELS: dict[str, int] = {
        "low": 10,
        "medium": 20,
        "high": 30,
        "critical": 40,
    }

    def __init__(
        self,
        policy_mode: FocusPolicyMode = FocusPolicyMode.MANUAL_BANNER,
        cooldown_sec: float = 8.0,
        cooldown_seconds: float | None = None,
    ) -> None:
        self.policy_mode = policy_mode
        self.cooldown_sec = cooldown_seconds if cooldown_seconds is not None else cooldown_sec
        self.last_auto_focus_time: float = 0.0
        self.active_focus_state: FocusState = FocusState()

    def get_state(self) -> dict[str, Any]:
        """Return snapshot of active focus state."""
        return {
            "is_focused": self.active_focus_state.is_focused,
            "active_camera_id": self.active_focus_state.focused_camera_id,
            "event_id": self.active_focus_state.event_id,
            "non_consequential_tag": "candidate_hypothesis",
        }

    def trigger_event_focus(
        self,
        layout: DisplayLayout,
        event_data: dict[str, Any],
    ) -> tuple[DisplayLayout, dict[str, Any]]:
        """
        Trigger camera enlargement for an incoming event candidate.
        Includes cooldown anti-stealing protection and ethical hypothesis tagging.
        """
        event_id = str(event_data.get("id") or event_data.get("event_id") or "")
        camera_id = str(event_data.get("camera_id") or "")
        severity = str(event_data.get("severity") or "low").lower()

        # Check if camera exists in current layout
        target_tile: CameraTile | None = None
        for t in layout.tiles:
            if t.camera_id == camera_id:
                target_tile = t
                break

        if target_tile is None:
            return layout, {
                "is_focused": False,
                "active_camera_id": self.active_focus_state.focused_camera_id,
                "reason": f"Camera '{camera_id}' not found in active layout.",
            }

        now = time.time()
        elapsed = now - self.last_auto_focus_time
        in_cooldown = self.active_focus_state.is_focused and (elapsed < self.cooldown_sec)

        # Anti-stealing cooldown: if currently focused on a camera, lower or equal severity cannot steal focus
        if in_cooldown:
            curr_sev_val = self.SEVERITY_LEVELS.get(self.active_focus_state.severity, 10)
            new_sev_val = self.SEVERITY_LEVELS.get(severity, 10)
            if new_sev_val <= curr_sev_val:
                # Retain existing focus
                return layout, self.get_state()

        # Save previous state if not already focused
        if not self.active_focus_state.is_focused:
            self.active_focus_state = FocusState(
                is_focused=True,
                focused_camera_id=camera_id,
                event_id=event_id,
                severity=severity,
                previous_preset=layout.preset,
                previous_maximized_tile_id=layout.maximized_tile_id,
                focused_at=now,
            )
        else:
            # Update active focus state
            self.active_focus_state = FocusState(
                is_focused=True,
                focused_camera_id=camera_id,
                event_id=event_id,
                severity=severity,
                previous_preset=self.active_focus_state.previous_preset,
                previous_maximized_tile_id=self.active_focus_state.previous_maximized_tile_id,
                focused_at=now,
            )

        self.last_auto_focus_time = now

        for t in layout.tiles:
            if t.camera_id == camera_id:
                t.is_focused = True
                t.is_maximized = True
                layout.maximized_tile_id = t.tile_id
            else:
                t.is_focused = False
                t.is_maximized = False

        state = self.get_state()
        state["requires_human_verification"] = True
        return layout, state

    def restore_focus(self, layout: DisplayLayout) -> DisplayLayout:
        """
        Restore display layout to its configuration prior to event focus.
        """
        prev_max_id = self.active_focus_state.previous_maximized_tile_id
        for t in layout.tiles:
            t.is_focused = False
            t.is_maximized = (t.tile_id == prev_max_id) if prev_max_id else False

        layout.maximized_tile_id = prev_max_id
        self.active_focus_state = FocusState()  # Reset focus state

        logger.info("event_focus.layout_restored")
        return layout
