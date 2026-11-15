"""
camserv.storage.sqlite_store
============================

Durable, transactional relational persistence for CAMserv using SQLite with
Write-Ahead Logging (WAL) enabled for high-concurrency read/write operations.
Persists cameras, users, event histories, and system configuration across service restarts.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from camserv.pipeline.interfaces import AlertStatus, Event, EventSeverity
from camserv.security.auth import Role

logger = structlog.get_logger(__name__)


class SQLiteStore:
    """Relational storage manager for durable CAMserv platform metadata."""

    def __init__(self, db_path: Path | str = "data/camserv.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create and configure a SQLite connection with WAL mode."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        """Initialize database schema tables if not present."""
        with self._get_connection() as conn:
            # Cameras table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cameras (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    fps INTEGER NOT NULL DEFAULT 15,
                    width INTEGER NOT NULL DEFAULT 1920,
                    height INTEGER NOT NULL DEFAULT 1080,
                    privacy_zones TEXT DEFAULT '[]',
                    onvif_profile TEXT DEFAULT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

            # Users table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_login TEXT DEFAULT NULL
                );
                """
            )

            # Events table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    camera_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    requires_verification INTEGER NOT NULL,
                    verification_status TEXT NOT NULL DEFAULT 'pending',
                    verified_by TEXT DEFAULT NULL,
                    description TEXT NOT NULL,
                    supporting_observations TEXT DEFAULT '[]',
                    reasoning_trace TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    metadata TEXT DEFAULT '{}'
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_camera_time ON events (camera_id, timestamp);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_severity ON events (severity);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_status ON events (verification_status);")

            # Privacy Evidence Manifests table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS privacy_manifests (
                    manifest_id TEXT PRIMARY KEY,
                    camera_id TEXT NOT NULL,
                    frame_id INTEGER NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    original_sha256 TEXT NOT NULL,
                    derivative_sha256 TEXT NOT NULL,
                    masking_method TEXT NOT NULL,
                    masked_regions_count INTEGER NOT NULL,
                    privacy_state TEXT NOT NULL,
                    fail_closed_active INTEGER NOT NULL,
                    is_original_preserved INTEGER NOT NULL DEFAULT 1,
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_priv_manifest_camera_time ON privacy_manifests (camera_id, timestamp_utc);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_priv_manifest_orig_hash ON privacy_manifests (original_sha256);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_priv_manifest_deriv_hash ON privacy_manifests (derivative_sha256);")

            # Enhancement Evidence Manifests table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS enhancement_manifests (
                    manifest_id TEXT PRIMARY KEY,
                    camera_id TEXT NOT NULL,
                    frame_id INTEGER NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    original_sha256 TEXT NOT NULL,
                    enhanced_sha256 TEXT NOT NULL,
                    applied_methods TEXT NOT NULL,
                    parameters TEXT NOT NULL,
                    contrast_before REAL NOT NULL,
                    contrast_after REAL NOT NULL,
                    contrast_gain REAL NOT NULL,
                    is_original_preserved INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_enh_manifest_camera_time ON enhancement_manifests (camera_id, timestamp_utc);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_enh_manifest_orig_hash ON enhancement_manifests (original_sha256);")

            # -------------------------------------------------------------------
            # NVR Subsystem Tables
            # -------------------------------------------------------------------
            # Recordings table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recordings (
                    recording_id TEXT PRIMARY KEY,
                    camera_id TEXT NOT NULL,
                    start_time_utc TEXT NOT NULL,
                    end_time_utc TEXT,
                    recording_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    storage_tier TEXT NOT NULL,
                    total_size_bytes INTEGER DEFAULT 0,
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_recordings_camera_time ON recordings (camera_id, start_time_utc);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_recordings_status ON recordings (status);")

            # Recording Segments table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recording_segments (
                    segment_id TEXT PRIMARY KEY,
                    recording_id TEXT NOT NULL,
                    camera_id TEXT NOT NULL,
                    segment_index INTEGER NOT NULL,
                    start_time_utc TEXT NOT NULL,
                    end_time_utc TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    file_path TEXT NOT NULL,
                    file_size_bytes INTEGER NOT NULL,
                    sha256_hash TEXT NOT NULL,
                    has_motion INTEGER DEFAULT 0,
                    has_event INTEGER DEFAULT 0,
                    event_ids TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(recording_id) REFERENCES recordings(recording_id) ON DELETE CASCADE
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_segments_recording ON recording_segments (recording_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_segments_camera_time ON recording_segments (camera_id, start_time_utc);")

            # Recording Schedules table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recording_schedules (
                    schedule_id TEXT PRIMARY KEY,
                    camera_id TEXT NOT NULL,
                    day_of_week INTEGER NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_schedules_camera ON recording_schedules (camera_id);")

            # PTZ Presets table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ptz_presets (
                    preset_id TEXT PRIMARY KEY,
                    camera_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    pan REAL NOT NULL,
                    tilt REAL NOT NULL,
                    zoom REAL NOT NULL,
                    token TEXT DEFAULT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ptz_camera ON ptz_presets (camera_id);")

            # Camera Groups table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS camera_groups (
                    group_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    camera_ids TEXT DEFAULT '[]',
                    site_id TEXT DEFAULT 'default',
                    tags TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_groups_site ON camera_groups (site_id);")

            conn.commit()
        logger.info("sqlite.initialized", path=str(self.db_path))

    # ---------------------------------------------------------------------------
    # Camera CRUD
    # ---------------------------------------------------------------------------

    def upsert_camera(self, camera: dict[str, Any]) -> None:
        """Insert or update a camera configuration."""
        now = datetime.now(timezone.utc).isoformat()
        pz_json = json.dumps(camera.get("privacy_zones", []))
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO cameras (id, name, url, enabled, fps, width, height, privacy_zones, onvif_profile, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    url=excluded.url,
                    enabled=excluded.enabled,
                    fps=excluded.fps,
                    width=excluded.width,
                    height=excluded.height,
                    privacy_zones=excluded.privacy_zones,
                    onvif_profile=excluded.onvif_profile,
                    updated_at=excluded.updated_at;
                """,
                (
                    camera["id"],
                    camera["name"],
                    camera["url"],
                    1 if camera.get("enabled", True) else 0,
                    camera.get("fps", 15),
                    camera.get("width", 1920),
                    camera.get("height", 1080),
                    pz_json,
                    camera.get("onvif_profile"),
                    camera.get("created_at", now),
                    now,
                ),
            )
            conn.commit()

    def get_camera(self, camera_id: str) -> dict[str, Any] | None:
        """Retrieve a camera configuration by ID."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM cameras WHERE id = ?", (camera_id,)).fetchone()
            if not row:
                return None
            res = dict(row)
            res["enabled"] = bool(res["enabled"])
            res["privacy_zones"] = json.loads(res["privacy_zones"]) if res.get("privacy_zones") else []
            return res

    def list_cameras(self) -> list[dict[str, Any]]:
        """List all registered cameras."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM cameras ORDER BY id ASC").fetchall()
            results = []
            for r in rows:
                c = dict(r)
                c["enabled"] = bool(c["enabled"])
                c["privacy_zones"] = json.loads(c["privacy_zones"]) if c.get("privacy_zones") else []
                results.append(c)
            return results

    def delete_camera(self, camera_id: str) -> bool:
        """Delete a camera from the database."""
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))
            conn.commit()
            return cur.rowcount > 0

    # ---------------------------------------------------------------------------
    # Event Persistence & Human-in-the-Loop Review
    # ---------------------------------------------------------------------------

    def store_event(self, event: Event) -> None:
        """Persist a security event record."""
        ts_str = event.timestamp.isoformat() if hasattr(event.timestamp, "isoformat") else str(event.timestamp)
        obs_json = json.dumps(event.metadata.get("supporting_observations", []))
        reasoning = str(event.metadata.get("reasoning_trace", ""))
        meta_json = json.dumps({k: v for k, v in event.metadata.items() if k not in ("supporting_observations", "reasoning_trace")})
        severity_val = event.severity.value if hasattr(event.severity, "value") else str(event.severity)

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO events (
                    event_id, event_type, severity, confidence, camera_id, timestamp,
                    requires_verification, verification_status, description,
                    supporting_observations, reasoning_trace, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type,
                    severity_val,
                    float(event.confidence),
                    event.camera_id,
                    ts_str,
                    1 if event.requires_verification else 0,
                    "pending" if event.requires_verification else "auto_resolved",
                    event.description,
                    obs_json,
                    reasoning,
                    meta_json,
                ),
            )
            conn.commit()

    def verify_event(self, event_id: str, verified_by: str, status: str, notes: str = "") -> bool:
        """Record human verification decision on a security event."""
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE events
                SET verification_status = ?, verified_by = ?, notes = ?
                WHERE event_id = ?
                """,
                (status, verified_by, notes, event_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def query_events(
        self,
        camera_id: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query persistent event history."""
        clauses = []
        params = []
        if camera_id:
            clauses.append("camera_id = ?")
            params.append(camera_id)
        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        if status:
            clauses.append("verification_status = ?")
            params.append(status)

        query = "SELECT * FROM events"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            results = []
            for r in rows:
                ev = dict(r)
                ev["requires_verification"] = bool(ev["requires_verification"])
                ev["supporting_observations"] = json.loads(ev["supporting_observations"]) if ev.get("supporting_observations") else []
                ev["metadata"] = json.loads(ev["metadata"]) if ev.get("metadata") else {}
                results.append(ev)
            return results

    # ---------------------------------------------------------------------------
    # User Management
    # ---------------------------------------------------------------------------

    def upsert_user(self, username: str, password_hash: str, role: Role | str) -> None:
        """Add or update a system user account."""
        now = datetime.now(timezone.utc).isoformat()
        role_val = role.value if hasattr(role, "value") else str(role)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users (username, password_hash, role, is_active, created_at)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(username) DO UPDATE SET
                    password_hash=excluded.password_hash,
                    role=excluded.role;
                """,
                (username, password_hash, role_val, now),
            )
            conn.commit()

    def get_user(self, username: str) -> dict[str, Any] | None:
        """Retrieve user credentials and role."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            return dict(row) if row else None

    # ---------------------------------------------------------------------------
    # Forensic Evidence Manifest Persistence (SEC-03)
    # ---------------------------------------------------------------------------

    def store_privacy_manifest(self, manifest: Any) -> None:
        """Persist a privacy evidence manifest linking original and derivative video frames."""
        now = datetime.now(timezone.utc).isoformat()
        if hasattr(manifest, "to_dict"):
            data = manifest.to_dict()
        elif isinstance(manifest, dict):
            data = manifest
        else:
            data = asdict(manifest)

        meta_json = json.dumps(data.get("metadata", {}))
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO privacy_manifests (
                    manifest_id, camera_id, frame_id, timestamp_utc, original_sha256,
                    derivative_sha256, masking_method, masked_regions_count, privacy_state,
                    fail_closed_active, is_original_preserved, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["manifest_id"],
                    data["camera_id"],
                    data["frame_id"],
                    data["timestamp_utc"],
                    data["original_sha256"],
                    data["derivative_sha256"],
                    data["masking_method"],
                    data["masked_regions_count"],
                    data["privacy_state"] if isinstance(data["privacy_state"], str) else data["privacy_state"].value,
                    1 if data.get("fail_closed_active") else 0,
                    1 if data.get("is_original_preserved", True) else 0,
                    meta_json,
                    now,
                ),
            )
            conn.commit()

    def get_privacy_manifest(self, manifest_id: str) -> dict[str, Any] | None:
        """Retrieve a privacy manifest by its unique manifest ID."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM privacy_manifests WHERE manifest_id = ?", (manifest_id,)).fetchone()
            if not row:
                return None
            res = dict(row)
            res["fail_closed_active"] = bool(res["fail_closed_active"])
            res["is_original_preserved"] = bool(res["is_original_preserved"])
            res["metadata"] = json.loads(res["metadata"]) if res.get("metadata") else {}
            return res

    def get_privacy_manifest_by_original_hash(self, original_sha256: str) -> dict[str, Any] | None:
        """Find the privacy manifest associated with a pristine original evidence frame hash."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM privacy_manifests WHERE original_sha256 = ? ORDER BY timestamp_utc DESC LIMIT 1",
                (original_sha256,),
            ).fetchone()
            if not row:
                return None
            res = dict(row)
            res["fail_closed_active"] = bool(res["fail_closed_active"])
            res["is_original_preserved"] = bool(res["is_original_preserved"])
            res["metadata"] = json.loads(res["metadata"]) if res.get("metadata") else {}
            return res

    def list_privacy_manifests(
        self,
        camera_id: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query privacy manifests filtered by camera and optional time range."""
        clauses = []
        params: list[Any] = []
        if camera_id:
            clauses.append("camera_id = ?")
            params.append(camera_id)
        if start_time:
            clauses.append("timestamp_utc >= ?")
            params.append(start_time)
        if end_time:
            clauses.append("timestamp_utc <= ?")
            params.append(end_time)

        query = "SELECT * FROM privacy_manifests"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY timestamp_utc DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            results = []
            for r in rows:
                m = dict(r)
                m["fail_closed_active"] = bool(m["fail_closed_active"])
                m["is_original_preserved"] = bool(m["is_original_preserved"])
                m["metadata"] = json.loads(m["metadata"]) if m.get("metadata") else {}
                results.append(m)
            return results

    def store_enhancement_manifest(self, manifest: Any) -> None:
        """Persist a forensic image enhancement manifest."""
        now = datetime.now(timezone.utc).isoformat()
        if hasattr(manifest, "to_dict"):
            data = manifest.to_dict()
        elif isinstance(manifest, dict):
            data = manifest
        else:
            data = asdict(manifest)

        methods_json = json.dumps(data.get("applied_methods", []))
        params_json = json.dumps(data.get("parameters", {}))
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO enhancement_manifests (
                    manifest_id, camera_id, frame_id, timestamp_utc, original_sha256,
                    enhanced_sha256, applied_methods, parameters, contrast_before,
                    contrast_after, contrast_gain, is_original_preserved, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["manifest_id"],
                    data["camera_id"],
                    data["frame_id"],
                    data["timestamp_utc"],
                    data["original_sha256"],
                    data["enhanced_sha256"],
                    methods_json,
                    params_json,
                    float(data["contrast_before"]),
                    float(data["contrast_after"]),
                    float(data["contrast_gain"]),
                    1 if data.get("is_original_preserved", True) else 0,
                    now,
                ),
            )
            conn.commit()

    def get_enhancement_manifest(self, manifest_id: str) -> dict[str, Any] | None:
        """Retrieve an enhancement manifest by its unique manifest ID."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM enhancement_manifests WHERE manifest_id = ?", (manifest_id,)).fetchone()
            if not row:
                return None
            res = dict(row)
            res["applied_methods"] = json.loads(res["applied_methods"]) if res.get("applied_methods") else []
            res["parameters"] = json.loads(res["parameters"]) if res.get("parameters") else {}
            res["is_original_preserved"] = bool(res["is_original_preserved"])
            return res

    def list_enhancement_manifests(
        self,
        camera_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List enhancement manifests filtered by camera ID."""
        query = "SELECT * FROM enhancement_manifests"
        params: list[Any] = []
        if camera_id:
            query += " WHERE camera_id = ?"
            params.append(camera_id)
        query += " ORDER BY timestamp_utc DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            results = []
            for r in rows:
                m = dict(r)
                m["applied_methods"] = json.loads(m["applied_methods"]) if m.get("applied_methods") else []
                m["parameters"] = json.loads(m["parameters"]) if m.get("parameters") else {}
                m["is_original_preserved"] = bool(m["is_original_preserved"])
                results.append(m)
            return results

    def verify_manifest_integrity_record(self, manifest_id: str, record_type: str = "privacy") -> bool:
        """Verify that a stored manifest record has well-formed cryptographic hashes and valid metadata."""
        if record_type == "privacy":
            rec = self.get_privacy_manifest(manifest_id)
            if not rec:
                return False
            h_orig = rec.get("original_sha256", "")
            h_deriv = rec.get("derivative_sha256", "")
            return len(h_orig) == 64 and len(h_deriv) == 64 and all(c in "0123456789abcdefABCDEF" for c in h_orig + h_deriv)
        elif record_type == "enhancement":
            rec = self.get_enhancement_manifest(manifest_id)
            if not rec:
                return False
            h_orig = rec.get("original_sha256", "")
            h_enh = rec.get("enhanced_sha256", "")
            return len(h_orig) == 64 and len(h_enh) == 64 and all(c in "0123456789abcdefABCDEF" for c in h_orig + h_enh)
        return False

    # ---------------------------------------------------------------------------
    # NVR Recordings & Segments Persistence
    # ---------------------------------------------------------------------------

    def upsert_recording(self, recording: dict[str, Any]) -> None:
        """Insert or update a recording session record."""
        now = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(recording.get("metadata", {}))
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO recordings (
                    recording_id, camera_id, start_time_utc, end_time_utc, recording_type,
                    status, storage_tier, total_size_bytes, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    recording["recording_id"],
                    recording["camera_id"],
                    recording["start_time_utc"],
                    recording.get("end_time_utc"),
                    recording.get("recording_type", "continuous"),
                    recording.get("status", "recording"),
                    recording.get("storage_tier", "operational"),
                    recording.get("total_size_bytes", 0),
                    meta_json,
                    recording.get("created_at", now),
                ),
            )
            conn.commit()

    # Alias for recording storage naming compatibility
    store_recording = upsert_recording

    def finalize_recording(self, recording_id: str, end_time_utc: str, total_size_bytes: int) -> bool:
        """Mark a recording session as finalized upon clean completion."""
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE recordings
                SET status = 'finalized', end_time_utc = ?, total_size_bytes = ?
                WHERE recording_id = ?
                """,
                (end_time_utc, total_size_bytes, recording_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def get_recording(self, recording_id: str) -> dict[str, Any] | None:
        """Retrieve a recording session by ID."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM recordings WHERE recording_id = ?", (recording_id,)).fetchone()
            if not row:
                return None
            res = dict(row)
            res["metadata"] = json.loads(res["metadata"]) if res.get("metadata") else {}
            return res

    def list_recordings(
        self,
        camera_id: str | None = None,
        recording_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List recordings with optional filters."""
        clauses = []
        params: list[Any] = []
        if camera_id:
            clauses.append("camera_id = ?")
            params.append(camera_id)
        if recording_type:
            clauses.append("recording_type = ?")
            params.append(recording_type)

        query = "SELECT * FROM recordings"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY start_time_utc DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            results = []
            for r in rows:
                rec = dict(r)
                rec["metadata"] = json.loads(rec["metadata"]) if rec.get("metadata") else {}
                results.append(rec)
            return results

    def set_recording_judicial_hold(
        self,
        recording_id: str,
        hold: bool,
        reason: str,
        operator_id: str,
        case_id: str | None = None,
    ) -> bool:
        """Lock or release a recording under judicial hold to prevent deletion and automated purging."""
        rec = self.get_recording(recording_id)
        if not rec:
            return False

        meta = rec.get("metadata", {})
        meta["judicial_hold"] = hold
        meta["judicial_hold_reason"] = reason
        meta["judicial_hold_operator"] = operator_id
        meta["judicial_hold_case_id"] = case_id or ""
        meta["judicial_hold_updated_at"] = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            cur = conn.execute(
                "UPDATE recordings SET metadata = ? WHERE recording_id = ?",
                (json.dumps(meta), recording_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def delete_recording(self, recording_id: str) -> bool:
        """Delete a recording and its associated segments cascade, refusing if locked under judicial hold."""
        rec = self.get_recording(recording_id)
        if rec and rec.get("metadata", {}).get("judicial_hold"):
            raise ValueError(
                f"Cannot delete recording '{recording_id}': active judicial hold "
                f"(reason: {rec['metadata'].get('judicial_hold_reason', 'unspecified')})."
            )

        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM recordings WHERE recording_id = ?", (recording_id,))
            conn.commit()
            return cur.rowcount > 0

    def store_recording_segment(self, segment: dict[str, Any]) -> None:
        """Store metadata for a video chunk segment."""
        now = datetime.now(timezone.utc).isoformat()
        events_json = json.dumps(segment.get("event_ids", []))
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO recording_segments (
                    segment_id, recording_id, camera_id, segment_index, start_time_utc,
                    end_time_utc, duration_seconds, file_path, file_size_bytes, sha256_hash,
                    has_motion, has_event, event_ids, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    segment["segment_id"],
                    segment["recording_id"],
                    segment["camera_id"],
                    segment["segment_index"],
                    segment["start_time_utc"],
                    segment["end_time_utc"],
                    float(segment["duration_seconds"]),
                    segment["file_path"],
                    int(segment["file_size_bytes"]),
                    segment["sha256_hash"],
                    1 if segment.get("has_motion") else 0,
                    1 if segment.get("has_event") else 0,
                    events_json,
                    now,
                ),
            )
            conn.commit()

    def list_recording_segments(self, recording_id: str) -> list[dict[str, Any]]:
        """List all video segments belonging to a recording."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM recording_segments WHERE recording_id = ? ORDER BY segment_index ASC",
                (recording_id,),
            ).fetchall()
            results = []
            for r in rows:
                seg = dict(r)
                seg["has_motion"] = bool(seg["has_motion"])
                seg["has_event"] = bool(seg["has_event"])
                seg["event_ids"] = json.loads(seg["event_ids"]) if seg.get("event_ids") else []
                results.append(seg)
            return results

    def query_segments_by_time_range(
        self,
        camera_id: str,
        start_time_utc: str,
        end_time_utc: str,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Query video segments spanning an arbitrary time window for playback/timeline."""
        query = """
            SELECT * FROM recording_segments
            WHERE camera_id = ?
              AND end_time_utc >= ?
              AND start_time_utc <= ?
            ORDER BY start_time_utc ASC
            LIMIT ?
        """
        with self._get_connection() as conn:
            rows = conn.execute(query, (camera_id, start_time_utc, end_time_utc, limit)).fetchall()
            results = []
            for r in rows:
                seg = dict(r)
                seg["has_motion"] = bool(seg["has_motion"])
                seg["has_event"] = bool(seg["has_event"])
                seg["event_ids"] = json.loads(seg["event_ids"]) if seg.get("event_ids") else []
                results.append(seg)
            return results

    # ---------------------------------------------------------------------------
    # Recording Schedules
    # ---------------------------------------------------------------------------

    def upsert_recording_schedule(self, schedule: dict[str, Any]) -> None:
        """Insert or update a camera recording schedule slot."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO recording_schedules (
                    schedule_id, camera_id, day_of_week, start_time, end_time, mode, is_active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    schedule["schedule_id"],
                    schedule["camera_id"],
                    int(schedule["day_of_week"]),
                    schedule["start_time"],
                    schedule["end_time"],
                    schedule["mode"],
                    1 if schedule.get("is_active", True) else 0,
                    schedule.get("created_at", now),
                ),
            )
            conn.commit()

    def list_recording_schedules(self, camera_id: str) -> list[dict[str, Any]]:
        """List active schedules for a camera."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM recording_schedules WHERE camera_id = ? ORDER BY day_of_week ASC, start_time ASC",
                (camera_id,),
            ).fetchall()
            results = []
            for r in rows:
                s = dict(r)
                s["is_active"] = bool(s["is_active"])
                results.append(s)
            return results

    def delete_recording_schedule(self, schedule_id: str) -> bool:
        """Delete a schedule entry."""
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM recording_schedules WHERE schedule_id = ?", (schedule_id,))
            conn.commit()
            return cur.rowcount > 0

    # ---------------------------------------------------------------------------
    # PTZ Presets
    # ---------------------------------------------------------------------------

    def upsert_ptz_preset(self, preset: dict[str, Any]) -> None:
        """Store or update a camera PTZ preset vector."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO ptz_presets (
                    preset_id, camera_id, name, pan, tilt, zoom, token, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    preset["preset_id"],
                    preset["camera_id"],
                    preset["name"],
                    float(preset["pan"]),
                    float(preset["tilt"]),
                    float(preset["zoom"]),
                    preset.get("token"),
                    now,
                ),
            )
            conn.commit()

    def list_ptz_presets(self, camera_id: str) -> list[dict[str, Any]]:
        """List saved presets for a camera channel."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ptz_presets WHERE camera_id = ? ORDER BY name ASC",
                (camera_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_ptz_preset(self, preset_id: str) -> bool:
        """Delete a PTZ preset."""
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM ptz_presets WHERE preset_id = ?", (preset_id,))
            conn.commit()
            return cur.rowcount > 0

    # ---------------------------------------------------------------------------
    # Camera Groups Persistence
    # ---------------------------------------------------------------------------

    def upsert_camera_group(self, group: dict[str, Any]) -> None:
        """Store or update a camera group in the relational database."""
        now = datetime.now(timezone.utc).isoformat()
        cams_json = json.dumps(group.get("camera_ids", []))
        tags_json = json.dumps(group.get("tags", []))
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO camera_groups (
                    group_id, name, description, camera_ids, site_id, tags, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    group["group_id"],
                    group["name"],
                    group.get("description", ""),
                    cams_json,
                    group.get("site_id", "default"),
                    tags_json,
                    group.get("created_at", now),
                ),
            )
            conn.commit()

    def get_camera_group(self, group_id: str) -> dict[str, Any] | None:
        """Retrieve a camera group by ID."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM camera_groups WHERE group_id = ?", (group_id,)).fetchone()
            if not row:
                return None
            res = dict(row)
            res["camera_ids"] = json.loads(res["camera_ids"]) if res.get("camera_ids") else []
            res["tags"] = json.loads(res["tags"]) if res.get("tags") else []
            return res

    def list_camera_groups(self, site_id: str | None = None) -> list[dict[str, Any]]:
        """List all camera groups."""
        query = "SELECT * FROM camera_groups"
        params: list[Any] = []
        if site_id:
            query += " WHERE site_id = ?"
            params.append(site_id)
        query += " ORDER BY name ASC"

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            results = []
            for r in rows:
                g = dict(r)
                g["camera_ids"] = json.loads(g["camera_ids"]) if g.get("camera_ids") else []
                g["tags"] = json.loads(g["tags"]) if g.get("tags") else []
                results.append(g)
            return results

    def delete_camera_group(self, group_id: str) -> bool:
        """Delete a camera group."""
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM camera_groups WHERE group_id = ?", (group_id,))
            conn.commit()
            return cur.rowcount > 0

