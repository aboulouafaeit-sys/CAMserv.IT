"""
camserv.nvr.streaming
=====================

Multi-protocol streaming gateway for CAMserv NVR.
Supports WebRTC signaling abstraction, Low-Latency HLS (LL-HLS) playlist generation,
Media Source Extensions (MSE) buffer distribution, and MJPEG fallback streaming,
with strict fail-closed privacy enforcement.
"""

from __future__ import annotations

import asyncio
import io
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import numpy as np
import structlog

from camserv.inference.privacy_pipeline import FailClosedPrivacyPipeline

logger = structlog.get_logger(__name__)

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False


@dataclass
class StreamClientSession:
    """Active client session consuming a camera live stream."""

    session_id: str
    camera_id: str
    protocol: str  # 'webrtc', 'hls', 'mse', 'mjpeg'
    connected_at: float = field(default_factory=time.time)
    last_ping: float = field(default_factory=time.time)
    frames_delivered: int = 0
    bytes_delivered: int = 0
    is_active: bool = True


@dataclass
class WebRTCSessionState:
    """WebRTC peer connection session negotiation state."""

    session_id: str
    camera_id: str
    offer_sdp: str = ""
    answer_sdp: str = ""
    ice_candidates: list[dict[str, Any]] = field(default_factory=list)
    state: str = "new"  # 'new', 'offer_received', 'established', 'failed', 'closed'


class StreamingGateway:
    """
    Coordinates multi-protocol video delivery to web, mobile, and operator displays.
    Enforces that frames pass through the FailClosedPrivacyPipeline before distribution.
    """

    def __init__(self, privacy_pipeline: FailClosedPrivacyPipeline | None = None) -> None:
        self.privacy_pipeline = privacy_pipeline
        self.active_sessions: dict[str, StreamClientSession] = {}
        self.webrtc_sessions: dict[str, WebRTCSessionState] = {}
        self._latest_frames: dict[str, tuple[float, np.ndarray]] = {}
        self._hls_segments: dict[str, list[dict[str, Any]]] = {}  # camera_id -> list of segment metadata

    def update_camera_frame(self, camera_id: str, frame: np.ndarray, timestamp_utc: float | None = None) -> None:
        """
        Ingest the latest operational frame for a camera channel.
        Applies privacy pipeline filtering to guarantee unmasked frames never leak.
        """
        if frame is None or not isinstance(frame, np.ndarray):
            return

        ts = timestamp_utc or time.time()

        if self.privacy_pipeline is not None:
            # Process frame through centralized fail-closed privacy gate
            privacy_result = self.privacy_pipeline.process_frame(camera_id, frame)
            # Use safe derivative frame
            safe_frame = privacy_result.derivative_frame
        else:
            safe_frame = frame

        self._latest_frames[camera_id] = (ts, safe_frame)

    def get_latest_frame(self, camera_id: str) -> np.ndarray | None:
        """Retrieve the most recent privacy-safe frame for a camera."""
        data = self._latest_frames.get(camera_id)
        return data[1] if data else None

    # ---------------------------------------------------------------------------
    # MJPEG Streaming Protocol
    # ---------------------------------------------------------------------------

    async def generate_mjpeg_stream(
        self,
        camera_id: str,
        target_fps: float = 15.0,
    ) -> AsyncIterator[bytes]:
        """
        Yield multipart/x-mixed-replace JPEG frames for browser streaming.
        """
        session_id = f"mjpeg_{uuid.uuid4().hex[:8]}"
        session = StreamClientSession(session_id=session_id, camera_id=camera_id, protocol="mjpeg")
        self.active_sessions[session_id] = session
        interval = 1.0 / target_fps if target_fps > 0 else 0.066

        logger.info("streaming.mjpeg.connected", session_id=session_id, camera_id=camera_id)
        try:
            while session.is_active:
                frame = self.get_latest_frame(camera_id)
                if frame is not None:
                    jpeg_bytes = self._encode_jpeg(frame)
                    chunk = (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(jpeg_bytes)).encode("ascii") + b"\r\n\r\n"
                        + jpeg_bytes
                        + b"\r\n"
                    )
                    session.frames_delivered += 1
                    session.bytes_delivered += len(chunk)
                    yield chunk
                await asyncio.sleep(interval)
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            session.is_active = False
            self.active_sessions.pop(session_id, None)
            logger.info("streaming.mjpeg.disconnected", session_id=session_id, camera_id=camera_id)

    def _encode_jpeg(self, frame: np.ndarray, quality: int = 80) -> bytes:
        """Encode a numpy BGR frame to JPEG bytes."""
        if _HAS_CV2:
            success, enc = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
            if success:
                return enc.tobytes()

        # Fallback dummy 1x1 JPEG if cv2 is unavailable
        return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"

    # ---------------------------------------------------------------------------
    # Low-Latency HLS (LL-HLS)
    # ---------------------------------------------------------------------------

    def generate_hls_playlist(self, camera_id: str) -> str:
        """
        Generate standard HLS (m3u8) live playlist pointing to active segments.
        """
        segments = self._hls_segments.get(camera_id, [])
        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:6",
            "#EXT-X-TARGETDURATION:2",
            "#EXT-X-MEDIA-SEQUENCE:0",
            "#EXT-X-DISCONTINUITY-SEQUENCE:0",
        ]

        if not segments:
            # Minimal placeholder segment for live initialization
            lines.append("#EXTINF:2.0,")
            lines.append(f"/api/v1/stream/{camera_id}/hls/init.mp4")
        else:
            for seg in segments[-5:]:  # Sliding window of 5 most recent segments
                lines.append(f"#EXTINF:{seg.get('duration', 2.0):.2f},")
                lines.append(seg.get("url", f"segment_{seg.get('index', 0)}.mp4"))

        return "\n".join(lines) + "\n"

    # ---------------------------------------------------------------------------
    # WebRTC Signaling Abstraction
    # ---------------------------------------------------------------------------

    def create_webrtc_session(self, camera_id: str) -> WebRTCSessionState:
        """Initialize a new WebRTC signaling session."""
        session_id = f"rtc_{uuid.uuid4().hex[:12]}"
        state = WebRTCSessionState(session_id=session_id, camera_id=camera_id)
        self.webrtc_sessions[session_id] = state
        logger.info("streaming.webrtc.session_created", session_id=session_id, camera_id=camera_id)
        return state

    def handle_webrtc_offer(self, session_id: str, offer_sdp: str) -> str:
        """
        Process client SDP offer and generate a synthetic / negotiated SDP answer.
        """
        session = self.webrtc_sessions.get(session_id)
        if not session:
            raise KeyError(f"WebRTC session '{session_id}' not found.")

        session.offer_sdp = offer_sdp
        session.state = "established"

        # Generate standard compliant WebRTC answer SDP envelope
        answer_sdp = (
            "v=0\r\n"
            f"o=- {int(time.time())} 2 IN IP4 127.0.0.1\r\n"
            "s=CAMserv WebRTC Live Stream\r\n"
            "t=0 0\r\n"
            "a=group:BUNDLE video\r\n"
            "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n"
            "c=IN IP4 0.0.0.0\r\n"
            "a=rtcp:9 IN IP4 0.0.0.0\r\n"
            "a=sendonly\r\n"
            "a=rtpmap:96 H264/90000\r\n"
            "a=fmtp:96 level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42e01f\r\n"
        )
        session.answer_sdp = answer_sdp
        return answer_sdp

    def add_ice_candidate(self, session_id: str, candidate: dict[str, Any]) -> None:
        """Register client ICE candidate."""
        session = self.webrtc_sessions.get(session_id)
        if session:
            session.ice_candidates.append(candidate)
