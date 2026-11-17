"""
camserv.platform.windows.display
================================

Windows 11 Native Multi-Monitor and Display Geometry Adapter.
Uses Win32 user32.dll (EnumDisplayMonitors, GetMonitorInfoW, GetSystemMetrics)
to discover physical displays, identify primary vs secondary monitors,
read usable work-area geometry, and clamp window positions to visible space.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any

import structlog

from camserv.platform.shared.interfaces import (
    DisplayGeometry,
    DisplayInfo,
    PlatformDisplayManager,
)

logger = structlog.get_logger(__name__)

# Win32 Constants
CCHDEVICENAME = 32
MONITORINFOF_PRIMARY = 0x00000001
SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
MDT_EFFECTIVE_DPI = 0


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * CCHDEVICENAME),
    ]


# Callback prototype: BOOL CALLBACK MonitorEnumProc(HMONITOR, HDC, LPRECT, LPARAM)
MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMONITOR,
    wintypes.HDC,
    ctypes.POINTER(RECT),
    wintypes.LPARAM,
)


class WindowsDisplayManager(PlatformDisplayManager):
    """
    Win32 implementation of display monitor enumeration and geometry management.
    """

    def __init__(self, mock_displays: list[DisplayInfo] | None = None) -> None:
        super().__init__()
        self._mock_displays = mock_displays

    def enumerate_displays(self) -> list[DisplayInfo]:
        """
        Discover all connected monitors using user32.EnumDisplayMonitors.
        Falls back to primary monitor via GetSystemMetrics if enumeration fails.
        """
        if self._mock_displays is not None:
            return list(self._mock_displays)

        displays: list[DisplayInfo] = []

        try:
            user32 = ctypes.windll.user32

            def _enum_proc(h_monitor: int, hdc: int, lprc: Any, lparam: int) -> int:
                info = MONITORINFOEXW()
                info.cbSize = ctypes.sizeof(MONITORINFOEXW)
                if user32.GetMonitorInfoW(h_monitor, ctypes.byref(info)):
                    m_rect = info.rcMonitor
                    w_rect = info.rcWork

                    x = int(m_rect.left)
                    y = int(m_rect.top)
                    w = int(m_rect.right - m_rect.left)
                    h = int(m_rect.bottom - m_rect.top)

                    work_x = int(w_rect.left)
                    work_y = int(w_rect.top)
                    work_w = int(w_rect.right - w_rect.left)
                    work_h = int(w_rect.bottom - w_rect.top)

                    is_primary = bool(info.dwFlags & MONITORINFOF_PRIMARY)
                    device_name = str(info.szDevice).strip()
                    display_id = device_name.replace("\\", "").replace(".", "_") or f"DISPLAY_{len(displays)}"

                    # Query DPI via shcore if available
                    dpi = 96
                    scale_factor = 1.0
                    try:
                        shcore = ctypes.windll.shcore
                        dpi_x = wintypes.UINT()
                        dpi_y = wintypes.UINT()
                        if shcore.GetDpiForMonitor(h_monitor, MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
                            dpi = int(dpi_x.value)
                            scale_factor = round(dpi / 96.0, 2)
                    except Exception:
                        pass

                    geom = DisplayGeometry(
                        x=x,
                        y=y,
                        width=w,
                        height=h,
                        work_x=work_x,
                        work_y=work_y,
                        work_width=work_w,
                        work_height=work_h,
                    )

                    disp = DisplayInfo(
                        display_id=display_id,
                        name=f"Windows Monitor ({device_name})",
                        geometry=geom,
                        is_primary=is_primary,
                        scale_factor=scale_factor,
                        refresh_rate_hz=60.0,
                        is_connected=True,
                        dpi=dpi,
                    )
                    displays.append(disp)
                return 1

            cb = MONITORENUMPROC(_enum_proc)
            user32.EnumDisplayMonitors(0, 0, cb, 0)

        except Exception as exc:
            logger.warning("windows_display.enum_failed_fallback_primary", error=str(exc))

        if not displays:
            # Fallback to single primary monitor metrics
            displays.append(self._get_fallback_primary_display())

        # Ensure at least one display is marked primary
        if not any(d.is_primary for d in displays):
            displays[0].is_primary = True

        return displays

    def _get_fallback_primary_display(self) -> DisplayInfo:
        """Create fallback display info from GetSystemMetrics or default 1080p."""
        w, h = 1920, 1080
        try:
            user32 = ctypes.windll.user32
            w = user32.GetSystemMetrics(SM_CXSCREEN) or 1920
            h = user32.GetSystemMetrics(SM_CYSCREEN) or 1080
        except Exception:
            pass

        return DisplayInfo(
            display_id="DISPLAY_PRIMARY",
            name="Primary Display (DirectShow/GDI)",
            geometry=DisplayGeometry(
                x=0,
                y=0,
                width=w,
                height=h,
                work_x=0,
                work_y=0,
                work_width=w,
                work_height=h - 48,  # Estimated Windows Taskbar
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
        """
        Validate and clamp window position to ensure it is not rendered off-screen
        or outside the usable working area of connected displays.
        """
        displays = self.enumerate_displays()
        primary = self.get_primary_display()

        # Check if coordinates (x, y) fall within any display's bounds
        contained_display: DisplayInfo | None = None
        for d in displays:
            if d.geometry.contains_point(x, y):
                contained_display = d
                break

        if contained_display is None:
            # Fall back to primary display working area with slight offset
            target_x = primary.geometry.work_x + 40
            target_y = primary.geometry.work_y + 40
            target_w = min(width, primary.geometry.work_width)
            target_h = min(height, primary.geometry.work_height)
            return target_x, target_y, target_w, target_h

        # Clamp dimensions to the contained display's work area
        work = contained_display.geometry
        clamped_w = min(width, work.work_width)
        clamped_h = min(height, work.work_height)

        # Ensure window header is inside the work area
        clamped_x = max(work.work_x, min(x, work.work_x + work.work_width - clamped_w))
        clamped_y = max(work.work_y, min(y, work.work_y + work.work_height - clamped_h))

        return clamped_x, clamped_y, clamped_w, clamped_h
