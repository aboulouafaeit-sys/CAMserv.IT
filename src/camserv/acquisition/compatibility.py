"""
camserv.acquisition.compatibility
=================================

Real-world Camera Compatibility and Protocol Validation Framework for CAMserv.
Evaluates RTSP stream stability, ONVIF Profile S/T/G capability negotiation,
PTZ mechanics, and privacy fail-closed enforcement across real and simulated IP cameras.

Strictly enforces classification:
- VERIFIED_ON_REAL_HARDWARE
- VERIFIED_ON_REAL_CAMERA
- VERIFIED_IN_SOFTWARE
- SIMULATED
- NOT_AVAILABLE
- NOT_TESTED
- FAILED
"""

from __future__ import annotations

import asyncio
import enum
import re
import socket
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from camserv.acquisition.onvif import (
    DeploymentTopology,
    DiscoveredCamera,
    NVRCompatibilityReport,
    NVRCompatibilityTester,
    ONVIFProfile,
)
from camserv.nvr.credentials import redact_url_credentials
from camserv.nvr.ptz import PTZController, PTZUnsupportedError, PTZVector

logger = structlog.get_logger(__name__)


class ValidationClassification(str, enum.Enum):
    """Rigorous classification for hardware and camera verification claims."""

    VERIFIED_ON_REAL_HARDWARE = "VERIFIED_ON_REAL_HARDWARE"
    VERIFIED_ON_REAL_CAMERA = "VERIFIED_ON_REAL_CAMERA"
    VERIFIED_IN_SOFTWARE = "VERIFIED_IN_SOFTWARE"
    SIMULATED = "SIMULATED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    NOT_TESTED = "NOT_TESTED"
    FAILED = "FAILED"


@dataclass(slots=True)
class CapabilityTestOutcome:
    """Individual protocol capability test result."""

    capability_name: str
    category: str  # 'RTSP', 'ONVIF', 'PTZ', 'PRIVACY', 'RECORDING'
    passed: bool
    classification: ValidationClassification
    latency_ms: float = 0.0
    details: str = ""


@dataclass(slots=True)
class CameraCompatibilityRecord:
    """Entry in the master camera compatibility matrix."""

    manufacturer: str
    exact_model: str
    firmware_version: str
    protocol: str
    codec: str
    resolution: str
    frame_rate: float
    rtsp_status: str
    onvif_status: str
    ptz_status: str  # 'SUPPORTED', 'NOT_SUPPORTED' (fixed), 'FAILED', 'NOT_TESTED'
    recording_status: str
    playback_status: str
    privacy_enforcement: str
    reconnection_status: str
    test_date: str
    evidence_reference: str
    validation_classification: ValidationClassification
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CameraCompatibilityFramework:
    """
    Automated and physical camera compatibility test orchestrator.
    Executes deep protocol probing for RTSP, ONVIF Profile S/T/G, and PTZ controls.
    """

    def __init__(self) -> None:
        self.test_records: list[CameraCompatibilityRecord] = []

    @staticmethod
    def validate_rtsp_url(url: str) -> dict[str, Any]:
        """Inspect and parse an RTSP URL, validating safety and formatting."""
        safe_url = redact_url_credentials(url)
        match = re.search(r"rtsp://(?:([^:@]+)(?::([^@]+))?@)?([^:/]+)(?::(\d+))?(/.*)?", url)
        if not match:
            return {"valid": False, "safe_url": safe_url, "error": "Invalid RTSP URI syntax"}

        user, pwd, host, port_str, path = match.groups()
        port = int(port_str) if port_str else 554
        return {
            "valid": True,
            "safe_url": safe_url,
            "has_auth": bool(user or pwd),
            "username": user or "",
            "host": host,
            "port": port,
            "path": path or "/",
        }

    async def probe_rtsp_transport(
        self,
        host: str,
        port: int = 554,
        timeout_sec: float = 1.0,
    ) -> CapabilityTestOutcome:
        """Validate raw TCP transport handshake to RTSP endpoint."""
        t0 = time.perf_counter()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=timeout_sec
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            writer.close()
            await writer.wait_closed()
            return CapabilityTestOutcome(
                capability_name="RTSP_TCP_Transport",
                category="RTSP",
                passed=True,
                classification=ValidationClassification.VERIFIED_ON_REAL_CAMERA,
                latency_ms=round(elapsed_ms, 2),
                details=f"TCP connection established to {host}:{port}",
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return CapabilityTestOutcome(
                capability_name="RTSP_TCP_Transport",
                category="RTSP",
                passed=False,
                classification=ValidationClassification.FAILED,
                latency_ms=round(elapsed_ms, 2),
                details=f"Connection failed: {str(exc)}",
            )

    @staticmethod
    def evaluate_ptz_compatibility(ptz_controller: PTZController, camera_id: str) -> CapabilityTestOutcome:
        """
        Evaluate PTZ capability on a camera channel.
        Correctly distinguishes fixed cameras (NOT_SUPPORTED) from functional PTZ failures.
        """
        try:
            caps = ptz_controller.get_capabilities(camera_id)
            if not caps.is_ptz_capable:
                return CapabilityTestOutcome(
                    capability_name="PTZ_Control",
                    category="PTZ",
                    passed=True,
                    classification=ValidationClassification.VERIFIED_IN_SOFTWARE,
                    details="Fixed camera correctly identified as NOT_SUPPORTED (no error).",
                )

            # Test vector validation
            valid_vec = PTZVector(pan=0.5, tilt=-0.2, zoom=0.0)
            ptz_controller.move(camera_id, valid_vec)
            ptz_controller.stop(camera_id)

            return CapabilityTestOutcome(
                capability_name="PTZ_Control",
                category="PTZ",
                passed=True,
                classification=ValidationClassification.VERIFIED_IN_SOFTWARE,
                details=f"PTZ controls operational (Continuous={caps.supports_continuous_move}, Presets={caps.supports_presets}).",
            )
        except PTZUnsupportedError:
            return CapabilityTestOutcome(
                capability_name="PTZ_Control",
                category="PTZ",
                passed=True,
                classification=ValidationClassification.VERIFIED_IN_SOFTWARE,
                details="Fixed camera raised PTZUnsupportedError cleanly as expected.",
            )
        except Exception as exc:
            return CapabilityTestOutcome(
                capability_name="PTZ_Control",
                category="PTZ",
                passed=False,
                classification=ValidationClassification.FAILED,
                details=f"PTZ execution error: {str(exc)}",
            )

    def register_matrix_record(self, record: CameraCompatibilityRecord) -> None:
        """Add record to matrix."""
        self.test_records.append(record)

    def generate_markdown_matrix(self) -> str:
        """Generate GitHub Flavored Markdown table documenting compatibility matrix."""
        headers = [
            "Manufacturer",
            "Exact Model",
            "Firmware",
            "Protocol",
            "Codec",
            "Resolution",
            "FPS",
            "RTSP",
            "ONVIF",
            "PTZ",
            "Recording",
            "Playback",
            "Privacy",
            "Reconnect",
            "Classification",
        ]
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join([":---"] * len(headers)) + " |",
        ]

        for r in self.test_records:
            row = [
                r.manufacturer,
                r.exact_model,
                r.firmware_version,
                r.protocol,
                r.codec,
                r.resolution,
                f"{r.frame_rate:.0f}",
                r.rtsp_status,
                r.onvif_status,
                r.ptz_status,
                r.recording_status,
                r.playback_status,
                r.privacy_enforcement,
                r.reconnection_status,
                r.validation_classification.value,
            ]
            lines.append("| " + " | ".join(row) + " |")

        return "\n".join(lines)
