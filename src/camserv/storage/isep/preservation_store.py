"""
camserv.storage.isep.preservation_store
======================================

Transactional, durable SQLite-backed storage layer for ISEP evidence preservation.
Persists PreservationHold records, vault segment catalogs, and append-only retention
audit events across process restarts and unexpected system crashes.

Fail-Closed Invariant: If this database becomes unavailable or corrupted,
preservation queries FAIL-CLOSED (reporting all evidence as protected) to prevent
accidental data loss during maintenance cycles.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from camserv.storage.isep.models import (
    PreservationHold,
    RecordingSegmentMetadata,
)

logger = structlog.get_logger(__name__)

CURRENT_SCHEMA_VERSION = 1


class PreservationStoreError(Exception):
    """Base exception for preservation store errors."""


class PreservationStoreCorruptError(PreservationStoreError):
    """Raised when the preservation ledger database is corrupt."""


class PreservationStore:
    """
    Transactional SQLite persistence layer for evidence holds, vault metadata,
    and retention audit records.
    """

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a connection with timeout and WAL mode enabled."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            return conn
        except Exception:
            conn.close()
            raise

    def close(self) -> None:
        """Close any cached resources."""
        pass

    def _init_db(self) -> None:
        """Initialize database tables with schema versioning and integrity check."""
        with self._lock:
            conn = self._get_connection()
            try:
                # Fast integrity check
                cur = conn.execute("PRAGMA quick_check;")
                row = cur.fetchone()
                if not row or row[0].lower() != "ok":
                    raise PreservationStoreCorruptError(f"Preservation store corruption detected: {row}")

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS preservation_schema_info (
                        version INTEGER PRIMARY KEY,
                        migrated_at TEXT NOT NULL
                    );
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS preservation_holds (
                        hold_id TEXT PRIMARY KEY,
                        target_id TEXT NOT NULL,
                        target_type TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        authorized_by TEXT NOT NULL,
                        hold_type TEXT NOT NULL,
                        active INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        released_at TEXT,
                        released_by TEXT,
                        release_reason TEXT,
                        expires_at TEXT,
                        metadata_json TEXT
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_holds_target_active ON preservation_holds(target_id, active);")

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS vault_segments (
                        segment_id TEXT PRIMARY KEY,
                        camera_id TEXT NOT NULL,
                        file_path TEXT NOT NULL,
                        sha256_hash TEXT NOT NULL,
                        file_size_bytes INTEGER NOT NULL,
                        ingested_at TEXT NOT NULL,
                        hold_id TEXT NOT NULL,
                        metadata_json TEXT NOT NULL
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_vault_cam ON vault_segments(camera_id);")

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS retention_audit_ledger (
                        entry_id TEXT PRIMARY KEY,
                        segment_id TEXT NOT NULL,
                        sha256_hash TEXT NOT NULL,
                        camera_id TEXT NOT NULL,
                        file_path TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL,
                        retention_decision TEXT NOT NULL,
                        policy_rule TEXT NOT NULL,
                        policy_version TEXT NOT NULL,
                        operator_authorization TEXT NOT NULL,
                        timestamp_utc TEXT NOT NULL,
                        hold_verification_result TEXT NOT NULL,
                        deletion_outcome TEXT NOT NULL
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_retention_audit_time ON retention_audit_ledger(timestamp_utc);")

                # Record schema version
                cur = conn.execute("SELECT MAX(version) FROM preservation_schema_info;")
                v_row = cur.fetchone()
                if not v_row or v_row[0] is None:
                    conn.execute(
                        "INSERT INTO preservation_schema_info (version, migrated_at) VALUES (?, ?);",
                        (CURRENT_SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
                    )
                conn.commit()
            except sqlite3.DatabaseError as exc:
                conn.close()
                logger.error("isep.preservation_store.init_failed", error=str(exc))
                raise PreservationStoreCorruptError(f"Failed to initialize preservation store: {exc}") from exc
            finally:
                conn.close()

    def save_hold(self, hold: PreservationHold) -> None:
        """Durably insert or update a preservation hold record."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO preservation_holds (
                        hold_id, target_id, target_type, reason, authorized_by,
                        hold_type, active, created_at, expires_at, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(hold_id) DO UPDATE SET
                        active = excluded.active,
                        released_at = excluded.released_at,
                        released_by = excluded.released_by,
                        release_reason = excluded.release_reason,
                        expires_at = excluded.expires_at,
                        metadata_json = excluded.metadata_json;
                    """,
                    (
                        hold.hold_id,
                        hold.target_id,
                        hold.target_type,
                        hold.reason,
                        hold.authorized_by,
                        hold.hold_type,
                        1 if hold.active else 0,
                        hold.created_at,
                        hold.expires_at,
                        json.dumps(hold.to_dict()),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def release_hold(self, hold_id: str, released_by: str, reason: str) -> bool:
        """Durably release a hold with operator attribution and timestamp."""
        with self._lock:
            conn = self._get_connection()
            try:
                now_iso = datetime.now(timezone.utc).isoformat()
                cur = conn.execute(
                    """
                    UPDATE preservation_holds
                    SET active = 0, released_at = ?, released_by = ?, release_reason = ?
                    WHERE hold_id = ? AND active = 1;
                    """,
                    (now_iso, released_by, reason, hold_id),
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def load_active_holds(self) -> dict[str, PreservationHold]:
        """Load all active preservation holds into memory on startup."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.execute("SELECT * FROM preservation_holds WHERE active = 1;")
                holds = {}
                for row in cur.fetchall():
                    h = PreservationHold(
                        hold_id=row["hold_id"],
                        target_id=row["target_id"],
                        target_type=row["target_type"],
                        reason=row["reason"],
                        authorized_by=row["authorized_by"],
                        hold_type=row["hold_type"],
                        active=bool(row["active"]),
                        created_at=row["created_at"],
                        expires_at=row["expires_at"],
                    )
                    holds[h.hold_id] = h
                return holds
            finally:
                conn.close()

    def is_target_protected(self, target_id: str) -> bool:
        """
        Check if target has an active, unexpired preservation hold.
        FAIL-CLOSED: If database read fails, returns True to protect evidence.
        """
        try:
            with self._lock:
                conn = self._get_connection()
                try:
                    now_iso = datetime.now(timezone.utc).isoformat()
                    cur = conn.execute(
                        """
                        SELECT hold_id, expires_at FROM preservation_holds
                        WHERE target_id = ? AND active = 1;
                        """,
                        (target_id,),
                    )
                    rows = cur.fetchall()
                    for r in rows:
                        expires_at = r["expires_at"]
                        if expires_at is None or expires_at > now_iso:
                            return True
                    return False
                finally:
                    conn.close()
        except Exception as exc:
            logger.error("isep.preservation_store.fail_closed_triggered", target_id=target_id, error=str(exc))
            # Fail closed: treat as protected
            return True

    def save_vault_segment(self, segment: RecordingSegmentMetadata, hold_id: str) -> None:
        """Durably persist vault segment metadata."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO vault_segments (
                        segment_id, camera_id, file_path, sha256_hash,
                        file_size_bytes, ingested_at, hold_id, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(segment_id) DO UPDATE SET
                        file_path = excluded.file_path,
                        sha256_hash = excluded.sha256_hash,
                        file_size_bytes = excluded.file_size_bytes,
                        metadata_json = excluded.metadata_json;
                    """,
                    (
                        segment.segment_id,
                        segment.camera_id,
                        segment.file_path,
                        segment.sha256_hash,
                        segment.file_size_bytes,
                        datetime.now(timezone.utc).isoformat(),
                        hold_id,
                        json.dumps(segment.to_dict()),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def load_vault_segments(self) -> dict[str, RecordingSegmentMetadata]:
        """Load all vaulted segment metadata from database on startup."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.execute("SELECT metadata_json FROM vault_segments;")
                segments = {}
                for row in cur.fetchall():
                    try:
                        data = json.loads(row["metadata_json"])
                        meta = RecordingSegmentMetadata.from_dict(data)
                        segments[meta.segment_id] = meta
                    except Exception as err:
                        logger.warning("isep.vault_segment_deserialize_failed", error=str(err))
                return segments
            finally:
                conn.close()

    def record_retention_audit_entry(
        self,
        segment_id: str,
        sha256_hash: str,
        camera_id: str,
        file_path: str,
        size_bytes: int,
        retention_decision: str,
        policy_rule: str,
        policy_version: str,
        operator_authorization: str,
        hold_verification_result: str,
        deletion_outcome: str,
    ) -> str:
        """Append a durable retention decision event to the audit ledger."""
        entry_id = f"audit_ret_{segment_id}_{int(time.time()*1000)}"
        timestamp_utc = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO retention_audit_ledger (
                        entry_id, segment_id, sha256_hash, camera_id, file_path,
                        size_bytes, retention_decision, policy_rule, policy_version,
                        operator_authorization, timestamp_utc, hold_verification_result,
                        deletion_outcome
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        entry_id,
                        segment_id,
                        sha256_hash,
                        camera_id,
                        file_path,
                        size_bytes,
                        retention_decision,
                        policy_rule,
                        policy_version,
                        operator_authorization,
                        timestamp_utc,
                        hold_verification_result,
                        deletion_outcome,
                    ),
                )
                conn.commit()
                return entry_id
            finally:
                conn.close()

    def get_retention_audit_entries(self, limit: int = 100) -> list[dict[str, Any]]:
        """Retrieve recent retention audit records."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.execute(
                    "SELECT * FROM retention_audit_ledger ORDER BY timestamp_utc DESC LIMIT ?;",
                    (limit,),
                )
                return [dict(row) for row in cur.fetchall()]
            finally:
                conn.close()
