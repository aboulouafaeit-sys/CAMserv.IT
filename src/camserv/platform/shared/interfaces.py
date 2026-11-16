"""
camserv.platform.shared.interfaces
==================================

Abstract Base Classes and contracts for platform-specific adapters.
Decouples operating system infrastructure (systemd vs Windows Service,
POSIX permissions vs Windows ACLs, V4L2 vs Media Foundation) from CAMserv core.
"""

from __future__ import annotations

import abc
import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ServiceState(str, enum.Enum):
    """Normalized status of a background platform service."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"
    NOT_INSTALLED = "not_installed"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class ServiceStatus:
    """Telemetry report for a managed service daemon."""

    name: str
    state: ServiceState
    pid: int | None = None
    exit_code: int | None = None
    uptime_sec: float = 0.0
    details: str = ""


@dataclass(slots=True)
class LocalCameraDevice:
    """Metadata describing a physically connected optical camera."""

    index: int
    name: str
    backend: str              # "v4l2", "media_foundation", "directshow", "synthetic"
    device_path: str = ""     # "/dev/video0" or Windows device instance path
    is_available: bool = True
    supported_resolutions: list[tuple[int, int]] = field(default_factory=list)
    supported_formats: list[str] = field(default_factory=list)


class PlatformServiceManager(abc.ABC):
    """Abstract interface for system background service management."""

    @abc.abstractmethod
    def install_service(
        self,
        name: str,
        display_name: str,
        description: str,
        exec_path: str,
        args: list[str] | None = None,
        dependencies: list[str] | None = None,
    ) -> bool:
        """Register a new service with the OS service controller."""
        raise NotImplementedError

    @abc.abstractmethod
    def uninstall_service(self, name: str) -> bool:
        """Remove a service registration from the OS."""
        raise NotImplementedError

    @abc.abstractmethod
    def start_service(self, name: str) -> bool:
        """Command the OS service manager to start the service."""
        raise NotImplementedError

    @abc.abstractmethod
    def stop_service(self, name: str, timeout_sec: float = 10.0) -> bool:
        """Command the OS service manager to gracefully terminate the service."""
        raise NotImplementedError

    @abc.abstractmethod
    def restart_service(self, name: str) -> bool:
        """Command the OS service manager to restart the service."""
        raise NotImplementedError

    @abc.abstractmethod
    def query_status(self, name: str) -> ServiceStatus:
        """Query real-time execution state of a service."""
        raise NotImplementedError

    @abc.abstractmethod
    def is_service_installed(self, name: str) -> bool:
        """Check whether a given service is registered with the host."""
        raise NotImplementedError

    @abc.abstractmethod
    def emit_watchdog_heartbeat(self) -> bool:
        """Send a keepalive signal to the OS watchdog supervisor."""
        raise NotImplementedError


class PlatformFilesystem(abc.ABC):
    """Abstract interface for operating-system directory layouts and security."""

    @abc.abstractmethod
    def get_config_dir(self) -> Path:
        """Base directory for configuration files (/etc/camserv or %ProgramData%/CAMserv/config)."""
        raise NotImplementedError

    @abc.abstractmethod
    def get_data_dir(self) -> Path:
        """Base directory for application databases and states (/var/lib/camserv or %ProgramData%/CAMserv/data)."""
        raise NotImplementedError

    @abc.abstractmethod
    def get_recordings_dir(self) -> Path:
        """Storage directory for continuous video recording segments."""
        raise NotImplementedError

    @abc.abstractmethod
    def get_vault_dir(self) -> Path:
        """Storage directory for cryptographically signed forensic evidence archives."""
        raise NotImplementedError

    @abc.abstractmethod
    def get_log_dir(self) -> Path:
        """Directory for diagnostic and audit logs (/var/log/camserv or %ProgramData%/CAMserv/logs)."""
        raise NotImplementedError

    @abc.abstractmethod
    def get_cache_dir(self) -> Path:
        """Directory for transient cache files and frame rings."""
        raise NotImplementedError

    @abc.abstractmethod
    def secure_directory(self, path: Path, is_sensitive: bool = False) -> bool:
        """Apply restrictive platform access control permissions to a directory."""
        raise NotImplementedError

    @abc.abstractmethod
    def secure_file(self, path: Path, is_secret: bool = False) -> bool:
        """Apply restrictive platform access control permissions to a file."""
        raise NotImplementedError

    @abc.abstractmethod
    def initialize_filesystem(self) -> bool:
        """Idempotently create and secure all required platform directories."""
        raise NotImplementedError


class PlatformCredentialVault(abc.ABC):
    """Abstract interface for hardware-bound or OS-protected secret encryption."""

    @abc.abstractmethod
    def protect_secret(self, secret_bytes: bytes, description: str = "") -> bytes:
        """Encrypt secret bytes using OS-protected keys (DPAPI on Windows, AES-GCM on Linux)."""
        raise NotImplementedError

    @abc.abstractmethod
    def unprotect_secret(self, encrypted_bytes: bytes) -> bytes:
        """Decrypt secret bytes using OS-protected keys."""
        raise NotImplementedError

    @abc.abstractmethod
    def is_hardware_bound(self) -> bool:
        """Return True if secret encryption is bound to TPM / hardware / machine identity."""
        raise NotImplementedError


class PlatformCameraBackend(abc.ABC):
    """Abstract interface for local optical camera capture and enumeration."""

    @abc.abstractmethod
    def enumerate_local_cameras(self) -> list[LocalCameraDevice]:
        """Discover physically connected optical camera sensors."""
        raise NotImplementedError

    @abc.abstractmethod
    def open_capture_stream(
        self,
        device_index_or_path: int | str,
        width: int | None = None,
        height: int | None = None,
        fps: int | None = None,
    ) -> Any:
        """Initialize and open an optical camera video capture channel."""
        raise NotImplementedError

    @abc.abstractmethod
    def get_backend_name(self) -> str:
        """Name of the active media capture backend."""
        raise NotImplementedError


class PlatformHardwareProber(abc.ABC):
    """Abstract interface for hardware diagnostics and sensor monitoring."""

    @abc.abstractmethod
    def probe_cpu_and_ram(self) -> dict[str, Any]:
        """Query CPU cores, load, and total/available system RAM."""
        raise NotImplementedError

    @abc.abstractmethod
    def probe_gpus(self) -> list[dict[str, Any]]:
        """Query discrete and integrated GPUs, drivers, and VRAM."""
        raise NotImplementedError

    @abc.abstractmethod
    def probe_thermal_and_power(self) -> dict[str, Any]:
        """Query hardware thermal sensors and fan speeds."""
        raise NotImplementedError
