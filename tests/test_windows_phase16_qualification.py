"""
tests/test_windows_phase16_qualification.py
===========================================

Phase 16 Independent Qualification Test Suite for Native Windows 11 Implementation.
Validates:
1. Windows Service Manager (SCM) lifecycle & Session 0 dispatcher.
2. Native Windows MSI installer packaging, database schema & data preservation policy.
3. Windows Desktop Operator Console & decoupled REST/WebSocket client.
4. Optical Camera Capture via Microsoft Media Foundation & DirectShow.
5. GPU AI inference provider negotiation (DirectML/CUDA/OpenVINO/CPU).
6. Security controls: Windows DPAPI credential protection, NTFS ACLs, and Defender Firewall.
7. Cryptographic invariant verification of the audit log.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from camserv.desktop.client import DesktopServiceClient
from camserv.desktop.console import DesktopOperatorConsole
from camserv.inference.windows_gpu import (
    WindowsExecutionProvider,
    WindowsGpuConfig,
    WindowsInferenceEvaluator,
)
from camserv.platform.shared.interfaces import ServiceState
from camserv.platform.windows.camera import WindowsMediaFoundationCameraBackend
from camserv.platform.windows.credentials import WindowsDPAPIVault
from camserv.platform.windows.filesystem import WindowsFilesystem
from camserv.platform.windows.firewall import WindowsFirewallManager
from camserv.platform.windows.hardware import WindowsHardwareProber
from camserv.platform.windows.service import (
    WindowsServiceManager,
    WindowsServiceRunner,
)
from deploy.windows.build_msi import (
    COMPONENT_ATTR_PERMANENT,
    WindowsMsiBuilder,
)


@pytest.mark.unit
def test_inviolate_audit_log_preserved() -> None:
    """Invariant Rule 1: Audit log must remain exactly 20,977 bytes with verified SHA-256."""
    audit_path = Path("logs/audit.jsonl")
    assert audit_path.exists(), "Audit log file is missing!"
    size = audit_path.stat().st_size
    assert size == 20977, f"Audit log size mismatch: got {size}, expected 20977 bytes"

    content = audit_path.read_bytes()
    digest = hashlib.sha256(content).hexdigest().upper()
    assert (
        digest == "F2A2484A0395140C4449C359200D1763381176A4CC825F56F0E65F881FEC1525"
    ), f"Audit log SHA-256 mismatch: {digest}"


@pytest.mark.unit
def test_windows_service_manager_query() -> None:
    """Verify Windows SCM status querying and parsing."""
    mgr = WindowsServiceManager()
    status = mgr.query_status("CAMservCore")
    assert status.name == "CAMservCore"
    assert status.state in (
        ServiceState.RUNNING,
        ServiceState.STOPPED,
        ServiceState.STARTING,
        ServiceState.STOPPING,
        ServiceState.NOT_INSTALLED,
        ServiceState.UNKNOWN,
    )
    assert mgr.emit_watchdog_heartbeat() is True


@pytest.mark.unit
def test_windows_service_runner_interactive_fallback() -> None:
    """Verify that SCM dispatcher handles interactive invocation gracefully (Win32 error 1063)."""
    runner = WindowsServiceRunner("CAMservCoreTest")
    with patch.object(runner, "run_console", return_value=0) as mock_console:
        code = runner.run_scm_dispatcher()
        assert code == 0
        mock_console.assert_called_once()


@pytest.mark.unit
def test_windows_msi_builder_execution(tmp_path: Path) -> None:
    """Verify that WindowsMsiBuilder produces a valid MSI installer and JSON manifest."""
    builder = WindowsMsiBuilder(
        output_dir=tmp_path / "msi_test",
        version="0.10.0-alpha2",
    )
    msi_path = builder.build()

    assert msi_path.exists()
    assert msi_path.name == "camserv_0.10.0-alpha2_win64.msi"
    size = msi_path.stat().st_size
    assert size > 10000, f"MSI size too small: {size} bytes"

    manifest_path = msi_path.with_suffix(".json")
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["package_name"] == "camserv_0.10.0-alpha2_win64.msi"
    assert manifest["version"] == "0.10.0-alpha2"
    assert manifest["architecture"] == "x64"
    assert manifest["size_bytes"] == size
    assert manifest["sha256"] == hashlib.sha256(msi_path.read_bytes()).hexdigest().upper()


@pytest.mark.unit
def test_windows_msi_tables_and_service_schema(tmp_path: Path) -> None:
    """Inspect generated MSI database schema via Win32 msi.dll API."""
    builder = WindowsMsiBuilder(
        output_dir=tmp_path / "msi_inspect",
        version="0.10.0-alpha2",
    )
    msi_path = builder.build()

    msi = ctypes.windll.msi
    h_db = wintypes.HANDLE()
    assert msi.MsiOpenDatabaseW(str(msi_path), 0, ctypes.byref(h_db)) == 0

    try:
        # Check Property table
        h_view = wintypes.HANDLE()
        assert (
            msi.MsiDatabaseOpenViewW(
                h_db,
                "SELECT Property, Value FROM Property WHERE Property='ProductName'",
                ctypes.byref(h_view),
            )
            == 0
        )
        assert msi.MsiViewExecute(h_view, 0) == 0
        h_rec = wintypes.HANDLE()
        assert msi.MsiViewFetch(h_view, ctypes.byref(h_rec)) == 0
        buf = ctypes.create_unicode_buffer(128)
        sz = wintypes.DWORD(128)
        msi.MsiRecordGetStringW(h_rec, 2, buf, ctypes.byref(sz))
        assert "CAMserv" in buf.value
        msi.MsiCloseHandle(h_rec)
        msi.MsiViewClose(h_view)
        msi.MsiCloseHandle(h_view)

        # Check ServiceInstall table
        assert (
            msi.MsiDatabaseOpenViewW(
                h_db,
                "SELECT Name, ServiceType, StartType FROM ServiceInstall",
                ctypes.byref(h_view),
            )
            == 0
        )
        assert msi.MsiViewExecute(h_view, 0) == 0
        assert msi.MsiViewFetch(h_view, ctypes.byref(h_rec)) == 0
        msi.MsiRecordGetStringW(h_rec, 1, buf, ctypes.byref(sz))
        assert buf.value == "CAMservCore"
        service_type = msi.MsiRecordGetInteger(h_rec, 2)
        start_type = msi.MsiRecordGetInteger(h_rec, 3)
        assert service_type == 16  # SERVICE_WIN32_OWN_PROCESS
        assert start_type == 2    # SERVICE_AUTO_START
        msi.MsiCloseHandle(h_rec)
        msi.MsiViewClose(h_view)
        msi.MsiCloseHandle(h_view)

        # Check Permanent Data Preservation on Recordings and Vault components
        assert (
            msi.MsiDatabaseOpenViewW(
                h_db,
                "SELECT Component, Attributes FROM Component WHERE Component='cmp_recordings' OR Component='cmp_vault'",
                ctypes.byref(h_view),
            )
            == 0
        )
        assert msi.MsiViewExecute(h_view, 0) == 0
        count = 0
        while msi.MsiViewFetch(h_view, ctypes.byref(h_rec)) == 0:
            attrs = msi.MsiRecordGetInteger(h_rec, 2)
            assert (attrs & COMPONENT_ATTR_PERMANENT) != 0, "Component missing permanent attribute!"
            count += 1
            msi.MsiCloseHandle(h_rec)
        assert count == 2, "Expected 2 permanent preservation components (recordings and vault)"
        msi.MsiViewClose(h_view)
        msi.MsiCloseHandle(h_view)

    finally:
        msi.MsiCloseHandle(h_db)


@pytest.mark.unit
def test_desktop_operator_console_headless() -> None:
    """Verify DesktopOperatorConsole initializes cleanly in headless mode."""
    console = DesktopOperatorConsole(headless=True)
    telem = console.update_telemetry()
    assert isinstance(telem, dict)
    assert "service_name" in telem
    assert "service_state" in telem
    assert "os" in telem
    assert telem["os"] == "Windows"
    assert telem["logical_cores"] >= 1
    assert telem["ram_total_mb"] > 0


@pytest.mark.unit
def test_desktop_client_unauthenticated_and_offline() -> None:
    """Verify DesktopServiceClient handles offline network gracefully."""
    # Connect to invalid port
    client = DesktopServiceClient(base_url="http://127.0.0.1:59999")
    health = client.check_health()
    assert health is None
    assert client.is_connected is False
    assert client.last_error is not None

    cameras = client.get_cameras()
    assert cameras == []

    recordings = client.get_recordings()
    assert recordings == []

    events = client.get_events()
    assert events == []


@pytest.mark.unit
def test_desktop_client_mock_api_interaction() -> None:
    """Verify DesktopServiceClient handles authenticated REST responses."""
    client = DesktopServiceClient(base_url="http://127.0.0.1:8080")

    mock_token_resp = {"access_token": "mock_jwt_token_12345", "token_type": "bearer"}
    mock_cameras_resp = [
        {"id": "cam-01", "name": "Front Gate", "rtsp_url": "rtsp://10.0.0.1/stream1", "is_active": True}
    ]
    mock_events_resp = [
        {"id": "evt-01", "camera_id": "cam-01", "detection_class": "person", "confidence": 0.95}
    ]

    with patch.object(client, "_request") as mock_req:
        # 1. Test Auth
        mock_req.return_value = mock_token_resp
        assert client.authenticate("admin", "secret") is True
        assert client.token == "mock_jwt_token_12345"
        assert client.is_connected is True

        # 2. Test Get Cameras
        mock_req.return_value = mock_cameras_resp
        cams = client.get_cameras()
        assert len(cams) == 1
        assert cams[0]["name"] == "Front Gate"

        # 3. Test Get Events
        mock_req.return_value = mock_events_resp
        evts = client.get_events()
        assert len(evts) == 1
        assert evts[0]["detection_class"] == "person"

        # 4. Test Acknowledge Event
        mock_req.return_value = {"status": "ok"}
        assert client.acknowledge_event("evt-01", "Operator verified") is True


@pytest.mark.unit
def test_windows_camera_dual_backend_probe() -> None:
    """Verify Windows camera backend enumerates devices and identifies capture backend."""
    backend = WindowsMediaFoundationCameraBackend()
    assert backend.get_backend_name() == "media_foundation"
    devices = backend.enumerate_local_cameras()
    assert len(devices) >= 1
    dev = devices[0]
    assert dev.backend in ("media_foundation", "directshow", "synthetic")
    assert len(dev.supported_resolutions) >= 1


@pytest.mark.unit
def test_windows_hardware_prober_real_telemetry() -> None:
    """Verify WindowsHardwareProber retrieves real CPU, RAM, and GPU telemetry on Windows."""
    prober = WindowsHardwareProber()
    cpu_ram = prober.probe_cpu_and_ram()
    assert cpu_ram["os"] == "Windows"
    assert cpu_ram["logical_cores"] >= 1
    assert cpu_ram["ram_total_mb"] > 1024
    assert cpu_ram["ram_available_mb"] > 0

    gpus = prober.probe_gpus()
    assert isinstance(gpus, list)
    if gpus:
        assert "name" in gpus[0]
        assert "memory_total_mb" in gpus[0]


@pytest.mark.unit
def test_windows_gpu_inference_evaluator() -> None:
    """Verify WindowsInferenceEvaluator establishes fallback chain with CPU resilience."""
    evaluator = WindowsInferenceEvaluator()
    config = evaluator.evaluate()
    assert isinstance(config, WindowsGpuConfig)
    assert WindowsExecutionProvider.CPU in config.fallback_chain
    assert config.primary_provider in (
        WindowsExecutionProvider.CUDA,
        WindowsExecutionProvider.DIRECTML,
        WindowsExecutionProvider.CPU,
    )


@pytest.mark.unit
def test_windows_dpapi_machine_protection() -> None:
    """Verify DPAPI credential store round-trip machine protection."""
    vault = WindowsDPAPIVault()
    secret = b"TopSecretCameraPassword!12345"
    protected = vault.protect_secret(secret, description="test_cred")
    assert protected != secret
    assert len(protected) > 20

    unprotected = vault.unprotect_secret(protected, description="test_cred")
    assert unprotected == secret


@pytest.mark.unit
def test_windows_filesystem_ntfs_acls(tmp_path: Path) -> None:
    """Verify WindowsFilesystem directory setup and permission controls."""
    fs = WindowsFilesystem(force_system=False)
    fs.initialize_filesystem()

    rec_dir = fs.get_recordings_dir()
    vault_dir = fs.get_vault_dir()
    assert rec_dir.exists()
    assert vault_dir.exists()

    # Verify applying NTFS ACL does not throw exceptions
    assert fs.secure_directory(rec_dir, is_sensitive=True) is True
    assert fs.secure_directory(vault_dir, is_sensitive=True) is True


@pytest.mark.unit
def test_windows_firewall_rule_synthesis() -> None:
    """Verify WindowsFirewallManager configures HTTP and RTSP rules."""
    fw = WindowsFirewallManager()
    with patch.object(fw, "_run_netsh", return_value=(0, "Ok.")) as mock_netsh:
        assert fw.add_inbound_port_rule("CAMserv HTTP API", 8080, "TCP", "CAMserv HTTP API") is True
        assert fw.add_inbound_port_rule("CAMserv RTSP Server", 8554, "TCP", "CAMserv RTSP Server") is True
        assert fw.remove_rule("CAMserv HTTP API") is True
        assert mock_netsh.call_count == 3

        default_rules = fw.configure_camserv_default_rules()
        assert default_rules["api_web"] is True
        assert default_rules["rtsp_tcp"] is True
        assert default_rules["onvif_discovery"] is True
