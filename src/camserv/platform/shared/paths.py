"""
camserv.platform.shared.paths
=============================

Unified cross-platform filesystem path resolution for CAMserv.
Resolves configuration, database, recording, vault, and log directories
according to the host operating system and execution context (appliance,
service, or development workspace).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class PlatformPaths:
    """Resolved system paths for the active platform."""

    config_dir: Path
    data_dir: Path
    db_path: Path
    recordings_dir: Path
    vault_dir: Path
    exports_dir: Path
    models_dir: Path
    log_dir: Path
    cache_dir: Path
    is_system_install: bool


class PathResolver:
    """Cross-platform path resolution engine."""

    @classmethod
    def resolve_paths(cls, force_system: bool | None = None) -> PlatformPaths:
        """
        Determine platform-appropriate paths based on OS and environment.
        
        Resolution Strategy:
        1. If CAMSERV_DATA_DIR / CAMSERV_CONFIG_DIR env vars exist, use them.
        2. If force_system is True or running in rootfs / installed service mode:
           - Linux: /etc/camserv, /var/lib/camserv, /var/log/camserv
           - Windows: %ProgramData%\\CAMserv\\config, %ProgramData%\\CAMserv\\data, etc.
        3. Otherwise fallback to local workspace directories (./data, ./logs, ./config).
        """
        env_config = os.environ.get("CAMSERV_CONFIG_DIR")
        env_data = os.environ.get("CAMSERV_DATA_DIR")
        env_log = os.environ.get("CAMSERV_LOG_DIR")

        is_windows = sys.platform.startswith("win")
        
        # Check if running as a system-level installation
        is_system = force_system
        if is_system is None:
            if is_windows:
                # Windows system mode: ProgramData directory exists or running as NT SERVICE / SYSTEM
                prog_data = Path(os.environ.get("ProgramData", "C:\\ProgramData")) / "CAMserv"
                is_system = prog_data.exists() or os.environ.get("CAMSERV_SYSTEM_SERVICE") == "1"
            else:
                # Linux system mode: /var/lib/camserv exists or running as root
                is_system = Path("/var/lib/camserv").exists() or (os.name == "posix" and os.getuid() == 0)

        if is_system:
            if is_windows:
                base_data = Path(os.environ.get("ProgramData", "C:\\ProgramData")) / "CAMserv"
                config_dir = Path(env_config) if env_config else base_data / "config"
                data_dir = Path(env_data) if env_data else base_data / "data"
                log_dir = Path(env_log) if env_log else base_data / "logs"
                cache_dir = base_data / "cache"
            else:
                config_dir = Path(env_config) if env_config else Path("/etc/camserv")
                data_dir = Path(env_data) if env_data else Path("/var/lib/camserv")
                log_dir = Path(env_log) if env_log else Path("/var/log/camserv")
                cache_dir = Path("/var/cache/camserv")
        else:
            # Local workspace development paths
            base_local = Path.cwd()
            config_dir = Path(env_config) if env_config else base_local / "config"
            data_dir = Path(env_data) if env_data else base_local / "data"
            log_dir = Path(env_log) if env_log else base_local / "logs"
            cache_dir = data_dir / "cache"

        return PlatformPaths(
            config_dir=config_dir,
            data_dir=data_dir,
            db_path=data_dir / "db" / "camserv.db",
            recordings_dir=data_dir / "recordings",
            vault_dir=data_dir / "vault",
            exports_dir=data_dir / "exports",
            models_dir=data_dir / "models",
            log_dir=log_dir,
            cache_dir=cache_dir,
            is_system_install=bool(is_system),
        )
