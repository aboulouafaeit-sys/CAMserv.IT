"""
camserv.nvr.recording_scheduler
===============================

Per-camera recording schedule evaluator for the CAMserv NVR subsystem.
Evaluates time-of-day and day-of-week active windows to determine whether
a camera channel should record continuously, record on events only, or remain inactive.
"""

from __future__ import annotations

from datetime import datetime, time as dtime, timezone
from typing import Any

import structlog

from camserv.storage.sqlite_store import SQLiteStore

logger = structlog.get_logger(__name__)


class RecordingScheduler:
    """
    Evaluates camera recording schedules defined in SQLiteStore.
    """

    def __init__(self, store: SQLiteStore, default_mode: str = "continuous") -> None:
        self.store = store
        self.default_mode = default_mode  # Fallback if no specific schedules are set

    def add_schedule(
        self,
        schedule_id: str,
        camera_id: str,
        day_of_week: int,
        start_time_str: str,
        end_time_str: str,
        mode: str = "continuous",
        is_active: bool = True,
    ) -> dict[str, Any]:
        """
        Register a schedule window.
        day_of_week: 0 = Monday, 6 = Sunday.
        start_time_str / end_time_str: "HH:MM" (24-hour format).
        mode: 'continuous', 'event', 'disabled'.
        """
        # Validate time format
        dtime.fromisoformat(start_time_str)
        dtime.fromisoformat(end_time_str)

        schedule = {
            "schedule_id": schedule_id,
            "camera_id": camera_id,
            "day_of_week": day_of_week,
            "start_time": start_time_str,
            "end_time": end_time_str,
            "mode": mode,
            "is_active": is_active,
        }
        self.store.upsert_recording_schedule(schedule)
        logger.info(
            "nvr.schedule.added",
            schedule_id=schedule_id,
            camera_id=camera_id,
            day=day_of_week,
            start=start_time_str,
            end=end_time_str,
            mode=mode,
        )
        return schedule

    def remove_schedule(self, schedule_id: str) -> bool:
        """Remove a schedule window."""
        return self.store.delete_recording_schedule(schedule_id)

    def get_schedules_for_camera(self, camera_id: str) -> list[dict[str, Any]]:
        """List all active schedules for a camera."""
        return self.store.list_recording_schedules(camera_id)

    def evaluate_schedule(
        self,
        camera_id: str,
        current_dt: datetime | None = None,
    ) -> tuple[bool, str]:
        """
        Determine if recording should be active for camera_id at current_dt.
        Returns: (should_record: bool, mode: str)
        where mode is 'continuous', 'event', or 'disabled'.
        """
        dt = current_dt or datetime.now(timezone.utc)
        day = dt.weekday()
        current_time = dt.time()

        schedules = self.store.list_recording_schedules(camera_id)
        if not schedules:
            # If no schedules defined, use default policy
            return (self.default_mode != "disabled", self.default_mode)

        active_schedules = [s for s in schedules if s.get("is_active", True) and s.get("day_of_week") == day]
        if not active_schedules:
            # No schedule for today
            return (False, "disabled")

        for sched in active_schedules:
            try:
                start_t = dtime.fromisoformat(sched["start_time"])
                end_t = dtime.fromisoformat(sched["end_time"])

                in_window = False
                if start_t <= end_t:
                    in_window = start_t <= current_time <= end_t
                else:
                    # Overnight window (e.g. 22:00 to 06:00)
                    in_window = current_time >= start_t or current_time <= end_t

                if in_window:
                    mode = sched.get("mode", "continuous")
                    return (mode != "disabled", mode)
            except Exception as exc:
                logger.warning("nvr.schedule.parse_error", schedule_id=sched.get("schedule_id"), error=str(exc))
                continue

        return (False, "disabled")
