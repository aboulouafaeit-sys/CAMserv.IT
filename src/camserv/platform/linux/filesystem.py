"""
camserv.platform.linux.filesystem
=================================

Linux FHS filesystem layout and POSIX DAC security enforcer.
Ensures appropriate owner:group permissions (0750/0600) on directories and files.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import structlog

from camserv.platform.shared.interfaces import PlatformFilesystem
from camserv.platform.shared.paths import PathResolver

logger = structlog.get_logger(__name__)


class LinuxFilesystem(PlatformFilesystem):
    """Filesystem layout and POSIX permission manager for Debian Linux appliances."""

    def __init__(self, force_system: bool | None = None) -> None:
        self.paths = PathResolver.resolve_paths(force_system=force_system)

    def get_config_dir(self) -> Path:
        return self.paths.config_dir

    def get_data_dir(self) -> Path:
        return self.paths.data_dir

    def get_recordings_dir(self) -> Path:
        return self.paths.recordings_dir

    def get_vault_dir(self) -> Path:
        return self.paths.vault_dir

    def get_log_dir(self) -> Path:
        return self.paths.log_dir

    def get_cache_dir(self) -> Path:
        return self.paths.cache_dir

    def secure_directory(self, path: Path, is_sensitive: bool = False) -> bool:
        """Apply 0700 (sensitive) or 0750 (standard) POSIX permissions."""
        if os.name != "posix":
            return True
        mode = stat.S_IRWXU if is_sensitive else (stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP)
        try:
            os.chmod(path, mode)
            return True
        except OSError as exc:
            logger.warning("linux.fs.chmod_dir_failed", path=str(path), error=str(exc))
            return False

    def secure_file(self, path: Path, is_secret: bool = False) -> bool:
        """Apply 0600 (secret) or 0640 (standard) POSIX permissions."""
        if os.name != "posix":
            return True
        mode = (stat.S_IRUSR | stat.S_IWUSR) if is_secret else (stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)
        try:
            os.chmod(path, mode)
            return True
        except OSError as exc:
            logger.warning("linux.fs.chmod_file_failed", path=str(path), error=str(exc))
            return False

    def initialize_filesystem(self) -> bool:
        """Ensure all required Linux appliance directories exist and are secured."""
        dirs = [
            (self.paths.config_dir, True),
            (self.paths.data_dir, False),
            (self.paths.data_dir / "db", False),
            (self.paths.recordings_dir, False),
            (self.paths.vault_dir, True),
            (self.paths.exports_dir, False),
            (self.paths.models_dir, False),
            (self.paths.log_dir, False),
            (self.paths.cache_dir, False),
        ]

        success = True
        for d, sensitive in dirs:
            try:
                d.mkdir(parents=True, exist_ok=True)
                self.secure_directory(d, is_sensitive=sensitive)
            except Exception as exc:
                logger.error("linux.fs.init_failed", path=str(d), error=str(exc))
                success = False
        return success
