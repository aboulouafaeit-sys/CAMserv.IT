"""
camserv.storage.migrations
==========================

Lightweight, transactional, zero-dependency schema migration framework for CAMserv SQLite databases.
Supports sequential forward migrations, atomic transactions, automatic rollback on error,
and cryptographic checksum tracking.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import structlog

logger = structlog.get_logger(__name__)


class MigrationError(RuntimeError):
    """Raised when a database migration fails or cannot be rolled back."""


@dataclass(slots=True)
class Migration:
    """Individual database migration step with forward and rollback SQL definitions."""

    version: int
    name: str
    up_sql: str
    down_sql: str = ""

    def checksum(self) -> str:
        """Compute SHA-256 checksum of the up_sql definition to detect tampering."""
        return hashlib.sha256(self.up_sql.strip().encode("utf-8")).hexdigest()


class MigrationManager:
    """
    Manages versioning and transactional execution of database schema migrations.
    """

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.migrations: list[Migration] = []
        self._ensure_migrations_table()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a connection with WAL mode and foreign keys enabled."""
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _ensure_migrations_table(self) -> None:
        """Ensure tracking table schema_migrations exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at REAL NOT NULL,
                    checksum TEXT NOT NULL
                );
                """
            )
            conn.commit()

    def register_migration(self, migration: Migration) -> None:
        """Register a migration in the sequence."""
        self.migrations.append(migration)
        # Keep migrations strictly sorted by version
        self.migrations.sort(key=lambda m: m.version)

    def get_applied_versions(self) -> dict[int, str]:
        """Return dict of {version: checksum} for applied migrations."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT version, checksum FROM schema_migrations ORDER BY version ASC;")
            return {row[0]: row[1] for row in cur.fetchall()}

    def get_current_version(self) -> int:
        """Return highest applied version, or 0 if none applied."""
        applied = self.get_applied_versions()
        return max(applied.keys()) if applied else 0

    def migrate(self, target_version: int | None = None) -> list[int]:
        """
        Execute pending forward migrations up to target_version (or all if None).
        Returns list of executed migration versions.
        """
        applied = self.get_applied_versions()
        executed: list[int] = []

        conn = self._get_connection()
        try:
            for mig in self.migrations:
                if target_version is not None and mig.version > target_version:
                    break

                if mig.version in applied:
                    # Verify checksum integrity
                    if applied[mig.version] != mig.checksum():
                        raise MigrationError(
                            f"Migration {mig.version} ({mig.name}) was modified after being applied! "
                            f"Recorded checksum: {applied[mig.version]}, Current: {mig.checksum()}"
                        )
                    continue

                # Execute migration inside an atomic transaction
                logger.info("migration.applying", version=mig.version, name=mig.name)
                cursor = conn.cursor()
                cursor.execute("BEGIN TRANSACTION;")
                try:
                    cursor.executescript(mig.up_sql)
                    cursor.execute(
                        "INSERT INTO schema_migrations (version, name, applied_at, checksum) VALUES (?, ?, ?, ?);",
                        (mig.version, mig.name, time.time(), mig.checksum()),
                    )
                    conn.commit()
                    executed.append(mig.version)
                    logger.info("migration.success", version=mig.version, name=mig.name)
                except Exception as e:
                    conn.rollback()
                    logger.critical("migration.failed_rolled_back", version=mig.version, error=str(e))
                    raise MigrationError(f"Migration {mig.version} ({mig.name}) failed: {e}") from e

        finally:
            conn.close()

        return executed

    def rollback(self, target_version: int) -> list[int]:
        """
        Rollback applied migrations down to target_version.
        Returns list of rolled-back versions.
        """
        applied = self.get_applied_versions()
        rolled_back: list[int] = []

        # Find migrations to revert in reverse order
        to_revert = [m for m in reversed(self.migrations) if m.version in applied and m.version > target_version]

        conn = self._get_connection()
        try:
            for mig in to_revert:
                if not mig.down_sql:
                    raise MigrationError(f"Cannot rollback migration {mig.version} ({mig.name}): No down_sql defined.")

                logger.warning("migration.rolling_back", version=mig.version, name=mig.name)
                cursor = conn.cursor()
                cursor.execute("BEGIN TRANSACTION;")
                try:
                    cursor.executescript(mig.down_sql)
                    cursor.execute("DELETE FROM schema_migrations WHERE version = ?;", (mig.version,))
                    conn.commit()
                    rolled_back.append(mig.version)
                    logger.info("migration.rollback_success", version=mig.version, name=mig.name)
                except Exception as e:
                    conn.rollback()
                    logger.critical("migration.rollback_failed", version=mig.version, error=str(e))
                    raise MigrationError(f"Rollback of migration {mig.version} failed: {e}") from e
        finally:
            conn.close()

        return rolled_back
