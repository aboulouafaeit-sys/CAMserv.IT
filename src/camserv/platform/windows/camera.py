"""
camserv.platform.windows.camera
===============================

Microsoft Windows camera acquisition backend using Microsoft Media Foundation (MF)
and DirectShow (DSHOW) fallback. Enumerates local USB and integrated optical webcams
and negotiates hardware capture parameters.
"""

from __future__ import annotations

from typing import Any

import structlog

from camserv.platform.shared.interfaces import LocalCameraDevice, PlatformCameraBackend

logger = structlog.get_logger(__name__)


class WindowsMediaFoundationCameraBackend(PlatformCameraBackend):
    """Camera capture backend for Windows using Microsoft Media Foundation and DirectShow."""

    def enumerate_local_cameras(self) -> list[LocalCameraDevice]:
        """Discover connected optical cameras via OpenCV MSMF probe with DSHOW fallback."""
        devices: list[LocalCameraDevice] = []

        try:
            import cv2
            # Probe indices 0 to 3 for active cameras
            for idx in range(4):
                cap = None
                backend_used = "media_foundation"
                # First try MSMF
                if hasattr(cv2, "CAP_MSMF"):
                    cap = cv2.VideoCapture(idx, cv2.CAP_MSMF)
                    if not (cap is not None and cap.isOpened()):
                        if cap is not None:
                            cap.release()
                        cap = None

                # Fallback to DirectShow if MSMF did not open
                if cap is None and hasattr(cv2, "CAP_DSHOW"):
                    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                    if cap is not None and cap.isOpened():
                        backend_used = "directshow"
                    else:
                        if cap is not None:
                            cap.release()
                        cap = None

                if cap is not None and cap.isOpened():
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
                    fps = int(cap.get(cv2.CAP_PROP_FPS))
                    if fps <= 0 or fps > 240:
                        fps = 30

                    devices.append(
                        LocalCameraDevice(
                            index=idx,
                            name=f"Windows Camera {idx} ({backend_used.upper()})",
                            backend=backend_used,
                            device_path=f"camera_index_{idx}",
                            is_available=True,
                            supported_resolutions=[(w, h), (1920, 1080), (1280, 720), (640, 480)],
                            supported_formats=["MJPEG", "YUY2", "NV12"],
                        )
                    )
                    cap.release()
        except Exception as exc:
            logger.debug("windows.camera.probe_failed", error=str(exc))

        if not devices:
            # Fallback synthetic camera descriptor
            devices.append(
                LocalCameraDevice(
                    index=0,
                    name="Synthetic Test Camera (Windows)",
                    backend="synthetic",
                    device_path="synthetic",
                    is_available=True,
                    supported_resolutions=[(1920, 1080), (640, 480)],
                    supported_formats=["RAW_RGB"],
                )
            )
        return devices

    def open_capture_stream(
        self,
        device_index_or_path: int | str,
        width: int | None = None,
        height: int | None = None,
        fps: int | None = None,
    ) -> Any:
        """Open camera stream using OpenCV Media Foundation or DirectShow backend."""
        try:
            import cv2
            target = device_index_or_path
            if isinstance(target, str) and target.isdigit():
                target = int(target)

            cap = None
            if hasattr(cv2, "CAP_MSMF"):
                cap = cv2.VideoCapture(target, cv2.CAP_MSMF)
                if not (cap is not None and cap.isOpened()):
                    if cap is not None:
                        cap.release()
                    cap = None

            if cap is None and hasattr(cv2, "CAP_DSHOW"):
                cap = cv2.VideoCapture(target, cv2.CAP_DSHOW)

            if cap is not None and cap.isOpened():
                if width:
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                if height:
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                if fps:
                    cap.set(cv2.CAP_PROP_FPS, fps)
                return cap
            return cap
        except ImportError:
            return "synthetic"

    def get_backend_name(self) -> str:
        return "media_foundation"
