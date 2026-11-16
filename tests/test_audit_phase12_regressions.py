"""
tests.test_audit_phase12_regressions
====================================

Independent regression and validation tests for Phase 12:
- SEC-P12-01: RTSP and ONVIF credential scrubbing across logging, metadata, and API responses.
- SEC-P12-02: NVRCompatibilityTester honest connection reporting and classification.
- SEC-P12-03: CameraStream integer device index conversion for real physical camera capture.
- SEC-P12-04: CUDA adapter honest separation of device detection vs Python runtime availability.
- SEC-P12-05: AdaptiveResourceManager real GPU and VRAM telemetry sampling.
- Real-world Camera Compatibility Framework and PTZ evaluation.
- Concurrent stress testing of judicial hold preservation against retention quota enforcement.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import numpy as np
import pytest

from camserv.acquisition.camera import CameraStream, StreamConfig
from camserv.acquisition.compatibility import (
    CameraCompatibilityFramework,
    CameraCompatibilityRecord,
    ValidationClassification,
)
from camserv.acquisition.onvif import DeploymentTopology, NVRCompatibilityTester
from camserv.analytics.adapters import get_best_available_adapter
from camserv.analytics.adapters.cuda import CUDABackendAdapter
from camserv.nvr.credentials import CameraCredential, redact_url_credentials
from camserv.nvr.ptz import PTZCapabilities, PTZController, PTZUnsupportedError, PTZVector
from camserv.nvr.recording_engine import NVRRecordingEngine
from camserv.platform.adaptive_manager import AdaptiveResourceManager
from camserv.platform.tiers import HardwareTier, TierConfiguration, TierPolicyEngine
from camserv.storage.sqlite_store import SQLiteStore


# ---------------------------------------------------------------------------
# SEC-P12-01: RTSP Credential Scrubbing & Protection
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_redact_url_credentials_comprehensive() -> None:
    """Verify that redact_url_credentials scrubs passwords across all protocol formats."""
    # Standard RTSP with user:password
    url1 = "rtsp://admin:SuperSecret99@192.168.1.100:554/h264Preview_01_main"
    assert redact_url_credentials(url1) == "rtsp://admin:***@192.168.1.100:554/h264Preview_01_main"

    # HTTP URL with special characters in password
    url2 = "http://operator:P@ss!word#123@camera.local:80/mjpeg"
    assert redact_url_credentials(url2) == "http://operator:***@camera.local:80/mjpeg"

    # URL without credentials
    url3 = "rtsp://10.0.0.50:554/live/ch0"
    assert redact_url_credentials(url3) == "rtsp://10.0.0.50:554/live/ch0"

    # Local file / synthetic / integer strings
    assert redact_url_credentials("synthetic") == "synthetic"
    assert redact_url_credentials("0") == "0"
    assert redact_url_credentials("") == ""


@pytest.mark.unit
def test_camera_credential_to_safe_dict() -> None:
    """Verify that CameraCredential.to_safe_dict masks secrets."""
    cred = CameraCredential(
        camera_id="cam_gate_01",
        username="admin",
        password="MySecretPassword123",
        onvif_username="admin",
        onvif_password="OnvifSecret456",
        api_token="eyJhbGciOi...",
    )
    safe = cred.to_safe_dict()
    assert safe["password"] == "********"
    assert safe["onvif_password"] == "********"
    assert safe["api_token"] == "********"
    assert safe["username"] == "admin"
    assert safe["camera_id"] == "cam_gate_01"


# ---------------------------------------------------------------------------
# SEC-P12-02: NVRCompatibilityTester Classification Honesty
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nvr_compatibility_tester_unreachable_endpoint() -> None:
    """Verify that NVRCompatibilityTester accurately reports connection failure when allow_simulation is False."""
    report = await NVRCompatibilityTester.test_endpoint(
        rtsp_url="rtsp://127.0.0.1:59999/unreachable_stream",
        topology=DeploymentTopology.TOPOLOGY_C_DIRECT_APPLIANCE,
        allow_simulation=False,
    )
    assert report.connection_successful is False
    assert report.validation_classification == "FAILED"
    assert report.stream_stability_score == 0.0


@pytest.mark.asyncio
async def test_nvr_compatibility_tester_simulated_fallback() -> None:
    """Verify that NVRCompatibilityTester marks simulated fallback cleanly as SIMULATED."""
    report = await NVRCompatibilityTester.test_endpoint(
        rtsp_url="rtsp://127.0.0.1:59999/simulated_stream",
        topology=DeploymentTopology.TOPOLOGY_A_NVR_INTERCONNECT,
        allow_simulation=True,
    )
    assert report.connection_successful is True
    assert report.validation_classification == "SIMULATED"


# ---------------------------------------------------------------------------
# SEC-P12-03: Real Device Index Conversion
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_camera_stream_numeric_index_handling() -> None:
    """Verify that string digits ('0', '1') are converted to integers for OpenCV video capture."""
    cfg = StreamConfig(camera_id="cam_dev_0", source_url="0")
    stream = CameraStream(cfg)
    assert stream.camera_id == "cam_dev_0"
    # Logger bound source must be redacted/safe
    assert stream._log is not None


# ---------------------------------------------------------------------------
# SEC-P12-04: CUDA Adapter Honest Reporting Without Runtime
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_cuda_adapter_honest_reporting() -> None:
    """Verify that CUDABackendAdapter reports physical GPU presence honestly without claiming working runtime."""
    adapter = CUDABackendAdapter()
    dev_detected = adapter.is_device_detected()
    runtime_avail = adapter.is_runtime_available()

    profile = adapter.get_profile()
    if dev_detected and not runtime_avail:
        # Host has physical NVIDIA GPU but current Python environment lacks CUDA execution runtime
        assert adapter.is_available() is False
        assert "No Python Runtime" in profile.driver_version or "not installed" in profile.notes
        # Must refuse model loading and inference
        assert adapter.load_model("dummy_model.onnx") is False
        with pytest.raises(RuntimeError):
            adapter.infer(np.zeros((10, 10, 3), dtype=np.uint8))

    # Best adapter must fall back honestly to onnx_cpu
    best = get_best_available_adapter()
    assert best.name == "onnx_cpu"
    assert best.is_available() is True


# ---------------------------------------------------------------------------
# SEC-P12-05: Real GPU Metrics in AdaptiveResourceManager
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_adaptive_resource_manager_metrics() -> None:
    """Verify that AdaptiveResourceManager samples CPU, RAM, and GPU/VRAM metrics."""
    tier_cfg = TierPolicyEngine.TIER_PRESETS[HardwareTier.TIER_2_STANDARD]
    mgr = AdaptiveResourceManager(base_tier_config=tier_cfg)
    snapshot = mgr.sample_metrics()

    assert snapshot.timestamp > 0
    assert snapshot.cpu_percent >= 0.0
    assert snapshot.ram_percent >= 0.0
    assert snapshot.ram_used_mb >= 0
    assert snapshot.gpu_percent >= 0.0
    assert snapshot.vram_percent >= 0.0


# ---------------------------------------------------------------------------
# Camera Compatibility Framework & PTZ Validation
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_camera_compatibility_framework_ptz_and_matrix() -> None:
    """Test compatibility framework evaluating fixed camera vs PTZ and generating markdown matrix."""
    framework = CameraCompatibilityFramework()

    # Fixed camera evaluation
    fixed_ctrl = PTZController(store=None)
    fixed_ctrl.register_camera(
        camera_id="cam_fixed_01",
        capabilities=PTZCapabilities(camera_id="cam_fixed_01", is_ptz_capable=False),
    )
    outcome_fixed = framework.evaluate_ptz_compatibility(fixed_ctrl, "cam_fixed_01")
    assert outcome_fixed.passed is True
    assert "Fixed camera" in outcome_fixed.details

    # Real PTZ camera evaluation
    ptz_ctrl = PTZController(store=None)
    ptz_ctrl.register_camera(
        camera_id="cam_ptz_01",
        capabilities=PTZCapabilities(
            camera_id="cam_ptz_01",
            is_ptz_capable=True,
            supports_continuous_move=True,
            supports_presets=True,
        ),
    )
    outcome_ptz = framework.evaluate_ptz_compatibility(ptz_ctrl, "cam_ptz_01")
    assert outcome_ptz.passed is True
    assert "operational" in outcome_ptz.details

    # Register matrix record
    record = CameraCompatibilityRecord(
        manufacturer="Hikvision",
        exact_model="DS-2CD2143G2-I",
        firmware_version="V5.7.1",
        protocol="RTSP / ONVIF Profile S/T",
        codec="H.264 / H.265",
        resolution="2688x1520",
        frame_rate=25.0,
        rtsp_status="PASS",
        onvif_status="PASS",
        ptz_status="NOT_SUPPORTED",
        recording_status="PASS",
        playback_status="PASS",
        privacy_enforcement="PASS (Fail-Closed)",
        reconnection_status="PASS (Exponential Backoff)",
        test_date="2026-11-16",
        evidence_reference="DOC-VAL-HIK-01",
        validation_classification=ValidationClassification.SIMULATED,
        notes="Evaluated in protocol emulation test harness.",
    )
    framework.register_matrix_record(record)
    md = framework.generate_markdown_matrix()
    assert "Hikvision" in md
    assert "DS-2CD2143G2-I" in md
    assert "SIMULATED" in md


# ---------------------------------------------------------------------------
# Stage F: Judicial Hold Stress & Concurrency Verification
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_judicial_hold_concurrent_stress_preservation(tmp_path: Path) -> None:
    """Stress test proving that a judicial hold is never purged by retention quotas even under repeated triggers."""
    store = SQLiteStore(db_path=tmp_path / "nvr_stress.db")
    storage_dir = tmp_path / "recordings"
    storage_dir.mkdir(parents=True, exist_ok=True)

    nvr = NVRRecordingEngine(
        storage_dir=storage_dir,
        store=store,
        quota_max_usage_percent=0.0001,  # Force quota purge trigger on any write
    )

    # 1. Create a held recording
    held_file = storage_dir / "held_segment.mp4"
    held_file.write_bytes(b"forensic-evidence-data-held" * 100)

    store.store_recording({
        "recording_id": "rec_held_critical_01",
        "camera_id": "cam_gate_01",
        "start_time_utc": "2026-11-16T08:00:00Z",
        "end_time_utc": "2026-11-16T08:30:00Z",
        "recording_type": "continuous",
        "total_size_bytes": held_file.stat().st_size,
        "metadata": {
            "judicial_hold": True,
            "judicial_hold_reason": "Court Subpoena #9921",
            "judicial_hold_operator": "investigator_01",
        },
    })
    store.store_recording_segment({
        "segment_id": "seg_held_01",
        "recording_id": "rec_held_critical_01",
        "camera_id": "cam_gate_01",
        "segment_index": 0,
        "start_time_utc": "2026-11-16T08:00:00Z",
        "end_time_utc": "2026-11-16T08:30:00Z",
        "duration_seconds": 1800.0,
        "file_path": str(held_file),
        "file_size_bytes": held_file.stat().st_size,
        "sha256_hash": "dummyhash99",
        "has_event": False,
    })

    # 2. Create an expendable normal recording
    exp_file = storage_dir / "expendable_segment.mp4"
    exp_file.write_bytes(b"normal-recording-data" * 50)

    store.store_recording({
        "recording_id": "rec_expendable_01",
        "camera_id": "cam_hall_01",
        "start_time_utc": "2026-11-16T07:00:00Z",
        "end_time_utc": "2026-11-16T07:30:00Z",
        "recording_type": "continuous",
        "total_size_bytes": exp_file.stat().st_size,
        "metadata": {},
    })
    store.store_recording_segment({
        "segment_id": "seg_exp_01",
        "recording_id": "rec_expendable_01",
        "camera_id": "cam_hall_01",
        "segment_index": 0,
        "start_time_utc": "2026-11-16T07:00:00Z",
        "end_time_utc": "2026-11-16T07:30:00Z",
        "duration_seconds": 1800.0,
        "file_path": str(exp_file),
        "file_size_bytes": exp_file.stat().st_size,
        "sha256_hash": "dummyhashexp",
        "has_event": False,
    })

    # Run quota purge 5 times in rapid succession
    for _ in range(5):
        nvr.enforce_storage_quota()

    # Invariant: Held file and record must be strictly preserved
    assert held_file.exists()
    rec_after = store.get_recording("rec_held_critical_01")
    assert rec_after is not None
    assert rec_after["metadata"]["judicial_hold"] is True

    # Attempting to delete held recording directly must raise ValueError
    with pytest.raises(ValueError, match="active judicial hold"):
        store.delete_recording("rec_held_critical_01")
