"""
camserv.acquisition
===================

Video acquisition, camera management, and frame decoding for CAMserv.
"""

from __future__ import annotations

from camserv.acquisition.camera import (
    AcquisitionError,
    CameraConnectionError,
    CameraHealth,
    CameraManager,
    CameraStatus,
    CameraStream,
    StreamConfig,
)
from camserv.acquisition.decoder import (
    DecoderConfig,
    FrameDecoderImpl,
)

__all__ = [
    "AcquisitionError",
    "CameraConnectionError",
    "CameraHealth",
    "CameraManager",
    "CameraStatus",
    "CameraStream",
    "DecoderConfig",
    "FrameDecoderImpl",
    "StreamConfig",
]
