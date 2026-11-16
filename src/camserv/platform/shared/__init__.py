"""
camserv.platform.shared
=======================

Operating-system-agnostic platform abstractions, interfaces, and path resolvers.
"""

from camserv.platform.shared.credentials import StandardSoftwareCredentialVault
from camserv.platform.shared.interfaces import (
    LocalCameraDevice,
    PlatformCameraBackend,
    PlatformCredentialVault,
    PlatformFilesystem,
    PlatformHardwareProber,
    PlatformServiceManager,
    ServiceState,
    ServiceStatus,
)
from camserv.platform.shared.paths import PathResolver, PlatformPaths

__all__ = [
    "LocalCameraDevice",
    "PathResolver",
    "PlatformCameraBackend",
    "PlatformCredentialVault",
    "PlatformFilesystem",
    "PlatformHardwareProber",
    "PlatformPaths",
    "PlatformServiceManager",
    "ServiceState",
    "ServiceStatus",
    "StandardSoftwareCredentialVault",
]
