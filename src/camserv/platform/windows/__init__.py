"""
camserv.platform.windows
========================

Microsoft Windows platform adapter implementation.
"""

from camserv.platform.windows.camera import WindowsMediaFoundationCameraBackend
from camserv.platform.windows.credentials import WindowsDPAPIVault
from camserv.platform.windows.filesystem import WindowsFilesystem
from camserv.platform.windows.firewall import WindowsFirewallManager
from camserv.platform.windows.hardware import WindowsHardwareProber
from camserv.platform.windows.service import WindowsServiceManager, WindowsServiceRunner

__all__ = [
    "WindowsDPAPIVault",
    "WindowsFilesystem",
    "WindowsFirewallManager",
    "WindowsHardwareProber",
    "WindowsMediaFoundationCameraBackend",
    "WindowsServiceManager",
    "WindowsServiceRunner",
]
