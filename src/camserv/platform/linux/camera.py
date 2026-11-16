"""
camserv.platform.linux.camera
=============================

Linux Video4Linux2 (V4L2) camera discovery and capture backend.
Enumerates /dev/video* nodes and configures hardware parameters.
"""

from __future__ import annotations

import glob
import os
from typing import Any

import structlog

from camserv.platform.shared.interfaces import LocalCameraDevice, PlatformCameraBackend

logger = structlog.get_logger(__name__)


class LinuxV4L2CameraBackend(PlatformCameraBackend):
    """V4L2 camera capture backend for Linux appliances."""

    def enumerate_local_cameras(self) -> list[LocalCameraDevice]:
        """Scan /dev/video* device nodes and report available cameras."""
        devices: list[LocalCameraDevice] = []
        video_nodes = sorted(glob.glob("/dev/video*"))

        for idx, node in enumerate(video_nodes):
            name = f"V4L2 Camera {idx}"
            sys_name_path = f"/sys/class/video4linux/{os.path.basename(node)}/name"
            if os.path.exists(sys_name_path):
                try:
                    with open(sys_name_path, "r", encoding="utf-8") as f:
                        name = f.read().strip()
                except OSError:
                    pass

            devices.append(
                LocalCameraDevice(
                    index=idx,
                    name=name,
                    backend="v4l2",
                    device_path=node,
                    is_available=os.access(node, os.R_OK | os.W_OK),
                    supported_resolutions=[(1920, 1080), (1280, 720), (640, 480)],
                    supported_formats=["YUYV", "MJPEG", "H264"],
                )
            )

        if not devices:
            # Fallback synthetic camera descriptor
            devices.append(
                LocalCameraDevice(
                    index=0,
                    name="Synthetic Test Camera",
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
        """Open camera stream using OpenCV V4L2 backend."""
        try:
            import cv2
            target = device_index_or_path
            backend_flag = getattr(cv2, "CAP_V4L2", 0)

            if isinstance(target, str) and target.isdigit():
                target = int(target)

            cap = cv2.VideoCapture(target, backend_flag)
            if width:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            if height:
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            if fps:
                cap.set(cv2.CAP_PROP_FPS, fps)
            return cap
        except ImportError:
            return "synthetic"

    def get_backend_name(self) -> str:
        return "v4l2"
