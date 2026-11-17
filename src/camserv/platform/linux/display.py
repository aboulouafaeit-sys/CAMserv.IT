"""
camserv.platform.linux.display
==============================

Linux (Debian 12/13) Multi-Monitor and Display Geometry Adapter.
Discovers displays using xrandr CLI output, sysfs DRM connectors, or
X11 geometry. Supports headless execution and synthetic mock monitors for CI.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any

import structlog

from camserv.platform.shared.interfaces import (
    DisplayGeometry,
    DisplayInfo,
    PlatformDisplayManager,
)

logger = structlog.get_logger(__name__)


class LinuxDisplayManager(PlatformDisplayManager):
    """
    Linux / X11 / Wayland implementation of display monitor enumeration.
    """

    def __init__(self, mock_displays: list[DisplayInfo] | None = None) -> None:
        super().__init__()
        self._mock_displays = mock_displays

    def enumerate_displays(self) -> list[DisplayInfo]:
        """
        Enumerate displays via xrandr or sysfs DRM connectors.
        Falls back to default virtual display in headless server environments.
        """
        if self._mock_displays is not None:
            return list(self._mock_displays)

        displays = self._probe_xrandr()
        if not displays:
            displays = self._probe_drm_sysfs()

        if not displays:
            displays.append(self._get_fallback_primary_display())

        # Ensure at least one primary display
        if not any(d.is_primary for d in displays):
            displays[0].is_primary = True

        return displays

    @classmethod
    def _parse_xrandr_output(cls, stdout: str) -> list[DisplayInfo]:
        """Parse raw xrandr query string for connected monitors and geometry."""
        displays: list[DisplayInfo] = []
        pattern = re.compile(
            r"^(\S+)\s+connected\s+(primary\s+)?(\d+)x(\d+)\+(\d+)\+(\d+)",
            re.MULTILINE,
        )

        for match in pattern.finditer(stdout):
            name = match.group(1)
            is_primary = bool(match.group(2))
            w = int(match.group(3))
            h = int(match.group(4))
            x = int(match.group(5))
            y = int(match.group(6))

            geom = DisplayGeometry(
                x=x,
                y=y,
                width=w,
                height=h,
                work_x=x,
                work_y=y,
                work_width=w,
                work_height=max(1, h - 32),  # Estimated panel deduction
            )

            displays.append(
                DisplayInfo(
                    display_id=f"LINUX_{name.replace('-', '_')}",
                    name=f"Linux Display ({name})",
                    geometry=geom,
                    is_primary=is_primary,
                    scale_factor=1.0,
                    refresh_rate_hz=60.0,
                    is_connected=True,
                    dpi=96,
                )
            )
        return displays

    def _probe_xrandr(self) -> list[DisplayInfo]:
        """Parse xrandr command output for connected monitors and geometry."""
        if not shutil.which("xrandr") or not os.environ.get("DISPLAY"):
            return []

        try:
            res = subprocess.run(
                ["xrandr", "--query"],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if res.returncode != 0:
                return []
            return self._parse_xrandr_output(res.stdout)
        except Exception as exc:
            logger.debug("linux_display.xrandr_probe_failed", error=str(exc))
            return []

    def _probe_drm_sysfs(self) -> list[DisplayInfo]:
        """Probe /sys/class/drm for connected display connectors."""
        displays: list[DisplayInfo] = []
        drm_path = "/sys/class/drm"
        if not os.path.isdir(drm_path):
            return displays

        try:
            for entry in sorted(os.listdir(drm_path)):
                status_file = os.path.join(drm_path, entry, "status")
                if os.path.isfile(status_file):
                    try:
                        with open(status_file, "r") as f:
                            if f.read().strip() == "connected":
                                # Connected DRM display detected
                                idx = len(displays)
                                geom = DisplayGeometry(
                                    x=idx * 1920,
                                    y=0,
                                    width=1920,
                                    height=1080,
                                    work_x=idx * 1920,
                                    work_y=0,
                                    work_width=1920,
                                    work_height=1048,
                                )
                                displays.append(
                                    DisplayInfo(
                                        display_id=f"DRM_{entry.replace('-', '_')}",
                                        name=f"DRM Output ({entry})",
                                        geometry=geom,
                                        is_primary=(idx == 0),
                                        scale_factor=1.0,
                                        refresh_rate_hz=60.0,
                                        is_connected=True,
                                        dpi=96,
                                    )
                                )
                    except Exception:
                        pass
        except Exception as exc:
            logger.debug("linux_display.drm_probe_failed", error=str(exc))

        return displays

    def _get_fallback_primary_display(self) -> DisplayInfo:
        """Fallback virtual 1080p display for headless CI / appliance nodes."""
        return DisplayInfo(
            display_id="DISPLAY_HEADLESS",
            name="Virtual Headless Display (Linux)",
            geometry=DisplayGeometry(
                x=0,
                y=0,
                width=1920,
                height=1080,
                work_x=0,
                work_y=0,
                work_width=1920,
                work_height=1048,
            ),
            is_primary=True,
            scale_factor=1.0,
            refresh_rate_hz=60.0,
            is_connected=True,
            dpi=96,
        )

    def get_primary_display(self) -> DisplayInfo:
        """Retrieve the primary monitor."""
        displays = self.enumerate_displays()
        for d in displays:
            if d.is_primary:
                return d
        return displays[0]

    def get_display_by_id(self, display_id: str) -> DisplayInfo | None:
        """Find a display matching display_id."""
        for d in self.enumerate_displays():
            if d.display_id == display_id:
                return d
        return None

    def validate_window_geometry(
        self, x: int, y: int, width: int, height: int
    ) -> tuple[int, int, int, int]:
        """Clamp window geometry to visible display bounds."""
        displays = self.enumerate_displays()
        primary = self.get_primary_display()

        contained: DisplayInfo | None = None
        for d in displays:
            if d.geometry.contains_point(x, y):
                contained = d
                break

        if contained is None:
            target_x = primary.geometry.work_x + 30
            target_y = primary.geometry.work_y + 30
            target_w = min(width, primary.geometry.work_width)
            target_h = min(height, primary.geometry.work_height)
            return target_x, target_y, target_w, target_h

        work = contained.geometry
        clamped_w = min(width, work.work_width)
        clamped_h = min(height, work.work_height)
        clamped_x = max(work.work_x, min(x, work.work_x + work.work_width - clamped_w))
        clamped_y = max(work.work_y, min(y, work.work_y + work.work_height - clamped_h))

        return clamped_x, clamped_y, clamped_w, clamped_h
