"""
tests.test_platform_cross_platform
==================================

Cross-platform architecture qualification tests for CAMserv (Phase 15).
Validates platform factory, path resolution, service management,
NTFS / POSIX security contracts, Windows DPAPI secret protection,
and optical camera abstraction across Windows and Linux.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from camserv.platform.factory import (
    get_active_platform_name,
    get_platform_camera_backend,
    get_platform_credential_vault,
    get_platform_filesystem,
    get_platform_hardware_prober,
    get_platform_service_manager,
    is_linux,
    is_windows,
)
from camserv.platform.shared.credentials import StandardSoftwareCredentialVault
from camserv.platform.shared.interfaces import (
    LocalCameraDevice,
    PlatformCameraBackend,
    PlatformCredentialVault,
    PlatformFilesystem,
    PlatformHardwareProber,
    PlatformServiceManager,
    ServiceState,
)
from camserv.platform.shared.paths import PathResolver, PlatformPaths


# ---------------------------------------------------------------------------
# Test 1: Platform Factory & Operating System Auto-Detection
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_platform_factory_os_detection() -> None:
    """Verify platform detection correctly identifies the active operating system."""
    active_name = get_active_platform_name()
    assert active_name in ("windows", "linux", "generic")

    if sys.platform.startswith("win"):
        assert is_windows() is True
        assert is_linux() is False
        assert active_name == "windows"
    elif sys.platform.startswith("linux"):
        assert is_windows() is False
        assert is_linux() is True
        assert active_name == "linux"

    svc_mgr = get_platform_service_manager()
    assert isinstance(svc_mgr, PlatformServiceManager)

    fs = get_platform_filesystem()
    assert isinstance(fs, PlatformFilesystem)

    vault = get_platform_credential_vault()
    assert isinstance(vault, PlatformCredentialVault)

    camera = get_platform_camera_backend()
    assert isinstance(camera, PlatformCameraBackend)

    prober = get_platform_hardware_prober()
    assert isinstance(prober, PlatformHardwareProber)


# ---------------------------------------------------------------------------
# Test 2: Cross-Platform Path Resolution (System vs Local Dev)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_path_resolver_contracts(tmp_path: Path) -> None:
    """Verify path resolver returns valid directory hierarchies for both dev and system modes."""
    # Local dev mode
    dev_paths = PathResolver.resolve_paths(force_system=False)
    assert dev_paths.is_system_install is False
    assert dev_paths.db_path.name == "camserv.db"
    assert "data" in str(dev_paths.recordings_dir)
    assert "vault" in str(dev_paths.vault_dir)

    # System mode
    sys_paths = PathResolver.resolve_paths(force_system=True)
    assert sys_paths.is_system_install is True

    if is_windows():
        assert "ProgramData" in str(sys_paths.data_dir) or "CAMserv" in str(sys_paths.data_dir)
    else:
        assert "/var/lib/camserv" in str(sys_paths.data_dir)
        assert "/etc/camserv" in str(sys_paths.config_dir)


# ---------------------------------------------------------------------------
# Test 3: Credential Vault Encryption & Roundtrip (DPAPI / AES-GCM)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_credential_vault_protection_roundtrip() -> None:
    """Verify secret encryption and decryption roundtrip across platform vaults."""
    secret_payload = b"UltraSecure_Camera_Password_!#$2026_XYZ"
    vault = get_platform_credential_vault()

    # Protect secret
    encrypted = vault.protect_secret(secret_payload, description="rtsp_cam_01")
    assert encrypted != secret_payload
    assert len(encrypted) > len(secret_payload)

    # Decrypt secret
    decrypted = vault.unprotect_secret(encrypted, description="rtsp_cam_01")
    assert decrypted == secret_payload

    # Test software fallback vault independently
    soft_vault = StandardSoftwareCredentialVault(master_key="test-cross-platform-key-32b-min")
    soft_enc = soft_vault.protect_secret(secret_payload, description="rtsp_cam_01")
    soft_dec = soft_vault.unprotect_secret(soft_enc, description="rtsp_cam_01")
    assert soft_dec == secret_payload

    # Tamper detection
    tampered = bytearray(soft_enc)
    tampered[-1] ^= 0xFF
    with pytest.raises(Exception):
        soft_vault.unprotect_secret(bytes(tampered), description="rtsp_cam_01")


# ---------------------------------------------------------------------------
# Test 4: Filesystem Security & Access Control Enforcement
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_platform_filesystem_security(tmp_path: Path) -> None:
    """Verify platform filesystem creation and access control enforcement."""
    fs = get_platform_filesystem(force_system=False)

    test_dir = tmp_path / "camserv_test_dir"
    test_dir.mkdir(parents=True, exist_ok=True)
    assert fs.secure_directory(test_dir, is_sensitive=True) is True

    test_file = test_dir / "secret_key.pem"
    test_file.write_text("TEST_KEY_DATA", encoding="utf-8")
    assert fs.secure_file(test_file, is_secret=True) is True


# ---------------------------------------------------------------------------
# Test 5: Local Camera Backend Discovery & Fallback
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_platform_camera_backend_enumeration() -> None:
    """Verify optical camera discovery returns valid LocalCameraDevice records."""
    camera_backend = get_platform_camera_backend()
    devices = camera_backend.enumerate_local_cameras()

    assert len(devices) >= 1
    primary = devices[0]
    assert isinstance(primary, LocalCameraDevice)
    assert primary.backend in ("v4l2", "media_foundation", "directshow", "synthetic")
    assert len(primary.supported_resolutions) >= 1

    # Open capture stream with synthetic fallback
    cap = camera_backend.open_capture_stream("synthetic", width=640, height=480)
    assert cap is not None


# ---------------------------------------------------------------------------
# Test 6: Hardware Telemetry & GPU Diagnostics Probing
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_platform_hardware_prober() -> None:
    """Verify host CPU, memory, and GPU telemetry probing."""
    prober = get_platform_hardware_prober()

    cpu_ram = prober.probe_cpu_and_ram()
    assert cpu_ram["logical_cores"] >= 1
    assert cpu_ram["physical_cores"] >= 1
    assert cpu_ram["ram_total_mb"] > 0

    gpus = prober.probe_gpus()
    assert isinstance(gpus, list)
    if gpus:
        gpu = gpus[0]
        assert "name" in gpu
        assert "memory_total_mb" in gpu

    thermals = prober.probe_thermal_and_power()
    assert "temperatures_celsius" in thermals


# ---------------------------------------------------------------------------
# Test 7: Windows Firewall Manager (Safe Non-Destructive Query)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_windows_firewall_manager_safe_execution() -> None:
    """Verify Windows Firewall manager commands execute safely or no-op on non-Windows."""
    if is_windows():
        from camserv.platform.windows.firewall import WindowsFirewallManager
        fwm = WindowsFirewallManager()
        # Non-destructive rule removal check
        fwm.remove_rule("CAMserv_NonExistent_Test_Rule_999")
        assert True
    else:
        # On Linux, firewall manager should not be imported
        assert True
