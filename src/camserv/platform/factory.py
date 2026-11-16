"""
camserv.platform.factory
========================

Dynamic platform adapter factory for CAMserv.
Detects host operating system and instantiates corresponding platform adapters.
"""

from __future__ import annotations

import os
import sys

from camserv.platform.shared.credentials import StandardSoftwareCredentialVault
from camserv.platform.shared.interfaces import (
    PlatformCameraBackend,
    PlatformCredentialVault,
    PlatformFilesystem,
    PlatformHardwareProber,
    PlatformServiceManager,
)


def is_windows() -> bool:
    """Return True if executing on Microsoft Windows."""
    return sys.platform.startswith("win") or os.name == "nt"


def is_linux() -> bool:
    """Return True if executing on Linux."""
    return sys.platform.startswith("linux") or os.name == "posix"


def get_active_platform_name() -> str:
    """Return 'windows', 'linux', or 'generic'."""
    if is_windows():
        return "windows"
    elif is_linux():
        return "linux"
    return "generic"


def get_platform_service_manager() -> PlatformServiceManager:
    """Instantiate OS-appropriate background service manager."""
    if is_windows():
        from camserv.platform.windows.service import WindowsServiceManager
        return WindowsServiceManager()
    elif is_linux():
        from camserv.platform.linux.service import LinuxSystemdManager
        return LinuxSystemdManager()
    else:
        from camserv.platform.linux.service import LinuxSystemdManager
        return LinuxSystemdManager()


def get_platform_filesystem(force_system: bool | None = None) -> PlatformFilesystem:
    """Instantiate OS-appropriate filesystem and ACL manager."""
    if is_windows():
        from camserv.platform.windows.filesystem import WindowsFilesystem
        return WindowsFilesystem(force_system=force_system)
    elif is_linux():
        from camserv.platform.linux.filesystem import LinuxFilesystem
        return LinuxFilesystem(force_system=force_system)
    else:
        from camserv.platform.linux.filesystem import LinuxFilesystem
        return LinuxFilesystem(force_system=force_system)


def get_platform_credential_vault(master_key: str | bytes | None = None) -> PlatformCredentialVault:
    """Instantiate OS-appropriate secure credential vault."""
    if is_windows():
        from camserv.platform.windows.credentials import WindowsDPAPIVault
        return WindowsDPAPIVault(fallback_key=master_key)
    else:
        return StandardSoftwareCredentialVault(master_key=master_key)


def get_platform_camera_backend() -> PlatformCameraBackend:
    """Instantiate OS-appropriate optical camera discovery backend."""
    if is_windows():
        from camserv.platform.windows.camera import WindowsMediaFoundationCameraBackend
        return WindowsMediaFoundationCameraBackend()
    elif is_linux():
        from camserv.platform.linux.camera import LinuxV4L2CameraBackend
        return LinuxV4L2CameraBackend()
    else:
        from camserv.platform.linux.camera import LinuxV4L2CameraBackend
        return LinuxV4L2CameraBackend()


def get_platform_hardware_prober() -> PlatformHardwareProber:
    """Instantiate OS-appropriate hardware and sensor prober."""
    if is_windows():
        from camserv.platform.windows.hardware import WindowsHardwareProber
        return WindowsHardwareProber()
    elif is_linux():
        from camserv.platform.linux.hardware import LinuxHardwareProber
        return LinuxHardwareProber()
    else:
        from camserv.platform.linux.hardware import LinuxHardwareProber
        return LinuxHardwareProber()
