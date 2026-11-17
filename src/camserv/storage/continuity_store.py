"""
camserv.storage.continuity_store
================================

Durable, transactional SQLite-backed persistence store for RecordingContinuityLedger
and DiscontinuityEvent records.

Durability Invariants:
1. All segment continuity states and discontinuity events are persisted with SQLite WAL mode
   (Write-Ahead Logging) and PRAGMA synchronous=NORMAL to survive power outages, kernel panics,
   and abrupt process crashes.
2. Unclean shutdown recovery: On application startup, any unfinalized segments are detected,
   transitioned to RECORDING_INTERRUPTED, and assigned explicit crash-recovery discontinuity events.
3. Separation of recording path from persistence: Database commits are bounded and isolated;
   database lock contention or storage full conditions degrade persistence state explicitly
   (is_persistence_degraded=True) without deadlocking the video frame ingestion pipeline.
4. Idempotency: All events use unique deterministic or UUID keys with INSERT OR IGNORE semantics;
   segments use UPSERT (ON CONFLICT DO UPDATE) to prevent duplicate sequence inflation.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from camserv.platform.stability import (
    DiscontinuityEvent,
    RecordingContinuityRecord,
    RecordingContinuityState,
)

logger = structlog.get_logger(__name__)

CURRENT_CONTINUITY_SCHEMA_VERSION = 1


class ContinuityStoreError(Exception):
    """Base exception for durable continuity store errors."""
    pass


class ContinuityStoreCorruptError(ContinuityStoreError):
    """Raised when the continuity database is corrupt."""
    pass


class DurableContinuityStore:
    """
    Transactional SQLite persistence layer for surveillance stream continuity records
    and forensic gap event telemetry.
    """

    def __init__(self, db_path: Path | str, timeout_sec: float = 5.0) -> None:
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.timeout_sec = timeout_sec
        self._lock = threading.RLock()
        self.is_degraded = False
        self.last_error: str | None = None
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a connection with timeout and WAL mode enabled."""
        conn = sqlite3.connect(str(self.db_path), timeout=self.timeout_sec)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        """Initialize database schema with idempotent tables and indexes."""
        with self._lock:
            try:
                conn = self._get_connection()
                try:
                    with conn:
                        conn.execute(
                            """
                            CREATE TABLE IF NOT EXISTS schema_version (
                                version INTEGER PRIMARY KEY,
                                updated_at_utc TEXT NOT NULL
                            );
                            """
                        )
                        conn.execute(
                            """
                            CREATE TABLE IF NOT EXISTS continuity_segments (
                                segment_id TEXT PRIMARY KEY,
                                camera_id TEXT NOT NULL,
                                stream_id TEXT NOT NULL,
                                start_timestamp_utc TEXT NOT NULL,
                                end_timestamp_utc TEXT,
                                expected_frames INTEGER DEFAULT 0,
                                observed_frames INTEGER DEFAULT 0,
                                current_state TEXT NOT NULL,
                                confirmed_missing_frames_total INTEGER DEFAULT 0,
                                estimated_missing_frames_total INTEGER DEFAULT 0,
                                unknown_frame_loss_events INTEGER DEFAULT 0,
                                reconnect_events INTEGER DEFAULT 0,
                                storage_write_errors INTEGER DEFAULT 0,
                                last_frame_seq INTEGER,
                                last_frame_pts REAL,
                                is_finalized INTEGER DEFAULT 0,
                                integrity_verified INTEGER DEFAULT 0,
                                created_at_utc TEXT NOT NULL,
                                updated_at_utc TEXT NOT NULL
                            );
                            """
                        )
                        conn.execute(
                            """
                            CREATE TABLE IF NOT EXISTS continuity_events (
                                event_id TEXT PRIMARY KEY,
                                camera_id TEXT NOT NULL,
                                stream_id TEXT NOT NULL,
                                segment_id TEXT,
                                gap_start_utc TEXT NOT NULL,
                                gap_end_utc TEXT NOT NULL,
                                gap_duration_sec REAL NOT NULL,
                                lost_frames_estimated INTEGER DEFAULT 0,
                                confirmed_missing_frames INTEGER,
                                estimated_missing_frames INTEGER,
                                unknown_frame_loss INTEGER DEFAULT 0,
                                estimation_method TEXT NOT NULL,
                                confidence TEXT NOT NULL,
                                reason TEXT NOT NULL,
                                recovery_status TEXT NOT NULL,
                                last_confirmed_pts REAL,
                                first_subsequent_pts REAL,
                                last_confirmed_seq INTEGER,
                                subsequent_seq INTEGER,
                                source_metadata_json TEXT,
                                detected_at_utc TEXT NOT NULL,
                                FOREIGN KEY (segment_id) REFERENCES continuity_segments(segment_id) ON DELETE SET NULL
                            );
                            """
                        )
                        conn.execute(
                            "CREATE INDEX IF NOT EXISTS idx_continuity_events_camera ON continuity_events(camera_id, detected_at_utc);"
                        )
                        conn.execute(
                            "CREATE INDEX IF NOT EXISTS idx_continuity_events_segment ON continuity_events(segment_id);"
                        )
                        conn.execute(
                            "CREATE INDEX IF NOT EXISTS idx_continuity_segments_camera ON continuity_segments(camera_id, start_timestamp_utc);"
                        )
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO schema_version (version, updated_at_utc)
                            VALUES (?, ?);
                            """,
                            (CURRENT_CONTINUITY_SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
                        )
                    self.is_degraded = False
                    self.last_error = None
                finally:
                    conn.close()
            except sqlite3.DatabaseError as exc:
                self.is_degraded = True
                self.last_error = f"Database initialization error: {exc}"
                logger.error("continuity_store.init_failed", error=str(exc))
                raise ContinuityStoreCorruptError(f"Continuity database corrupted: {exc}") from exc

    def save_segment(self, record: RecordingContinuityRecord) -> bool:
        """
        Idempotently persist or update a RecordingContinuityRecord using SQLite transactions.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            try:
                conn = self._get_connection()
                try:
                    with conn:
                        conn.execute(
                            """
                            INSERT INTO continuity_segments (
                                segment_id, camera_id, stream_id, start_timestamp_utc,
                                end_timestamp_utc, expected_frames, observed_frames,
                                current_state, confirmed_missing_frames_total,
                                estimated_missing_frames_total, unknown_frame_loss_events,
                                reconnect_events, storage_write_errors, last_frame_seq,
                                last_frame_pts, is_finalized, integrity_verified,
                                created_at_utc, updated_at_utc
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(segment_id) DO UPDATE SET
                                end_timestamp_utc=excluded.end_timestamp_utc,
                                expected_frames=excluded.expected_frames,
                                observed_frames=excluded.observed_frames,
                                current_state=excluded.current_state,
                                confirmed_missing_frames_total=excluded.confirmed_missing_frames_total,
                                estimated_missing_frames_total=excluded.estimated_missing_frames_total,
                                unknown_frame_loss_events=excluded.unknown_frame_loss_events,
                                reconnect_events=excluded.reconnect_events,
                                storage_write_errors=excluded.storage_write_errors,
                                last_frame_seq=excluded.last_frame_seq,
                                last_frame_pts=excluded.last_frame_pts,
                                is_finalized=excluded.is_finalized,
                                integrity_verified=excluded.integrity_verified,
                                updated_at_utc=excluded.updated_at_utc;
                            """,
                            (
                                record.segment_id,
                                record.camera_id,
                                record.stream_id,
                                record.start_timestamp_utc,
                                record.end_timestamp_utc,
                                record.expected_frames,
                                record.observed_frames,
                                record.current_state.value,
                                record.confirmed_missing_frames_total,
                                record.estimated_missing_frames_total,
                                record.unknown_frame_loss_events,
                                record.reconnect_events,
                                record.storage_write_errors,
                                record.last_frame_seq,
                                record.last_frame_pts,
                                1 if record.is_finalized else 0,
                                1 if record.integrity_verified else 0,
                                record.start_timestamp_utc,
                                now_iso,
                            ),
                        )
                    self.is_degraded = False
                    self.last_error = None
                    return True
                finally:
                    conn.close()
            except sqlite3.Error as exc:
                self.is_degraded = True
                self.last_error = f"save_segment failed: {exc}"
                logger.critical("continuity_store.save_segment_failed", segment=record.segment_id, error=str(exc))
                return False

    def save_discontinuity_event(self, event: DiscontinuityEvent, event_id: str | None = None) -> bool:
        """
        Durably persist a DiscontinuityEvent record.
        """
        eid = event_id or f"disc_{event.camera_id}_{uuid.uuid4().hex[:12]}"
        meta_json = json.dumps(event.source_metadata) if event.source_metadata else "{}"
        with self._lock:
            try:
                conn = self._get_connection()
                try:
                    with conn:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO continuity_events (
                                event_id, camera_id, stream_id, segment_id,
                                gap_start_utc, gap_end_utc, gap_duration_sec,
                                lost_frames_estimated, confirmed_missing_frames,
                                estimated_missing_frames, unknown_frame_loss,
                                estimation_method, confidence, reason,
                                recovery_status, last_confirmed_pts, first_subsequent_pts,
                                last_confirmed_seq, subsequent_seq, source_metadata_json,
                                detected_at_utc
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                            """,
                            (
                                eid,
                                event.camera_id,
                                event.stream_id,
                                event.segment_id,
                                event.gap_start_utc,
                                event.gap_end_utc,
                                event.gap_duration_sec,
                                event.lost_frames_estimated,
                                event.confirmed_missing_frames,
                                event.estimated_missing_frames,
                                1 if event.unknown_frame_loss else 0,
                                event.estimation_method,
                                event.confidence,
                                event.reason,
                                event.recovery_status,
                                event.last_confirmed_pts,
                                event.first_subsequent_pts,
                                event.last_confirmed_seq,
                                event.subsequent_seq,
                                meta_json,
                                event.detected_at_utc,
                            ),
                        )
                    self.is_degraded = False
                    self.last_error = None
                    return True
                finally:
                    conn.close()
            except sqlite3.Error as exc:
                self.is_degraded = True
                self.last_error = f"save_discontinuity_event failed: {exc}"
                logger.critical("continuity_store.save_event_failed", camera=event.camera_id, error=str(exc))
                return False

    def load_segment(self, camera_id: str, segment_id: str) -> RecordingContinuityRecord | None:
        """
        Load a specific segment record and its associated discontinuity events from SQLite.
        """
        with self._lock:
            try:
                conn = self._get_connection()
                try:
                    cursor = conn.execute(
                        "SELECT * FROM continuity_segments WHERE camera_id = ? AND segment_id = ?;",
                        (camera_id, segment_id),
                    )
                    row = cursor.fetchone()
                    if not row:
                        return None

                    # Load discontinuities for this segment
                    ev_cursor = conn.execute(
                        "SELECT * FROM continuity_events WHERE segment_id = ? ORDER BY detected_at_utc ASC;",
                        (segment_id,),
                    )
                    events: list[DiscontinuityEvent] = []
                    for erow in ev_cursor.fetchall():
                        meta = json.loads(erow["source_metadata_json"]) if erow["source_metadata_json"] else {}
                        events.append(
                            DiscontinuityEvent(
                                camera_id=erow["camera_id"],
                                stream_id=erow["stream_id"],
                                segment_id=erow["segment_id"],
                                gap_start_utc=erow["gap_start_utc"],
                                gap_end_utc=erow["gap_end_utc"],
                                gap_duration_sec=erow["gap_duration_sec"],
                                lost_frames_estimated=erow["lost_frames_estimated"],
                                reason=erow["reason"],
                                detected_at_utc=erow["detected_at_utc"],
                                confirmed_missing_frames=erow["confirmed_missing_frames"],
                                estimated_missing_frames=erow["estimated_missing_frames"],
                                unknown_frame_loss=bool(erow["unknown_frame_loss"]),
                                estimation_method=erow["estimation_method"],
                                confidence=erow["confidence"],
                                source_metadata=meta,
                                recovery_status=erow["recovery_status"],
                                first_subsequent_pts=erow["first_subsequent_pts"],
                                last_confirmed_pts=erow["last_confirmed_pts"],
                                last_confirmed_seq=erow["last_confirmed_seq"],
                                subsequent_seq=erow["subsequent_seq"],
                            )
                        )

                    state_str = row["current_state"]
                    try:
                        state = RecordingContinuityState(state_str)
                    except ValueError:
                        state = RecordingContinuityState.CONTINUOUS

                    rec = RecordingContinuityRecord(
                        camera_id=row["camera_id"],
                        stream_id=row["stream_id"],
                        segment_id=row["segment_id"],
                        start_timestamp_utc=row["start_timestamp_utc"],
                        end_timestamp_utc=row["end_timestamp_utc"],
                        expected_frames=row["expected_frames"],
                        observed_frames=row["observed_frames"],
                        discontinuities=events,
                        reconnect_events=row["reconnect_events"],
                        storage_write_errors=row["storage_write_errors"],
                        is_finalized=bool(row["is_finalized"]),
                        integrity_verified=bool(row["integrity_verified"]),
                        current_state=state,
                        confirmed_missing_frames_total=row["confirmed_missing_frames_total"],
                        estimated_missing_frames_total=row["estimated_missing_frames_total"],
                        unknown_frame_loss_events=row["unknown_frame_loss_events"],
                        last_frame_seq=row["last_frame_seq"],
                        last_frame_pts=row["last_frame_pts"],
                    )
                    return rec
                finally:
                    conn.close()
            except sqlite3.Error as exc:
                logger.error("continuity_store.load_segment_failed", error=str(exc))
                return None

    def load_unfinalized_segments(self) -> list[RecordingContinuityRecord]:
        """
        Load all in-flight segments that were never cleanly finalized (e.g. prior to crash).
        """
        with self._lock:
            try:
                conn = self._get_connection()
                try:
                    cursor = conn.execute("SELECT camera_id, segment_id FROM continuity_segments WHERE is_finalized = 0;")
                    pairs = cursor.fetchall()
                finally:
                    conn.close()

                segments: list[RecordingContinuityRecord] = []
                for p in pairs:
                    seg = self.load_segment(p["camera_id"], p["segment_id"])
                    if seg:
                        segments.append(seg)
                return segments
            except sqlite3.Error as exc:
                logger.error("continuity_store.load_unfinalized_failed", error=str(exc))
                return []

    def recover_unclean_shutdown(self) -> list[RecordingContinuityRecord]:
        """
        Detects unfinalized segments from before restart, marks them RECORDING_INTERRUPTED,
        records a crash recovery discontinuity event, and saves them to SQLite.
        Guarantees that a crash never leaves a false CONTINUOUS recording claim.
        """
        unfinalized = self.load_unfinalized_segments()
        recovered: list[RecordingContinuityRecord] = []
        now_iso = datetime.now(timezone.utc).isoformat()

        for rec in unfinalized:
            rec.current_state = RecordingContinuityState.RECORDING_INTERRUPTED
            rec.end_timestamp_utc = now_iso
            rec.is_finalized = True

            crash_event = DiscontinuityEvent(
                camera_id=rec.camera_id,
                stream_id=rec.stream_id,
                segment_id=rec.segment_id,
                gap_start_utc=rec.start_timestamp_utc,
                gap_end_utc=now_iso,
                gap_duration_sec=0.0,
                lost_frames_estimated=0,
                confirmed_missing_frames=None,
                estimated_missing_frames=None,
                unknown_frame_loss=True,
                estimation_method="unclean_shutdown_recovery",
                confidence="unknown",
                reason="PROCESS_ABRUPT_TERMINATION_OR_POWER_CUT",
                recovery_status="interrupted",
            )
            rec.discontinuities.append(crash_event)
            rec.unknown_frame_loss_events += 1

            self.save_discontinuity_event(crash_event)
            self.save_segment(rec)
            recovered.append(rec)
            logger.warning(
                "continuity_store.unclean_shutdown_recovered",
                camera_id=rec.camera_id,
                segment_id=rec.segment_id,
                observed_frames=rec.observed_frames,
            )

        return recovered

