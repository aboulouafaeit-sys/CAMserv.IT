"""
camserv.storage.init_service
============================

Appliance Storage Pre-Flight Initialization, Directory Setup & Migration Runner.
Executed by camserv-storage.service (Type=oneshot) during appliance startup.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import structlog

from camserv.storage.migrations import MigrationManager
from camserv.storage.sqlite_store import SQLiteStore

logger = structlog.get_logger(__name__)

STANDARD_APPLIANCE_DIRS = [
    Path("/var/lib/camserv/db"),
    Path("/var/lib/camserv/recordings"),
    Path("/var/lib/camserv/vault"),
    Path("/var/lib/camserv/exports"),
    Path("/var/lib/camserv/models"),
    Path("/var/log/camserv"),
    Path("/var/cache/camserv"),
    Path("/etc/camserv"),
]

FALLBACK_LOCAL_DIRS = [
    Path("data/db"),
    Path("data/recordings"),
    Path("data/vault"),
    Path("data/exports"),
    Path("data/models"),
    Path("logs"),
]


def initialize_appliance_storage(use_system_paths: bool | None = None) -> int:
    """Ensure all storage directories exist with appropriate permissions and run SQLite schema migrations."""
    # Determine directory layout: check if /var/lib/camserv or running in local dev
    if use_system_paths is None:
        use_system_paths = Path("/var/lib/camserv").exists() or os.name == "posix" and os.getuid() == 0

    target_dirs = STANDARD_APPLIANCE_DIRS if use_system_paths else FALLBACK_LOCAL_DIRS

    logger.info("storage.init_service.starting", use_system_paths=use_system_paths)

    for d in target_dirs:
        try:
            d.mkdir(parents=True, exist_ok=True)
            # Apply secure permissions on POSIX
            if os.name == "posix":
                if "vault" in str(d) or "etc" in str(d):
                    os.chmod(d, 0o700)
                else:
                    os.chmod(d, 0o750)
            logger.debug("storage.directory_verified", path=str(d))
        except Exception as e:
            logger.warning("storage.directory_create_failed", path=str(d), error=str(e))

    # Initialize SQLite store and run schema migrations
    db_path = (
        Path("/var/lib/camserv/db/camserv.db")
        if use_system_paths
        else Path("data/db/camserv.db")
    )
    db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        store = SQLiteStore(db_path=db_path)
        logger.info("storage.sqlite_initialized", path=str(db_path))

        # Run migration manager
        mgr = MigrationManager(db_path=db_path)
        applied = mgr.migrate()
        logger.info("storage.migrations_applied", count=len(applied))
    except Exception as e:
        logger.error("storage.sqlite_init_failed", error=str(e))
        return 1

    logger.info("storage.init_service.complete", status="READY")
    return 0


def main() -> None:
    code = initialize_appliance_storage()
    sys.exit(code)


if __name__ == "__main__":
    main()
